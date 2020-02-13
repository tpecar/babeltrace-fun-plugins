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

import time
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
        msg = next(self._it)

        if type(msg) == bt2._EventMessageConst:
            # Save event to buffer
            self._buffer.append((msg.default_clock_snapshot.value, msg.event.name))


# Graph thread manager - or how to enter Signal / Slot / QtEvent hell
# -- Has to be started in GUI thread. --
#
# The idea is that the graph thread emits a signal through a BlockingQueuedConnection, which causes it to block,
# allowing the transition back to the main (GUI) thread, which will process all current events and the
# graph thread event, allowing it to be scheduled in the future.
#
# More info
#   https://doc.qt.io/qt-5/eventsandfilters.html
#   https://doc.qt.io/qt-5/qabstracteventdispatcher.html
#   https://doc.qt.io/qt-5/qcoreapplication.html
#
#   https://doc.qt.io/qt-5/signalsandslots.html
#   https://doc.qt.io/qt-5/qt.html#ConnectionType-enum
#   https://woboq.com/blog/how-qt-signals-slots-work-part3-queuedconnection.html
#
#   PyQt5-5.14.2.dev2002051759/qpy/QtCore/qpycore_pyqtboundsignal.cpp
#
class BT2GraphThreadManager(QObject):

    @pyqtSlot()
    def wake_graph_thread(self):
        # Invoked from the main thread event queue (presumably when other events are processed).
        #
        # Since the signal-slot connection is BlockingQueuedConnection, the sole fact that slot was invoked is enough
        # to reschedule the graph thread.
        pass

    def __init__(
            self,
            buffer,
            thread_time=0.05 # Time in s the graph thread can process before being blocked
    ):
        super().__init__()

        self.thread = QThread()

        self.worker = BT2GraphWorker(buffer, self.wake_graph_thread, thread_time)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.work)   # QThread will start the work() slot in new thread

    def start(self):
        self.thread.start()

# Graph processing thread
#
# Check Qt multithreading gotchas at
# https://doc.qt.io/qt-5/qthread.html
# https://mayaposch.wordpress.com/2011/11/01/how-to-really-truly-use-qthreads-the-full-explanation/
# https://www.kdab.com/wp-content/uploads/stories/slides/DD12/Multithreading_Presentation.pdf
#
# IDEs have only support for QtThreads
# https://youtrack.jetbrains.com/issue/PY-24162
# https://intellij-support.jetbrains.com/hc/en-us/community/posts/203420404-Pycharm-debugger-not-stopping-on-QThread-breakpoints
#
class BT2GraphWorker(QObject):

    _blocking_signal = pyqtSignal()

    def __init__(self, buffer, wake_slot, thread_time):
        super().__init__()
        self._buffer = buffer
        self._running = True
        self._thread_time = thread_time

        self._blocking_signal.connect(wake_slot, type=Qt.BlockingQueuedConnection)

    @pyqtSlot()
    def work(self):
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
        graph_sink = graph.add_component(EventBufferSink, 'sink', obj=self._buffer)

        # Connect components together
        graph.connect_ports(
            list(graph_source.output_ports.values())[0],
            list(graph_sink.input_ports.values())[0]
        )

        # Timer that will periodically yield the graph processing thread for better UI responsiveness
        #
        # While we have QTimers and all that jazz, both python threading and Qt's event loop mechanism seem to have
        # a very hard time interrupting a fast loop that jumps into native code, so we implement it manually.
        #
        self._last_wait_time = time.clock_gettime(time.CLOCK_PROCESS_CPUTIME_ID)

        # Run graph
        while self._running:
            self._graph.run_once()

            if time.clock_gettime(time.CLOCK_PROCESS_CPUTIME_ID) - self._last_wait_time > self._thread_time:
                # Block graph thread
                self._blocking_signal.emit()
                # Reset timer when we return
                self._last_wait_time = time.clock_gettime(time.CLOCK_PROCESS_CPUTIME_ID)

    @pyqtSlot()
    def stop(self):
        self._running = False


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

        self._data = data_obj
        self._data_headers = None

        self._data_columnCount = 0   # Displayed column count
        self._data_rowCount = 0      # Displayed row count

    def rowCount(self, parent=QModelIndex()):
        return self._data_rowCount if not parent.isValid() else 0

    def columnCount(self, parent=QModelIndex()):
        return self._data_columnCount if not parent.isValid() else 0

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and index.isValid() and self._data:
            # This is where we return data to be displayed
            return str(self._data[index.row()][index.column()])

        return None

    def setHorizontalHeaderLabels(self, headers):
        self._data_headers = headers
        self._data_columnCount = len(headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal and section < len(self._data_headers):
                return self._data_headers[section]
        return None

    def canFetchMore(self, index):
        return self._data_rowCount < len(self._data)

    def fetchMore(self, index):
        itemsToFetch = len(self._data) - self._data_rowCount

        self.beginInsertRows(QModelIndex(), self._data_rowCount + 1, self._data_rowCount + itemsToFetch)
        self._data_rowCount += itemsToFetch
        self.endInsertRows()

# Reference to BT2GraphThreadManager instance needs to be global to survive main exit, which happens before
# aboutToQuit is called
#
# TODO: there still seems to be a race condition during program close

# Event buffer
buffer = EventBuffer(event_block_sz=500, event_dtype=np.dtype( [('timestamp', np.int32), ('name', 'U25')] ))

# Graph thread machinery
graph_thread = BT2GraphThreadManager(buffer)

# GUI Application
def main():
    global graph_thread

    app = QApplication([])

    # Data model
    model = EventTableModel(buffer)
    model.setHorizontalHeaderLabels(buffer.dtype.names)

    # Table window
    tableView = QTableView()
    tableView.setWindowTitle("Sink data")
    tableView.setModel(model)

    tableView.setEditTriggers(QTableWidget.NoEditTriggers)  # read-only
    tableView.verticalHeader().setDefaultSectionSize(10)    # row height

    # Configure stop signal and start graph thread
    app.aboutToQuit.connect(graph_thread.worker.stop)  # Stop processing the graph if gui quit
    graph_thread.start()

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