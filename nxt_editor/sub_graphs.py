"""Sub-graph nodes: nodes that run another graph.

A sub-graph node instances `/_sub_graph`, from the builtin sub_graphs
graph, and names the graph it runs in `_graph_path`. Its own attrs are
given to that graph as its world node's attrs, so the world node's attrs
are the sub-graph's parameters. The editor opens the graph a node runs
(see `graph_path`) and shows its parameters (see `world_attrs`).
"""
# Builtin
import logging
import os

# Internal
from nxt import nxt_path
from nxt.nxt_node import META_ATTRS

logger = logging.getLogger('nxt')

GRAPH_PATH_ATTR = '_graph_path'
# The sub-graph node's own settings, never given to the graph.
OWN_ATTRS = (GRAPH_PATH_ATTR, '_start', '_parameters', '_cache_file')

# {graph path: (modified time, world attrs)}
_world_attrs = {}


def graph_path(model, node_path):
    """The graph file the node at node_path runs, when it names one that
    is there. Relative to the top layer's folder if it is not absolute.

    :param model: StageModel
    :param node_path: path of the node
    :return: the file's path, or None
    """
    comp = model.comp_layer
    if not model.node_exists(node_path, comp):
        return None
    if GRAPH_PATH_ATTR not in model.get_node_attr_names(node_path, comp):
        return None
    value = model.get_node_attr_value(node_path, GRAPH_PATH_ATTR, comp)
    if not isinstance(value, str):
        return None
    # A str attr's value is written as Python, quotes and all.
    value = value.strip().strip('\'"').strip()
    if not value or value == 'None':
        return None
    path = os.path.expandvars(os.path.expanduser(value))
    if not os.path.isabs(path):
        top = model.top_layer.real_path
        if top:
            path = os.path.join(os.path.dirname(top), path)
    path = os.path.normpath(path)
    return path if os.path.isfile(path) else None


def world_attrs(path):
    """The attrs the world node of the graph at path has, its sub-graph
    parameters. Read again once the file changes.

    :param path: graph file path
    :return: {name: (value, comment)}, empty if it cannot be read
    """
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return {}
    known = _world_attrs.get(path)
    if known and known[0] == stamp:
        return known[1]
    from nxt.stage import Stage
    try:
        stage = Stage.load_from_filepath(path)
        world = stage.build_stage().lookup(nxt_path.WORLD)
    except Exception:
        logger.exception('Could not read the sub-graph %s', path)
        return {}
    attrs = {}
    if world is not None:
        for name in stage.get_node_attr_names(world):
            if name in OWN_ATTRS:
                continue
            attrs[name] = (getattr(world, name, None),
                           getattr(world, name + META_ATTRS.COMMENT, None))
    _world_attrs[path] = (stamp, attrs)
    return attrs
