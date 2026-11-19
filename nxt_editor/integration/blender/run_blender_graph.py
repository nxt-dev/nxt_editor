"""Run an nxt graph in Blender without its UI.

Blender runs it in the background. Its own arguments come first, then the
runner's after ``--``::

    blender --background --python run_blender_graph.py -- -g path/to/graph.nxt
    blender --background scene.blend --python run_blender_graph.py -- -g graph.nxt -s /start_node
    blender --background --python run_blender_graph.py -- -g graph.nxt -p params.json

Give a .blend file before ``--python`` to run the graph with it open. The
graph saves whatever it needs to; nothing is saved for it. The exit code is
0 when the graph ran and 1 when it failed.

The add-on carries this file under ``lib/nxt_editor/integration/blender``,
with nxt beside it, and it finds nxt from there. Blender's background mode
needs no Qt, and the add-on does not have to be enabled. The arguments are
shared with the Maya and Unreal runners, see ``integration/run_graph.py``.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
INTEGRATION = os.path.dirname(HERE)
# The folder nxt_editor is in: the add-on's lib folder, a site-packages, or
# a checkout of the nxt_editor repository.
EDITOR_PARENT = os.path.dirname(os.path.dirname(INTEGRATION))


def _put_nxt_on_path():
    """Make nxt importable: from the add-on's lib folder, where it sits
    beside nxt_editor, or from an nxt checkout beside an nxt_editor one."""
    try:
        import nxt  # noqa: F401
        return
    except ImportError:
        pass
    for root in (EDITOR_PARENT,
                 os.path.join(os.path.dirname(EDITOR_PARENT), 'nxt')):
        if os.path.isdir(os.path.join(root, 'nxt')) and root not in sys.path:
            sys.path.insert(0, root)
            return


def _run_graph():
    """integration/run_graph.py, loaded by path: importing nxt_editor would
    import Qt, which a background Blender does not have."""
    path = os.path.join(INTEGRATION, 'run_graph.py')
    spec = importlib.util.spec_from_file_location('nxt_run_graph', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def runner_args(argv=None):
    """The arguments after ``--``, which Blender leaves to the script."""
    argv = sys.argv if argv is None else argv
    if '--' in argv:
        return argv[argv.index('--') + 1:]
    return []


def main(argv=None):
    run_graph = _run_graph()
    parser = run_graph.make_parser('Blender', os.path.basename(__file__))
    args = parser.parse_args(run_graph.runner_argv(runner_args(argv)))
    _put_nxt_on_path()
    return run_graph.run(args)


if __name__ == '__main__':
    # Leaves Blender with this exit code, which --background passes on.
    sys.exit(main())
