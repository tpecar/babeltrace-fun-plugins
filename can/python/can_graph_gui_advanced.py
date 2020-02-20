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
import types
import collections.abc

from PyQt5.Qt import *
from PyQt5.QtWidgets import *

# import local modules
from graph.event_buffer import AppendableTableModel, AppendableTreeModel
from graph.utils import load_plugins, cmd_parser


class EventClassTreeModel(AppendableTreeModel):
    """
    Extended verison of AppendableTreeModel that contains additional functionality for this GUI.

    Since original class instantiates objects with type(self), this will correctly reference the TreeItem of this class.
    """

    class TreeItem(AppendableTreeModel.TreeItem):
        def __init__(self, data, parent=None):
            super().__init__(data, parent)
            self.count = None

        def data(self, column):
            # if the element is a function, return the result of this function
            data_obj = super().data(column)

            if isinstance(data_obj, types.FunctionType):
                return data_obj()
            else:
                return data_obj

        # Recursively updates the model with payload from event message
        #def update_model(self, payload_field):

        # count_update
        # field_update
        # update model klice eno izemd teh


    def __init__(self, rootItem_data, parent=None):
        super().__init__(rootItem_data, parent)

        # dict to treeModel to correlate between event id - tree item
        self.item = {}

    def reg_event_class(self, item, id):
        item.count = 0
        item.itemData.append(lambda : item.count)

        self.item[id] = item

    def inc_countable(self, event_id):
        item = self.item[event_id]
        item.count += 1

        if item.indexReady():
            itemIdx = list(item.index.values())[-1]
            self.dataChanged.emit(itemIdx, itemIdx)

@bt2.plugin_component_class
class EventBufferSink(bt2._UserSinkComponent):
    """
    Sink component that stores event messages in provided EventBuffer.
    """

    def __init__(self, config, params, obj):
        self._port = self._add_input_port("in")
        (self._tableModel, self._treeModel) = obj

    def _user_graph_is_configured(self):
        self._it = self._create_message_iterator(self._port)

    def _user_consume(self):
        msg = next(self._it)

        # Event class payload field parsing
        if type(msg) == bt2._StreamBeginningMessageConst:
            # Parse event classes
            for event_class in msg.stream.cls.values():

                # Event class payload field parsing
                #
                # More info:
                #
                # Common Trace Format (CTF) documentation
                #   https://diamon.org/ctf/
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
                # The general idea:                Notation: (  is a field_class.py : _FIELD_CLASS_TYPE_TO_OBJ )
                #                                            [[ is an abc.Mapping ]]
                #
                #   event_class (_EventClass)
                #        |
                #    has ---> payload_field_class (_[X]FieldClass)
                #                 |
                #              is |----> scalar field type
                #                 |            |
                #                 |     can be | ---> Boolean           (_BoolFieldClass)
                #                 |            OR --> Bit array         (_BitArrayFieldClass)
                #                 |            OR --> Integer           (_UnsignedIntegerFieldClass / _SignedIntegerFieldClass)
                #                 |            OR --> [[ Enumeration ]] (_UnsignedEnumerationFieldClass / _SignedEnumerationFieldClass)
                #                 OR           |
                #                 |            |
                #                 |            OR --> Real              (_SinglePrecisionRealFieldClass / _DoublePrecisionRealFieldClass)
                #                 |            OR --> String            (_StringFieldClass)
                #                 |
                #                 |
                #                 -----> container field type
                #                              |
                #                       can be | ---> Array             (_StaticArrayFieldClass / _DynamicArrayFieldClass / _DynamicArrayWithLengthFieldFieldClass)
                #                              OR --> [[ Structure ]]   (_StructureFieldClass)
                #                              |
                #                              |
                #                              OR --> Option            (_OptionFieldClass / _OptionWithBoolSelectorFieldClass / _OptionWithUnsignedIntegerSelectorFieldClass / _OptionWithSignedIntegerSelectorFieldClass)
                #                              OR --> [[ Variant ]]     (_VariantFieldClassWithoutSelector / _VariantFieldClassWithUnsignedIntegerSelector / _VariantFieldClassWithSignedIntegerSelector)
                #

                # Create node with update_model handler for event class
                event_class_item = self._treeModel.rootItem.appendItem(
                    (f"{event_class.id} : {event_class.name}", type(event_class)._NAME)
                )

                # Parse field classes recursively
                def parse_field_class(parent_field_class, parent_item):

                    # Container type
                    if issubclass(type(parent_field_class), collections.abc.Mapping):

                        # Create node with update_model handler for container type
                        field_class_item = parent_item.appendItem((name, type(parent_field_class)._NAME))

                        # Recursively parse its members
                        for member in parent_field_class.values():
                            parse_field_class(member.field_class, member.name, field_class_item)

                    # Scalar type
                    else:
                        # Create node with update_model handler for scalar type
                        field_class_item = parent_item.appendItem((name, type(parent_field_class)._NAME))

                parse_field_class(event_class.payload_field_class, event_class_item)

        if type(msg) == bt2._EventMessageConst:
            # Save event to buffer
            self._tableModel.append((msg.default_clock_snapshot.value, msg.event.name, str(msg.event.payload_field)))
            self._treeModel.inc_countable(msg.event.id)

