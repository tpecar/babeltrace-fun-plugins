"""
Common functionality shared between can_graph examples.
"""

import bt2
import argparse


def load_plugins(system_plugin_path, plugin_path):
    """
    Loads system & user plugins and returns them as an unified dict

    :param system_plugin_path: path to system plugins (searched recursively) - if None, uses default system paths and BABELTRACE_PLUGIN_PATH (non-recursively)
    :param plugin_path: path to user plugins
    :return: dict with all found plugins
    """

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

    return plugins


"""
Argument parser used by all can_graph examples.
The examples might additionally extend the parser.
"""
cmd_parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
cmd_parser.add_argument(
    "--system-plugin-path", type=str, default=None,
    help="Specify folder for system plugins (recursive!). "
         "Alternatively, set BABELTRACE_PLUGIN_PATH (non-recursive!)"
)
cmd_parser.add_argument(
    "--plugin-path", type=str, default="./",
    help="Path to 'bt_user_can.(so|py)' plugin"
)
cmd_parser.add_argument(
    "--CANSource-data-path", type=str, default="../test.data",
    help="Path to test data required by bt_user_can"
)
cmd_parser.add_argument(
    "--CANSource-dbc-path", type=str, default="../database.dbc",
    help="Path to DBC (CAN Database) required by bt_user_can"
)
