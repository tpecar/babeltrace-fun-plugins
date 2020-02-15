This repository contains a few silly or less silly Babetrace 2 plugins.

 * Very simple
   [source and sink components](/my-first-components),
   to help you get started.
 * A source to read CAN bus traces, implemented in both
   [Python](/can/python/bt_plugin_can.py)
   and
   [C(++)](/can/c/).
 * A source to read
   [gpx](/gpx/)
   files as traces.
 * A sink to generate
   [plots](/plot/)
   from event data.

There are also silly examples of constructing Babeltrace2 graphs
 * with the [CAN source and different components](/can/python/can_graph.py)
 * with the CAN source and a sink which forwards events to the PyQt5 GUI
    * [the easy way](/can/python/can_graph_gui_simple.py)
    * [in a more complicated, but more performant way](/can/python/can_graph_gui_responsive.py)