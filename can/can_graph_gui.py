#!/usr/bin/env python3
# *_* coding: utf-8 *_*

"""
Creates and runs a graph with a can.CANSource source and in-app sink, which delegates stream info to the GUI.
---
Please note: libbabeltrace2 python library (bt2) depends on its core C library.
---
LD_LIBRARY_PATH=[babeltrace2 build folder]/src/lib/.libs/
BABELTRACE_PLUGIN_PATH = [babeltrace2 build folder]/src/plugins/[plugin name]
LIBBABELTRACE2_PLUGIN_PROVIDER_DIR = [babeltrace2 build folder]/src/python-plugin-provider/.libs/
"""

import bt2
import numpy as np

import argparse

from PyQt5.Qt import *
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *

# Event buffer, implemented as a list of fixed size buffers.
#
class EventBuffer:
    def __init__(self, event_block_sz, event_dtype):
        self._blocksz = event_block_sz
        self._dtype = event_dtype
        self._buffer = [ np.empty(self._blocksz, dtype=self._dtype) ]
        self._fblocks = 0    # Number of fully used blocks
        self._lbufsiz = 0    # Number of saved events in the last block

    def __len__(self):
        return self._fblocks * self._blocksz + self._lbufsiz

    def __getitem__(self, idx):
        if idx > len(self):
            raise IndexError

        return self._buffer[idx // self._blocksz][idx % self._blocksz]

    @property
    def dtype(self):
        return self._dtype

    def append(self, event):
        if self._lbufsiz == self._blocksz:
            new_block = np.empty(self._blocksz, dtype=self._dtype)
            new_block[0] = event
            self._buffer.append(new_block)

            self._lbufsiz = 1
            self._fblocks += 1
        else:
            self._buffer[self._fblocks][self._lbufsiz] = event
            self._lbufsiz += 1

# Loads system & user plugins to 'plugins' global
def load_plugins():
    global system_plugin_path, plugin_path
    global plugins

    # Load plugins
    system_plugins = bt2.find_plugins_in_path(system_plugin_path) if system_plugin_path else bt2.find_plugins()
    user_plugins = bt2.find_plugins_in_path(plugin_path)

    assert system_plugins, "No system plugins found!"
    assert user_plugins, "No user plugins found!"

    # Convert _PluginSet to dict
    plugins = {
        **{plugin.name: plugin for plugin in system_plugins},
        **{plugin.name: plugin for plugin in user_plugins}
    }

# Sink component that emits signals @ event
@bt2.plugin_component_class
class EventBufferSink(bt2._UserSinkComponent):

    def __init__(self, config, params, obj):
        self._port = self._add_input_port("in")
        self._buffer = obj

    def _user_graph_is_configured(self):
        self._it = self._create_message_iterator(self._port)

    def _user_consume(self):
        # Consume one message and print it.
        msg = next(self._it)

        handler = {
            bt2._StreamBeginningMessageConst :
                lambda : "Stream begin",
            bt2._PacketBeginningMessageConst :
                lambda : "Packet begin",

            bt2._EventMessageConst :
                # Save event to buffer
                lambda : self._buffer.append( (msg.default_clock_snapshot.value, msg.event.name) ),

            bt2._PacketEndMessageConst:
                lambda : "Packet end",
            bt2._StreamEndMessageConst:
                lambda : "Stream end"
        }
        try:
            msg = handler[type(msg)]()
            if msg:
                print(msg)
        except KeyError:
            raise RuntimeError("Unhandled message type", type(msg))


# Graph processing thread
#
# We're using the QThread subclassing approach, check gotchas at
# https://doc.qt.io/qt-5/qthread.html
# https://mayaposch.wordpress.com/2011/11/01/how-to-really-truly-use-qthreads-the-full-explanation/
#
class BT2GraphThread(QThread):

    def __init__(self, buffer, parent=None):
        super(BT2GraphThread, self).__init__(parent)

        global CANSource_data_path, CANSource_dbc_path
        global plugins

        # Load required components from plugins
        source = plugins['can'].source_component_classes['CANSource']

        # Create graph and add components
        self._graph = graph = bt2.Graph()

        graph_source = graph.add_component(source, 'source',
            params=bt2.MapValue({
                'inputs': bt2.ArrayValue([CANSource_data_path]),
                'databases': bt2.ArrayValue([CANSource_dbc_path])
            })
        )

        # Do note: event_signal is static, but it has to be accessed through instance
        # (via self.) in order to be "bound" (expose the .emit() method)
        graph_sink = graph.add_component(EventBufferSink, 'sink', obj=buffer)

        # Connect components together
        graph.connect_ports(
            list(graph_source.output_ports.values())[0],
            list(graph_sink.input_ports.values())[0]
        )

    def __del__(self):
        self.wait()

    def run(self):
        # Run graph
        self._graph.run()


# Data model that uses fetchMore mechanism for on-demand row loading.
#
# More info on
#   https://doc.qt.io/qt-5/qabstracttablemodel.html
#   https://sateeshkumarb.wordpress.com/2012/04/01/paginated-display-of-table-data-in-pyqt/
#   /examples/itemviews/fetchmore.py
#   /examples/itemviews/storageview.py
#   /examples/multimediawidgets/player.py
#
class EventTableModel(QAbstractTableModel):
    def __init__(self, data_obj=None, parent=None):
        super(QAbstractTableModel, self).__init__(parent)

        self.data = data_obj
        self.data_headers = None

        self.data_columnCount = 0   # Displayed column count
        self.data_rowCount = 0      # Displayed row count

    def rowCount(self, parent=QModelIndex()):
        return self.data_rowCount if not parent.isValid() else 0

    def columnCount(self, parent=QModelIndex()):
        return self.data_columnCount if not parent.isValid() else 0

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and index.isValid() and self.data:
            # This is where we return data to be displayed
            return str(self.data[index.row()][index.column()])

        return None

    def setHorizontalHeaderLabels(self, headers):
        self.data_headers = headers
        self.data_columnCount = len(headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal and section < len(self.data_headers):
                return self.data_headers[section]
        return None

    def canFetchMore(self, index):
        return self.data_rowCount < len(self.data)

    def fetchMore(self, index):
        itemsToFetch = len(self.data) - self.data_rowCount

        self.beginInsertRows(QModelIndex(), self.data_rowCount+1, self.data_rowCount + itemsToFetch)
        self.data_rowCount += itemsToFetch
        self.endInsertRows()

# GUI Application
def main():
    app = QApplication([])

    # Event buffer
    buffer = EventBuffer(event_block_sz=500, event_dtype=np.dtype( [('timestamp', np.int32), ('name', 'U25')] ))

    # BT2 Graph thread
    graph_thread = BT2GraphThread(buffer)

    # Data model
    model = EventTableModel(buffer)
    model.setHorizontalHeaderLabels(buffer.dtype.names)

    # Table window
    tableView = QTableView()
    tableView.setWindowTitle("Sink data")
    tableView.setModel(model)

    tableView.setEditTriggers(QTableWidget.NoEditTriggers)  # read-only
    tableView.verticalHeader().setDefaultSectionSize(10)    # row height

    # Start graph thread
    graph_thread.start(QThread.LowestPriority)

    # Start GUI event loop
    tableView.show()
    app.exec_()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "--system-plugin-path", type=str, default=None,
        help="Specify folder for system plugins (recursive!). "
             "Alternatively, set BABELTRACE_PLUGIN_PATH (non-recursive!)"
    )
    parser.add_argument(
        "--plugin-path", type=str, default="./python/",
        help="Path to 'bt_user_can.(so|py)' plugin"
    )
    parser.add_argument(
        "--CANSource-data-path", type=str, default="./test.data",
        help="Path to test data required by bt_user_can"
    )
    parser.add_argument(
        "--CANSource-dbc-path", type=str, default="./database.dbc",
        help="Path to DBC (CAN Database) required by bt_user_can"
    )

    # Add parameters to globals
    globals().update(vars(parser.parse_args()))

    load_plugins()
    main()