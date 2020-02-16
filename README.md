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
 * with the CAN source and a sink which forwards events to the PyQt5 GUI, with the graph running in
    * [the GUI event loop](/can/python/can_graph_gui_threaded_simple.py), which is fast and easy
   
   You can also run the graph in a separate thread, which is more complex and with little additional benefit.
   
   But, if you _really really_ want to, you can
    * [pass data via signals](/can/python/can_graph_gui_threaded_simple.py) and get into performance issues
    * [try to optimize the heck out of it](/can/python/can_graph_gui_threaded_responsive.py)
    and you get similar performance as the event loop example.