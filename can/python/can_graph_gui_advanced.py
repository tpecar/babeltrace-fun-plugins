#!/usr/bin/env python3
# *_* coding: utf-8 *_*

"""
Creates and runs a graph with a can.CANSource source and in-app sink, which delegates stream info to the GUI.
A more complex example which allows for faster graph execution.
---
Please note: libbabeltrace2 python library (bt2) depends on its core C library.
---
LD_LIBRARY_PATH=[babeltrace2 build folder]/src/lib/.libs/
BABELTRACE_PLUGIN_PATH = [babeltrace2 build folder]/src/plugins/[plugin name]
LIBBABELTRACE2_PLUGIN_PROVIDER_DIR = [babeltrace2 build folder]/src/python-plugin-provider/.libs/
"""

import bt2
import collections.abc
import numpy as np

from PyQt5.Qt import *
from PyQt5.QtWidgets import *

# import local modules
from graph.event_buffer import EventBuffer, EventBufferTableModel
from graph.utils import load_plugins, cmd_parser


# Tree view
#
# PyQt5-5.14.2.devX/examples/itemviews/simpletreemodel/simpletreemodel.py
# PyQt5-5.14.2.devX/examples/itemviews/editabletreemodel/editabletreemodel.py
#
class TreeItem(object):
    def __init__(self, data, parent=None):
        self.parentItem = parent
        self.itemData = data
        self.childItems = []

    def appendChild(self, item):
        self.childItems.append(item)

    def child(self, row):
        return self.childItems[row]

    def childCount(self):
        return len(self.childItems)

    def columnCount(self):
        return len(self.itemData)

    def data(self, column):
        try:
            return self.itemData[column]
        except IndexError:
            return None

    def parent(self):
        return self.parentItem

    def row(self):
        if self.parentItem:
            return self.parentItem.childItems.index(self)

        return 0

class TreeModel(QAbstractItemModel):
    def __init__(self, rootItem, parent=None):
        super(TreeModel, self).__init__(parent)

        self.rootItem = rootItem

    def columnCount(self, parent):
        if parent.isValid():
            return parent.internalPointer().columnCount()
        else:
            return self.rootItem.columnCount()

    def data(self, index, role):
        if not index.isValid():
            return None

        if role != Qt.DisplayRole:
            return None

        item = index.internalPointer()

        return item.data(index.column())

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags

        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def headerData(self, section, orientation, role):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.rootItem.data(section)

        return None

    def index(self, row, column, parent):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()

        if not parent.isValid():
            parentItem = self.rootItem
        else:
            parentItem = parent.internalPointer()

        childItem = parentItem.child(row)
        if childItem:
            return self.createIndex(row, column, childItem)
        else:
            return QModelIndex()

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()

        childItem = index.internalPointer()
        parentItem = childItem.parent()

        if parentItem == self.rootItem:
            return QModelIndex()

        return self.createIndex(parentItem.row(), 0, parentItem)

    def rowCount(self, parent):
        if parent.column() > 0:
            return 0

        if not parent.isValid():
            parentItem = self.rootItem
        else:
            parentItem = parent.internalPointer()

        return parentItem.childCount()


@bt2.plugin_component_class
class EventBufferSink(bt2._UserSinkComponent):
    """
    Sink component that stores event messages in provided EventBuffer.
    """

    def __init__(self, config, params, obj):
        self._port = self._add_input_port("in")
        self._buffer = obj

    def _user_graph_is_configured(self):
        self._it = self._create_message_iterator(self._port)

    def _user_consume(self):
        msg = next(self._it)

        # Event class payload field parsing
        #
        # More info:
        #
        # C documentation for Stream / Event / Field classes
        #   https://babeltrace.org/docs/v2.0/libbabeltrace2/group__api-tir-stream-cls.html
        #   https://babeltrace.org/docs/v2.0/libbabeltrace2/group__api-tir-ev-cls.html
        #   https://babeltrace.org/docs/v2.0/libbabeltrace2/group__api-tir-ev-cls.html#api-tir-ev-cls-prop-p-fc
        #   https://babeltrace.org/docs/v2.0/libbabeltrace2/group__api-tir-fc.html
        #
        # Python wrapper
        #   babeltrace-2.0.0/src/bindings/python/bt2/bt2/stream_class.py
        #   babeltrace-2.0.0/src/bindings/python/bt2/bt2/field_class.py
        #
        # text.details sink source
        #   babeltrace-2.0.0/src/plugins/text/details/write.c
        #       static void write_stream_class(struct details_write_ctx *ctx, const bt_stream_class *sc) definition
        #       static void write_event_class(struct details_write_ctx *ctx, const bt_event_class *ec) definition
        #       static void write_field_class(struct details_write_ctx *ctx, const bt_field_class *fc) definition
        #
        if type(msg) == bt2._StreamBeginningMessageConst:
            # Parse event classes
            for event_class in msg.stream.cls.values():
                # Parse field classes recursively
                def parse_container(container, name, level=0):
                    print(f"{' '*(5*level)}{name} : {type(container)._NAME}")

                    # If member is a container type, iterate over it
                    if issubclass(type(container), collections.abc.Mapping):
                        for member in container.values():
                            parse_container(member.field_class, member.name, level+1)

                parse_container(event_class.payload_field_class, f"{event_class.id:3}: {event_class.name}")
                print()

        if type(msg) == bt2._EventMessageConst:
            # Save event to buffer
            self._buffer.append((msg.default_clock_snapshot.value, msg.event.name))


