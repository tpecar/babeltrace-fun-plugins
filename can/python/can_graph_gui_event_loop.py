#!/usr/bin/env python3
# *_* coding: utf-8 *_*

"""
Creates and runs a graph with a can.CANSource source and in-app sink, which delegates stream info to the GUI.
A more complex example which allows for faster graph execution, while allowing for a decently responsive ui.

Event-loop implementation. Fast and simple.
---
Please note: libbabeltrace2 python library (bt2) depends on its core C library.
---
LD_LIBRARY_PATH=[babeltrace2 build folder]/src/lib/.libs/
BABELTRACE_PLUGIN_PATH = [babeltrace2 build folder]/src/plugins/[plugin name]
LIBBABELTRACE2_PLUGIN_PROVIDER_DIR = [babeltrace2 build folder]/src/python-plugin-provider/.libs/
"""

import bt2
import time
import numpy as np

from PyQt5.Qt import *
from PyQt5.QtWidgets import *

# import local modules
from graph.event_buffer import EventBuffer, EventBufferSink, EventBufferTableModel
from graph.utils import load_plugins, cmd_parser


# MainWindow
#
class MainWindow(QMainWindow):

    def __init__(self, buffer, model):
        super().__init__()
        self._buffer = buffer
        self._model = model

        self.setWindowTitle("Responsive Babeltrace2 GUI demo")

        # Table view
        self._tableView = QTableView()
        self._tableView.setWindowTitle("Sink data")
        self._tableView.setModel(model)

        self._tableView.setEditTriggers(QTableWidget.NoEditTriggers)    # read-only
        self._tableView.verticalHeader().setDefaultSectionSize(10)      # row height
        self._tableView.horizontalHeader().setStretchLastSection(True)  # last column resizes to widget width

        # Statistics label
        self._statLabel = QLabel("Events (processed/loaded): - / -")

        # Refresh checkbox
        self._followCheckbox = QCheckBox("Follow events")
        self._followCheckbox.setChecked(True)

        # Layout
        self._layout = QGridLayout()
        self._layout.addWidget(self._tableView, 0, 0, 1, 2) # See https://doc.qt.io/qt-5/qgridlayout.html#addWidget-2
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
        self._statLabel.setText(f"Events (processed/loaded): {len(self._buffer)} / {self._model.rowCount()}")

        # Force the view to call canFetchMore / fetchMore initially
        if not self._model.rowCount():
            self._model.modelReset.emit()

        # Follow events
        if self._followCheckbox.isChecked():
            # The following could be achieved similarly with self._tableView.scrollToBottom(), but that method has
            # issues with panning - rows appear to "bounce" and it's hard to look at the output
            #
            self._tableView.scrollTo(self._model.index(self._model.rowCount()-1, 0), QAbstractItemView.PositionAtBottom)


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
    graph_timer.timeout.connect(lambda: graph.run_once())
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
