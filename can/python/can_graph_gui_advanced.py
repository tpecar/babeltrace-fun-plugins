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
from bt2 import field_class

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

        def getCount(self):
            return self.itemData[2]

        def setCount(self, state):
            self.itemData[2] = state

            # Notify view
            if self.indexReady():
                itemIdx = self.index[2]
                self.model.dataChanged.emit(itemIdx, itemIdx)

        def getValue(self):
            return self.itemData[3]

        def setValue(self, state):
            self.itemData[3] = state

            # Notify view
            if self.indexReady():
                itemIdx = self.index[3]
                self.model.dataChanged.emit(itemIdx, itemIdx)

        def appendItem(self, item_data):
            item = type(self)(item_data, self, self.model)
            self.childItems.append(item)
            return item

    def __init__(self, rootItem_data, parent=None):
        super().__init__(rootItem_data, parent)
        self.rootItem.model = self

        # event id -> model update handler
        self.update = {}

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
        #   event_class ( _EventClassConst )
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

                # Parse field classes + attach update handlers recursively
                def parse_field_class(parent_item, child_class, child_columns): # add wrapper_handler - do that the parent can affect the childs handler - it gets the childs handler as an argument

                    class_item = parent_item.appendItem(child_columns)

                    if any([issubclass(type(child_class), c) for c in (
                        field_class._BoolFieldClassConst,
                        field_class._BitArrayFieldClassConst,
                        field_class._IntegerFieldClassConst,
                        field_class._RealFieldClassConst,
                        field_class._StringFieldClassConst
                    )]):
                        def update_scalar(payload):
                            class_item.setValue(payload)
                            return None  # No subelements, so no update view handler
                        return (class_item, update_scalar)

                    elif type(child_class) == field_class._EnumerationFieldClassConst:
                        # item     -> enum current state
                        # children -> fixed value, possible enum states
                        for member in child_class.values():
                            parse_field_class(
                                class_item, member.field_class,
                                # "Name",     "Type",                         "Count", "Last Value"
                                [member.name, type(member.field_class)._NAME, None,     None]
                            )

                        def update_enum(payload):
                            class_item.setValue(payload) # TODO
                        return (class_item, update_enum)

                    elif type(child_class) == field_class._ArrayFieldClass:
                        # item     -> length, (checksum ?)
                        # children -> array elements
                        # In case of dynamic arrays, the number of children can change! (Tree is modified!)
                        def update_array(payload):
                            class_item.setValue(payload) # TODO
                        return (class_item, update_array)

                    elif type(child_class) == field_class._StructureFieldClassConst:
                        # item      -> (checksum ?)
                        # children  -> structure elements

                        sub_handler = []

                        for member in child_class.values():
                            sub_handler.append(
                                parse_field_class(
                                    class_item, member.field_class,
                                    # "Name",     "Type",                         "Count", "Last Value"
                                    [member.name, type(member.field_class)._NAME, None,     '-']
                                )[1] # handler only
                            )

                        def update_struct(payload):
                            # Update members
                            for shp in zip(sub_handler, payload.values()):
                                shp[0](shp[1]) # sub handler for payload member ( payload member instance )
                        return (class_item, update_struct)

                    elif type(child_class) == field_class._OptionFieldClassConst:
                        # item   -> option enabled
                        # child  -> option data struct, with values displayed if enabled
                        def update_option(payload):
                            class_item.setValue(payload) # TODO
                        return (class_item, update_option)

                    elif type(child_class) == field_class._VariantFieldClassConst:
                        # item      -> data struct selection
                        # children  -> all variant data structs, selected one has values displayed
                        def update_variant(payload):
                            class_item.setValue(payload) # TODO
                        return (class_item, update_variant)

                    else:
                        print(f"{type(child_class)} not handled!")

                # Attach update handler from the child to parent, so that the parent can call it
                (item, update_handler) = parse_field_class(
                    self._treeModel.rootItem, event_class.payload_field_class,
                    # "Name",          "Type",                                      "Count", "Last Value"
                    [event_class.name, type(event_class.payload_field_class)._NAME, 0,        '']
                )

                # Augment the payload handler with counting functionality
                # Toplevel field class (event_class.payload_field_class) is in the same row as event class
                def update_event_class(payload):

                    # Since people usually stop at "closures in python are late binding", with no explanation why,
                    # I want to elaborate on this:
                    #
                    #   When you define a function / lambda that uses a variable from an outside scope,
                    #   the variable from outside scope is a 'lexically bound free variable'
                    #   - it references (not copies!) the variable (not the object!) in the outer scope.
                    #
                    #   A function
                    #       1. can outlive the scope of its free variables,
                    #       2. has to reference the variable of the outer scope, possibly even modify it
                    #          (that is, change the object the variable points to) with the modified variable
                    #          (new object) available in the outer scope itself,
                    #   Python supports both by storing the variable-to-object mapping (cell object) of the variable
                    #   in the __closure__ attribute of the defined function.
                    #
                    #   Consequentially, all functions that use the same out-of-scope variable will have the same
                    #   variable-to-object mapping, which means that
                    #       - the variable will reference the same object in all functions
                    #       - the assignment to the variable, be it in the function or
                    #         through an assignment in the original scope, or sub-scopes, will be seen in all functions
                    #
                    # More info:
                    #   https://stackoverflow.com/questions/12919278/how-to-define-free-variable-in-python
                    #   https://www.python.org/dev/peps/pep-0227/
                    #

                    item.setCount(item.getCount()+1)
                    update_handler(payload)

                # Add update handler for event class as closure
                self._treeModel.update[event_class.id] = update_event_class

        if type(msg) == bt2._EventMessageConst:
            # Save event to buffer
            self._tableModel.append((msg.default_clock_snapshot.value, msg.event.name, str(msg.event.payload_field)))
            self._treeModel.update[msg.event.id](msg.event.payload_field)

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
    treeModel = EventClassTreeModel(("Name", "Type", "Count", "Last Value"))

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
