#!/usr/bin/python
"""Run an nxt graph in Maya without its UI (maya.standalone).

Run it with Maya's own python, from Maya's bin folder::

    mayapy run_maya_graph.py -g path/to/graph.nxt
    mayapy run_maya_graph.py -g path/to/graph.nxt -s /start_node
    mayapy run_maya_graph.py -g path/to/graph.nxt -p "{\"/.name\": \"test\"}"

The exit code is 0 when the graph ran and 1 when it failed. To launch it
from inside another graph, instance ``/_maya_standalone_graph`` from the
builtin ``sub_graphs.nxt``. The arguments are shared with the Blender and
Unreal runners, see ``integration/run_graph.py``.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _run_graph():
    """integration/run_graph.py, loaded by path: importing nxt_editor would
    import Qt, which mayapy may not need for a headless run."""
    path = os.path.join(os.path.dirname(HERE), 'run_graph.py')
    spec = importlib.util.spec_from_file_location('nxt_run_graph', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    run_graph = _run_graph()
    # Parse first, so -h and bad arguments answer without starting Maya.
    parser = run_graph.make_parser('Maya', os.path.basename(__file__))
    argv = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(run_graph.runner_argv(argv))
    from maya import standalone
    standalone.initialize()
    try:
        return run_graph.run(args)
    finally:
        standalone.uninitialize()


if __name__ == '__main__':
    sys.exit(main())
