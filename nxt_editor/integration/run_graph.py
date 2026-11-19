"""Run a graph headless: the arguments and the run that every host's runner
shares.

Each host has a small runner that starts the host without a UI, puts nxt on
``sys.path`` and then hands its command line to :func:`main`:

- Maya: ``integration/maya/run_maya_graph.py``, run with ``mayapy``.
- Blender: ``integration/blender/run_blender_graph.py``, run with
  ``blender --background --python``.
- Unreal: ``integration/unreal/Content/Python/run_unreal_graph.py``, run with
  ``UnrealEditor-Cmd -run=pythonscript``.

Nothing here imports Qt or the rest of nxt_editor, which a headless host may
not have, so a runner loads this file by its path rather than importing it.
"""
import argparse
import json
import os
import sys
import traceback

#: Where a runner also takes its arguments, as a JSON list, when its command
#: line has none. A host's command line can lose them: Unreal splits
#: ``-script`` at every space, and mayapy turns any character the system's
#: code page lacks, Chinese or Cyrillic on a Western Windows, into ``?``.
#: The environment keeps them whole.
ARGS_ENV = 'NXT_RUN_GRAPH_ARGS'


def dict_or_string(value):
    """The parameters as a dictionary, from a JSON string or a JSON file.

    :param value: a dictionary, a JSON dictionary or the path to a JSON file.
    :type value: dict | str
    :raises argparse.ArgumentTypeError: when it is none of those.
    :return: the parameters.
    :rtype: dict
    """
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    if os.path.isfile(value):
        try:
            # A byte order mark is fine, as Windows tools often write one.
            with open(value, 'r', encoding='utf-8-sig') as fp:
                parsed = json.load(fp)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    raise argparse.ArgumentTypeError(
        'Parameters must be a JSON dictionary, or the path to a JSON file '
        'holding one: {}'.format(value))


def runner_argv(argv):
    """The arguments to parse: the command line's, or when it has none,
    the ones in :data:`ARGS_ENV`.

    :param argv: the arguments from the command line.
    :type argv: list[str]
    :rtype: list[str]
    """
    if not argv and os.environ.get(ARGS_ENV):
        return json.loads(os.environ[ARGS_ENV])
    return argv


def make_parser(host, prog=None):
    """The command line every runner takes.

    :param host: the host's name, for the help text.
    :type host: str
    :param prog: the runner's file name, for the help text. A host's own
        program name would be wrong there, as it is not what takes these.
    :type prog: str | None
    :rtype: argparse.ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog=prog,
        description='Run an nxt graph in {} without its UI.'.format(host))
    parser.add_argument('-g', '--graph_path', required=True,
                        help='The graph to run.')
    parser.add_argument('-s', '--start_node', default=None,
                        help="The node to start from. Without it the graph's "
                             "start point is used.")
    parser.add_argument('-p', '--parameters', type=dict_or_string,
                        default=None,
                        help='Values to set before the graph runs, as a JSON '
                             'dictionary or the path to a JSON file. Keys are '
                             'attribute paths, such as /node.attr.')
    return parser


def run(args):
    """Run the graph the arguments name.

    :param args: parsed arguments from :func:`make_parser`.
    :return: the process exit code, 0 when the graph ran and 1 when it failed.
    :rtype: int
    """
    from nxt import execute_graph
    graph = os.path.abspath(os.path.expanduser(args.graph_path))
    if not os.path.isfile(graph):
        print('nxt: no graph at {}'.format(graph), file=sys.stderr)
        return 1
    print('nxt: running {}'.format(graph))
    try:
        execute_graph(graph, start=args.start_node or None,
                      parameters=args.parameters or None)
    except Exception:
        traceback.print_exc()
        print('nxt: {} failed'.format(graph), file=sys.stderr)
        return 1
    print('nxt: finished {}'.format(graph))
    return 0


def main(host, argv=None, prog=None):
    """Parse a runner's command line and run its graph.

    :param host: the host's name, for the help text.
    :type host: str
    :param argv: the arguments, without the program name. Defaults to
        ``sys.argv[1:]``.
    :type argv: list[str] | None
    :param prog: the runner's file name, for the help text.
    :type prog: str | None
    :return: the process exit code.
    :rtype: int
    """
    argv = sys.argv[1:] if argv is None else argv
    args = make_parser(host, prog).parse_args(runner_argv(argv))
    return run(args)