# MainWindow
#
class MainWindow(QMainWindow):

    def __init__(self, buffer, tableModel):
        super().__init__()
        self._buffer = buffer
        self._tableModel = tableModel

        self.setWindowTitle("Responsive Babeltrace2 GUI demo")

        # Table view
        self._tableView = QTableView()
        self._tableView.setWindowTitle("Sink data")
        self._tableView.setModel(tableModel)

        self._tableView.setEditTriggers(QTableWidget.NoEditTriggers)    # read-only
        self._tableView.verticalHeader().setDefaultSectionSize(10)      # row height
        self._tableView.horizontalHeader().setStretchLastSection(True)  # last column resizes to widget width

        # Tree view
        #
        # PyQt5-5.14.2.devX/examples/itemviews/simpletreemodel/simpletreemodel.py
        # PyQt5-5.14.2.devX/examples/itemviews/editabletreemodel/editabletreemodel.py
        #
        self._treeModel = TreeModel(TreeItem( ("Column 1", "Column 2", "Column 3") ))

        item1 = TreeItem( ("Test 1", "Test 2", "Test 3"), self._treeModel.rootItem )
        self._treeModel.rootItem.appendChild(item1)

        item2 = TreeItem( ("Test 21", "Test 22", "Test 23"), item1 )
        item1.appendChild(item2)

        self._treeView = QTreeView()
        self._treeView.setModel(self._treeModel)
        self._treeView.expandAll()
        self._treeView.setItemsExpandable(False)

        # Statistics label
        self._statLabel = QLabel("Events (processed/loaded): - / -")

        # Refresh checkbox
        self._followCheckbox = QCheckBox("Follow events")
        self._followCheckbox.setChecked(True)

        # Layout
        self._layout = QGridLayout()

        # See https://doc.qt.io/qt-5/qgridlayout.html#addWidget-2
        #
        #    0           1
        # 0 [< treeView ] [< tableView     ]
        # 1 [< statLabel] [followCheckbox >]
        #
        self._layout.addWidget(self._treeView,  0, 0)
        self._layout.addWidget(self._tableView, 0, 1)
        self._layout.addWidget(self._statLabel, 1, 0)
        self._layout.addWidget(self._followCheckbox, 1, 1, 1, 1, Qt.AlignRight)

        self._mainWidget = QWidget()
        self._mainWidget.setLayout(self._layout)

        self.setCentralWidget(self._mainWidget)

    # Timer handler, provided by QObject
    # https://doc.qt.io/qt-5/qtimer.html#alternatives-to-qtimer
    @pyqtSlot()
    def timerEvent(self, QTimerEvent):

        # Statistics
        self._statLabel.setText(f"Events (processed/loaded): {len(self._buffer)} / {self._tableModel.rowCount()}")

        # Force the view to call canFetchMore / fetchMore initially
        if not self._tableModel.rowCount():
            self._tableModel.modelReset.emit()

        # Follow events
        if self._followCheckbox.isChecked():
            # The following could be achieved similarly with self._tableView.scrollToBottom(), but that method has
            # issues with skipping multiple rows - rows appear to "bounce" and it's hard to look at the output
            #
            self._tableView.scrollTo(self._tableModel.index(self._tableModel.rowCount() - 1, 0), QAbstractItemView.PositionAtBottom)


# GUI Application
def main():
    global CANSource_data_path, CANSource_dbc_path
    global plugins

    app = QApplication([])

    # Event buffer
    buffer = EventBuffer(event_block_sz=500, event_dtype=np.dtype([('timestamp', np.int32), ('name', 'U35')]))

    # Create graph and add components
    graph = bt2.Graph()

    source = plugins['can'].source_component_classes['CANSource']
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


    # Data model
    model = EventBufferTableModel(buffer)
    model.setHorizontalHeaderLabels(buffer.dtype.names)

    # Main window
    mainWindow = MainWindow(buffer, model)

    # Run graph as part of the GUI event loop
    # https://stackoverflow.com/questions/36988826/running-code-in-the-main-loop
    graph_timer = QTimer()

    def run_graph():
        try:
            graph.run_once()
        except bt2.Stop:
            print("Graph finished execution.")
            graph_timer.stop()

    graph_timer.timeout.connect(run_graph)
    graph_timer.start()

    # Start GUI event loop
    mainWindow.show()
    mainWindow.startTimer(100) # Update stats & refresh interval in ms

    app.exec_()
    print("Done.")


if __name__ == "__main__":
    global system_plugin_path, plugin_path
    global plugins

    # Parse command line and add parsed parameters to globals
    parser = cmd_parser(__doc__)
    globals().update(vars(parser.parse_args()))

    plugins = load_plugins(system_plugin_path, plugin_path)
    main()
