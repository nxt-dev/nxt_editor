# Builtin
import json
import os

# Internal
import nxt_log
nxt_log.initial_setup()

import plugin_loader
from constants import (DATA_STATE, NODE_ERRORS, UNTITLED,
                       IGNORE, GRID_SIZE)
from session import Session

plugin_loader.load_plugins()


def execute_graph(filepath, start=None, parameters=None):
    """Shortest code path to exeucting a graph from the nxt package.
    Creates a 1 off session and executes the graph within that session.
    Arguments are a direct copy of Session.execute_graph, see there for full
    details.

    :param filepath: Path to the graph file.
    :type filepath: str
    :param start: Path to the node to begin execution from.
    :type start: str
    :param parameters: Dict where key is attr path and value is new attr
    value.
    :type parameters: dict
    """
    one_shot_session = Session()
    one_shot_session.execute_graph(filepath,
                                   start=start, parameters=parameters)
