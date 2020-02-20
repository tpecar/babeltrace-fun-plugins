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
        def __init__(self, data, parent=None, model=None):
            super().__init__(data, parent)
            self.model = model
            self.update = None              # Set up @ bt2._StreamBeginningMessageConst - dej stran

        def getState(self):
            return self.itemData[2]         # [2] is the "Count / Last Value" column

        def setState(self, state):
            self.itemData[2] = state

            # Notify view
            if self.indexReady():
                itemIdx = self.index[2]
                self.model.dataChanged.emit(itemIdx, itemIdx)

        def appendItem(self, item_data):
            item = type(self)(item_data, self, self.model)
            self.childItems.append(item)
            return item

    def __init__(self, rootItem_data, parent=None):
        super().__init__(rootItem_data, parent)
        self.rootItem.model = self

        # event id -> event class TreeItem
        self.event_class_item = {}

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
        # Python bindings
        #   babeltrace-2.0.0/src/bindings/python/bt2/bt2/stream_class.py
        #   babeltrace-2.0.0/src/bindings/python/bt2/bt2/field_class.py
        #   babeltrace-2.0.0/src/bindings/python/bt2/bt2/field.py
        #   babeltrace-2.0.0/tests/bindings/python/bt2/test_field.py
        #
        # text.details sink source
        #   babeltrace-2.0.0/src/plugins/text/details/write.c
        #       static void write_stream_class(struct details_write_ctx *ctx, const bt_stream_class *sc) definition
        #       static void write_event_class(struct details_write_ctx *ctx, const bt_event_class *ec) definition
        #       static void write_field_class(struct details_write_ctx *ctx, const bt_field_class *fc) definition
        #
        # The general idea:                Notation: (  is a field_class.py : _FIELD_CLASS_TYPE_TO_CONST_OBJ )
        #                                            [[ is an abc.Mapping ]]
        #   event_class ( _EventClass )
        #        |
        #    has ---> payload_field_class ( _[X]FieldClass )    <------------------------------------------------- <
        #               |                                                                                          |
        #            is |---> scalar field type                                                                    |
        #               |        |                                                                                 |
        #               | can be | ---> Boolean           ( _BoolFieldClassConst )                                 |
        #               |        |                                                                                 |
        #               |        OR --> Bit array         ( _BitArrayFieldClassConst )                             |
        #               |        |                                                                                 |
        #               |        OR --> Integer           ( _UnsignedIntegerFieldClassConst )                      |
        #               |        |                        ( _SignedIntegerFieldClassConst )                        |
        #               |        |                                                                                 |
        #               OR       OR --> [[ Enumeration ]] ( _UnsignedEnumerationFieldClassConst )                  |
        #               |        |            |           ( _SignedEnumerationFieldClassConst )                    |
        #               |        |        has ---> (?)                                                             |
        #               |        |                                                                                 |
        #               |        OR --> Real              ( _SinglePrecisionRealFieldClassConst )                  ^
        #               |        |                        ( _DoublePrecisionRealFieldClassConst )                  |
        #               |        |                                                                                 |
        #               |        OR --> String            ( _StringFieldClassConst )                               |
        #               |                                                                                          |
        #               |                                                                                          |
        #               ----> container field type                                                                 |
        #                        |                                                                                 |
        #                 can be | ---> Array             ( _StaticArrayFieldClassConst )                          |
        #                        |                        ( _DynamicArrayFieldClassConst )                         |
        #                        |                        ( _DynamicArrayWithLengthFieldFieldClassConst )          |
        #                        |                                                                                 |
        #                        OR --> [[ Structure ]]   ( _StructureFieldClassConst )                            |
        #                        |            |                                                                    |
        #                        |        has ---> _StructureFieldClassMember                                      |
        #                        |                      |                                                          |
        #                        |                  has ---> field_class ( _[X]FieldClass ) --->------------------ ^
        #                        |
        #                        OR --> Option            ( _OptionFieldClassConst )
        #                        |         |              ( _OptionWithBoolSelectorFieldClassConst )
        #                        |     has ---> (?)       ( _OptionWithUnsignedIntegerSelectorFieldClassConst )
        #                        |                        ( _OptionWithSignedIntegerSelectorFieldClassConst )
        #                        |
        #                        OR --> [[ Variant ]]     ( _VariantFieldClassWithoutSelector )
        #                                     |           ( _VariantFieldClassWithUnsignedIntegerSelectorConst )
        #                                     |           ( _VariantFieldClassWithSignedIntegerSelectorConst )
        #                                 has ---> (?)
        #
        #   list(msg.stream.cls.values())[0] ----------------------------->  _EventClassConst
        #                                                                     defined @ event_class.py
        #   if type(msg) == bt2._StreamBeginningMessageConst:
        #       list(msg.stream.cls.values())[0].payload_field_class ----->  _[X]FieldClassConst
        #                                                                     defined @ field_class.py:
        #                                                                    _FIELD_CLASS_TYPE_TO_CONST_OBJ
        #   if type(msg) == bt2._EventMessageConst:
        #       list(msg.event.payload_field.values())[0] ---------------->  _[X]FieldConst
        #                                                                     defined @ field.py:
        #                                                                    _FIELD_CLASS_TYPE_TO_OBJ

        if type(msg) == bt2._StreamBeginningMessageConst:

            # Parse event classes
            for event_class in msg.stream.cls.values():

                # Create node with update_model handler for event class
                event_class_item = self._treeModel.rootItem.appendItem(
                    [f"{event_class.id} : {event_class.name}", event_class.name, 0]
                )

                # We use closures to bind the model update handler back to the tree item
                # We use attributes attached bound to the handler function itself to recursively call update handlers
                def update_event_class_closure():
                    def update_event_class(payload):
                        event_class_item.setState(event_class_item.getState() + 1)

                        # Recursively call update handlers for field classes
                        # The called update handler should have the capability to iterate over input if the provided
                        # payload is a map.
                        update_event_class.update(payload.payload_field)
                    return update_event_class

                # ker vracamo zdaj handlerje z returni, je ta lahko tehnicno za parse_field_class

                event_class_item.update = update_event_class_closure()

                # Parse field classes + attach update handlers recursively
                def parse_field_class(name, parent_field_class, parent_item):

                    field_class_item = parent_item.appendItem([name, type(parent_field_class)._NAME, '-'])

                    # abc.Mapping type
                    # TODO: check if a different model would be better for handling container types
                    if issubclass(type(parent_field_class), collections.abc.Mapping):
                        # Create node with update_model handler for specific container type
                        # [[ Enumeration ]] -> parent displays type + state, children display possible states
                        # [[ Structure ]]   -> parent displays type, children display type + state
                        # [[ Variant ]]     -> parent displays type + selected variant, children are
                        #                           possible representations, selected representation displays state
                        # TODO: field_class_item for children has to be initialized differently depending
                        #   on whether the parent is a enum / struct / variant.
                        # This is a PoC for structs only right now.

                        # Recursively parse its members
                        handlers = []
                        for member in parent_field_class.values():
                            handlers.append(parse_field_class(member.name, member.field_class, field_class_item))

                        # Create a handler that calls its childrens handlers
                        def map_field_handler(payload):
                            for hp in zip(handlers, payload.values()):
                                hp[0](hp[1])
                            # Currently we don't use our item here - when we will have enums, etc, we will update
                            # the current state

                        # Return handler (closure)
                        return map_field_handler

                    # non-abc.Mapping type
                    else:
                        # Create node with update_model handler for non-mapping type
                        # TODO: We only handle scalars here, but there can be non-mapping container types (arrays)
                        def non_map_field_handler(payload): # To bi lahko z lambdami naredil
                            field_class_item.setState(payload)
                        return non_map_field_handler

                # Attach update handler from the child to parent, so that the parent can call it
                event_class_item.update.update = parse_field_class("payload", event_class.payload_field_class, event_class_item)
                # to lahko naredimo drugace, ker je lahko za podelementom, in ker itak delamo closure, damo to kot argument v funkcijo k vraca closure

                self._treeModel.event_class_item[event_class.id] = event_class_item # tehnicno bi lahko klicali handler direkt

        if type(msg) == bt2._EventMessageConst:
            # Save event to buffer
            self._tableModel.append((msg.default_clock_snapshot.value, msg.event.name, str(msg.event.payload_field)))
            self._treeModel.event_class_item[msg.event.id].update(msg.event)

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

        self._tableView.setEditTriggers(QTableWidget.NoEditTriggers)    # read-only
        self._tableView.verticalHeader().setDefaultSectionSize(10)      # row height
        self._tableView.horizontalHeader().setStretchLastSection(True)  # last column resizes to widget width

        # Tree view
        self._treeView = QTreeView()
        self._treeView.setModel(self._treeModel)
        self._treeView.loaded = False

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
        if not self._treeView.loaded and self._treeModel.rowCount(QModelIndex()):
            self._treeModel.modelReset.emit()
            self._treeView.resizeColumnToContents(0)
            self._treeView.loaded = True

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
