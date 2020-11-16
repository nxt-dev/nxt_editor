# Built-in
import argparse
import sys
import os
import logging
import time

# Internal
from session import Session

import legacy
import nxt_log

logger = logging.getLogger('nxt')


class InvalidChoice(Exception):
    pass


class UnrecognizedArg(Exception):
    pass


class CustomParser(argparse.ArgumentParser):
    def error(self, message):
        if "invalid choice" in message:
            # If message doesn't look like a file path, raise the error
            if '.nxt' not in message:
                super(CustomParser, self).error(message)
            raise InvalidChoice(message)
        elif 'unrecognized arguments' in message:
            possible_args = ['-gui']
            args = [a for a in possible_args if a in message]
            if args:
                raise UnrecognizedArg(message)

        super(CustomParser, self).error(message)


def count_down(t=3):
    while t != 0:
        sys.stdout.write('\r' + str(t))
        sys.stdout.flush()
        time.sleep(.8)
        t -= 1
    sys.stdout.write('\r ')
    sys.stdout.flush()


def editor(args):
    """Launches editor
    :param args: Namespace Object
    :return: None
    """
    try:
        from ui import resources
    except ImportError:
        import subprocess
        result_path = os.path.join(os.path.dirname(__file__), 'ui/resources.py')
        qrc_path = os.path.join(os.path.dirname(__file__),
                                'ui/resources/resources.qrc')
        logger.info('generating nxt resources '
                    'from {} to {}'.format(qrc_path, result_path))
        subprocess.call(['pyside2-rcc', qrc_path, '-o', result_path])
    from Qt import QtCore, QtWidgets, QtGui
    from ui.main_window import MainWindow
    app = QtWidgets.QApplication(sys.argv)
    app.setEffectEnabled(QtCore.Qt.UI_AnimateCombo, False)
    if isinstance(args.path, list):
        path = args.path[0]
    else:
        path = args.path
    instance = MainWindow(filepath=path)
    pixmap = QtGui.QPixmap(':icons/icons/nxt.svg')
    app.setWindowIcon(QtGui.QIcon(pixmap))
    app.setActiveWindow(instance)
    instance.show()
    sys.exit(app.exec_())


def execute(args):
    """Executes graph
    :param args: Namespace Object
    :return: None"""
    if not hasattr(args, 'parameters'):
        parameter_list = []  # Legacy does not support parameters
    else:
        parameter_list = args.parameters
    if not hasattr(args, 'start'):
        start = None # Legacy does not support start points
    else:
        start = args.start

    param_arg_count = len(parameter_list)
    if param_arg_count % 2 != 0:
        raise Exception('Invalid parameters supplied, must be in pattern '
                        '-/node.attr value')
    parameters = {}
    i = 0
    for _ in range(param_arg_count / 2):
        key = parameter_list[i]
        if not key.startswith('/'):
            raise Exception('Invalid attr path key {}, must be '
                            'formatted as /node.attr'.format(key))
        val = parameter_list[i + 1]
        parameters[key] = val
        i += 2
    Session().execute_graph(args.path[0], start, parameters)
    logger.execinfo('Execution finished!')


def convert(args):
    """Convert save file
    :param args: Namespace Object
    :return: None"""
    legacy.cli_file_convert(args.path[0], args.replace)
    sys.exit()


def main():
    desc = 'execute nxt file or open an nxt session'
    parser = CustomParser(description=desc, prog='nxt')
    subs = parser.add_subparsers()
    parser.add_argument('-v', '--verbose', help='verbose execution '
                                                '(-vv for debugging)',
                        action='count')
    # Legacy
    # TODO: Remove at 2.0
    leg_desc = ('Please convert your calls to the new system: '
                'edit, exec,or convert.')
    legacy_parser = subs.add_parser('legacy', help=leg_desc)
    legacy_parser.add_argument('-v', '--verbose', help='verbose execution',
                               action='store_true')

    gui_parser = subs.add_parser('ui', help='Launch visual editor.')
    gui_parser.set_defaults(which='ui')
    gui_parser.add_argument('path', type=str, nargs='?', help='file to open',
                            default='')

    exec_parser = subs.add_parser('exec', help='Execute graph. See: exec -h')
    exec_parser.set_defaults(which='exec')

    exec_parser.add_argument('path', type=str, nargs=1, help='file to execute')
    exec_parser.add_argument('-s', '--start', nargs='?', default=None,
                             help='start node path')

    convert_parser = subs.add_parser('convert', help='upgrades old save file to'
                                                     ' current version.'
                                                     'See: convert -h')
    convert_parser.set_defaults(which='convert')

    convert_parser.add_argument('path', type=str, nargs=1,
                                help='file/dir to convert')

    convert_parser.add_argument('-r', '--replace', help='replace file with '
                                                        'converted.')

    parameters_help = '''Incompatible with -gui! Graph parameters can be 
    overloaded before the graph starts running. To overload (set) a node's attr 
    value provide the full path to the attr and the value, separated by a space:
        /node.attr 5
    If your value must contain a space wrap it in double quotes (" not '').
    If your value must contain any number of double quote character (") you 
    must escape them:
        /node.attr "\"Hello World!\""
        /node.attr "\"\"\"Hello World!\"\"\""
        /node.attr \"Hello\"
    TLDR; Escape all your literal double quotes, try not to use them, if you 
    have to, use the Python API.
    '''
    exec_parser.add_argument('-p', '--parameters', nargs="*",
                             help=parameters_help, default=())

    legacy_parser.add_argument('-gui', '--gui',
                               help='launch visual editor session '
                                    '(will be depreciated at 2.0)',
                               action='store_true')
    legacy_parser.add_argument('path', type=str, nargs='?', help='file to open',
                               default='')
    legacy_parser.add_argument('-c', '--convert',
                               help='converts old save version to '
                                    'current (will be depreciated at 2.0)',
                               action='store_true')
    legacy_parser.add_argument('-r', '--replace',
                               help='when used with -c the file on disc is '
                                    'replaced (will be depreciated at 2.0)',
                               action='store_true')
    legacy_parser.add_argument('path', type=str, help='file to open',
                               default='')

    try:
        args = parser.parse_args()
    except (InvalidChoice, UnrecognizedArg):
        # Supports legacy
        logger.exception('Invalid choice, falling back to legacy.')
        try:
            sys.argv.remove('legacy')
        except ValueError:
            pass
        args = legacy_parser.parse_args()
        setattr(args, 'which', 'legacy')
        if getattr(args, 'path'):
            if not isinstance(args.path, list):
                args.path = [args.path]
    if args.verbose:
        if os.environ.get(nxt_log.VERBOSE_ENV_VAR) is None:
            os.environ[nxt_log.VERBOSE_ENV_VAR] = str(args.verbose)
        nxt_log.set_verbosity(args.verbose)
    if args.which == 'legacy':
        if args.gui:
            logger.warning('The flag -gui will be depreciated at 2.0, please '
                           'see: ui -h')
            count_down()
            editor(args)
        if args.convert:
            logger.warning('The flag -c will be depreciated at 2.0, please '
                           'see: convert -h')
            count_down()
            convert(args)
        else:
            logger.warning('Executing without the "exec" keyword will be '
                           'depreciated at 2.0, please '
                           'see: exec -h')
            count_down()
            execute(args)

    elif args.which == 'convert':
        if not args.path:
            raise IOError('No file path to convert provided!')
        convert(args)
    elif args.which == 'ui':
        editor(args)
    elif args.path and args.which == 'exec':
        execute(args)
    else:
        logger.error('No file path provided!')


if __name__ == '__main__':
    main()