# MainWindow
#
class MainWindow(QMainWindow):

    def __init__(self, tableModel, treeModel):
        super().__init__()
        self._tableModel = tableModel
        self._treeModel = treeModel

        self.setWindowTitle("Advanced Babeltrace2 GUI demo")

        # Table view
        self._tableView = QTableView()
        self._tableView.setModel(tableModel)
        self._tableView.loaded = False

        self._tableView.setEditTriggers(QTableWidget.NoEditTriggers)    # read-only
        self._tableView.verticalHeader().setDefaultSectionSize(10)      # row height
        self._tableView.horizontalHeader().setStretchLastSection(True)  # last column resizes to widget width

        # Tree view
        self._treeView = QTreeView()
        self._treeView.setModel(self._treeModel)

        self._treeView.setUniformRowHeights(True)  # https://doc.qt.io/qt-5/qtreeview.html#uniformRowHeights-prop

        # Statistics label
        self._statLabel = QLabel("Events (processed/loaded): - / -")

        # Refresh checkbox
        self._followCheckbox = QCheckBox("Follow events")
        self._followCheckbox.setChecked(True)

        # Layout
        self._layout = QGridLayout()
        self._splitter = QSplitter()

        # See https://doc.qt.io/qt-5/qgridlayout.html#addWidget-2
        #
        #   0               1
        # 0 [ QSplitter                        ]
        #   [ [< treeView ] [< tableView     ] ]
        #
        # 1 [< statLabel  ] [followCheckbox   >]
        #
        self._splitter.addWidget(self._treeView)
        self._splitter.addWidget(self._tableView)
        self._layout.addWidget(self._splitter, 0, 0, 1, 2)

        self._layout.addWidget(self._statLabel, 1, 0)
        self._layout.addWidget(self._followCheckbox, 1, 1, 1, 1, Qt.AlignRight)

        self._mainWidget = QWidget()
        self._mainWidget.setLayout(self._layout)

        self.setCentralWidget(self._mainWidget)

        # Widget sizes
        self._splitter.setStretchFactor(0, 45)
        self._splitter.setStretchFactor(1, 55)
        self.resize(750, 450)

    # Timer handler, provided by QObject
    # https://doc.qt.io/qt-5/qtimer.html#alternatives-to-qtimer
    @pyqtSlot()
    def timerEvent(self, QTimerEvent):

        # Statistics
        self._statLabel.setText(f"Events (processed/loaded): {len(self._tableModel._table)} / {self._tableModel.rowCount()}")

        # Signal views to start fetching model data
        if not self._tableView.loaded and self._treeModel.rowCount(QModelIndex()):
            self._treeModel.modelReset.emit()
            self._treeView.resizeColumnToContents(0)
            self._tableView.loaded = True

        if not self._tableModel.rowCount():
            self._tableModel.modelReset.emit()

        # Follow events
        if self._followCheckbox.isChecked():
            # QTableView also provides scrollToBottom(), but that method seems to have issues
            # with skipping multiple rows - rows appear to "bounce"
            self._tableView.scrollTo(self._tableModel.index(self._tableModel.rowCount() - 1, 0), QAbstractItemView.PositionAtBottom)


# GUI Application
def main():
    global CANSource_data_path, CANSource_dbc_path
    global plugins

    app = QApplication([])

    # Data models
    tableModel = AppendableTableModel(('Timestamp', 'Event', 'Payload'))
    treeModel = EventClassTreeModel(("Name", "Type", "Count / Last Value"))

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
    graph_sink = graph.add_component(EventBufferSink, 'sink', obj=(tableModel, treeModel))

    # Connect components together
    graph.connect_ports(
        list(graph_source.output_ports.values())[0],
        list(graph_sink.input_ports.values())[0]
    )


    # Main window
    mainWindow = MainWindow(tableModel, treeModel)

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
