"""Run an nxt graph in Unreal without its UI.

Unreal's command line editor runs it as a Python commandlet, in a project
that has the nxt plugin and the Python Editor Script Plugin enabled. The
script and its arguments go in one quoted ``-script``::

    UnrealEditor-Cmd.exe MyProject.uproject -run=pythonscript
        -script="run_unreal_graph.py -g C:/graphs/build.nxt"
        -unattended -nosplash -nullrhi

Unreal finds this file by name in the plugin's Content/Python folder. ``-s``
and ``-p`` work as in the Maya and Blender runners, see
``integration/run_graph.py``. Unreal splits ``-script`` at every space and
keeps any quotes, so a path with a space in it cannot go there. Leave the
arguments out of ``-script`` and set ``NXT_RUN_GRAPH_ARGS`` to them as a
JSON list instead, which is what the ``/_unreal_headless_graph`` node does::

    NXT_RUN_GRAPH_ARGS=["-g", "C:/my graphs/build.nxt"]

Unreal exits with an error code when the graph fails and 0 when it ran. No
Qt is needed.
"""
import importlib.util
import os
import sys

ARGS_ENV = 'NXT_RUN_GRAPH_ARGS'

HERE = os.path.dirname(os.path.abspath(__file__))


def _run_graph_path():
    """integration/run_graph.py: beside this file in a released plugin,
    which carries nxt_editor in Content/Python, or up the tree in a
    checkout of nxt_editor."""
    for path in (os.path.join(HERE, 'nxt_editor', 'integration',
                              'run_graph.py'),
                 os.path.join(HERE, os.pardir, os.pardir, os.pardir,
                              'run_graph.py')):
        if os.path.isfile(path):
            return os.path.abspath(path)
    raise ImportError('nxt_editor/integration/run_graph.py was not found '
                      'from {}'.format(HERE))


def _put_nxt_on_path():
    """Make nxt importable. A released plugin carries it in Content/Python,
    which Unreal puts on sys.path; a checkout has it beside nxt_editor."""
    try:
        import nxt  # noqa: F401
        return
    except ImportError:
        pass
    editor_repo = os.path.abspath(os.path.join(HERE, *[os.pardir] * 5))
    root = os.path.join(os.path.dirname(editor_repo), 'nxt')
    if os.path.isdir(os.path.join(root, 'nxt')) and root not in sys.path:
        sys.path.insert(0, root)


def _run_graph():
    """integration/run_graph.py, loaded by path: importing nxt_editor would
    import Qt, which a headless run does not need."""
    spec = importlib.util.spec_from_file_location('nxt_run_graph',
                                                  _run_graph_path())
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    run_graph = _run_graph()
    parser = run_graph.make_parser('Unreal', os.path.basename(__file__))
    args = parser.parse_args(run_graph.runner_argv(argv))
    _put_nxt_on_path()
    return run_graph.run(args)


if __name__ == '__main__':
    code = main()
    # A raised error is what fails the commandlet, so its exit code is not
    # 0; a plain exit code is not passed on by Unreal.
    if code:
        raise RuntimeError('nxt: the graph failed, see the log above.')
