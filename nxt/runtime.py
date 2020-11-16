# Built-in
import code
import sys
import traceback
import logging

# Internal
from . import IGNORE

logger = logging.getLogger(__name__)


class Console(code.InteractiveConsole):
    def __init__(self, _globals=None, _locals=None, filename=IGNORE,
                 node_path=None, layer_path=None):
        if locals is None:
            _locals = {}
        if globals is None:
            _globals = {}
        self.node_path = node_path
        self.running_lines = []
        self.layer_path = layer_path
        self.locals = _locals
        self.globals = _globals
        self.run_as_global = False
        self.lineno_offset = -1
        code.InteractiveConsole.__init__(self, self.locals, filename)

    def runcode(self, c):
        try:  # Convert to tuple for python3
            exec c in self.globals
        except KeyboardInterrupt:
            raise
        except SystemExit:
            logger.warning("System Exit raised in {}, "
                           "halting execution.".format(self.node_path),
                           links=[self.node_path])
        except Exception as err:
            lineno = get_traceback_lineno(err_depth=1)
            lineno -= 1
            bad_line = self.running_lines[lineno-1]
            _, _, tb = sys.exc_info()
            raise GraphError(err, tb, self.layer_path, self.node_path, lineno,
                             bad_line, err_depth=1)


def get_traceback_lineno(err_depth=0):
    """Get the line number of one of the errors in the current traceback.

    :param err_depth: index of the error to get line number of. 0 is most
    recent, higher values are deeper errors. Defaults to 0
    :type err_depth: int, optional
    :return: line number of requested error
    :rtype: int
    """
    _, _, tb = sys.exc_info()
    _tblist = traceback.extract_tb(tb)
    return _tblist[err_depth][1]


class GraphError(Exception):
    def __init__(self, err, tb, layer_path, err_path, lineno, bad_line,
                 err_depth=0):
        tb_lines = traceback.extract_tb(tb)
        tb_lines = tb_lines[err_depth:]
        # Insert our custom graph traceback
        tb_lines[0] = (layer_path, lineno, err_path, bad_line)
        print_lines = traceback.format_list(tb_lines)
        print_lines[0] = print_lines[0].lstrip()
        print_lines += traceback.format_exception_only(type(err), err)
        print_tb = ''.join(print_lines)
        print_tb = print_tb.rstrip('\n')
        super(Exception, self).__init__(print_tb)


class GraphSyntaxError(GraphError):
    def __init__(self, error, layer_path, error_path, lineno):
        print_lines = traceback.format_exception_only(type(error), error)
        top_line_fmt = 'File "{}", line {}, in {}\n'
        print_lines[0] = top_line_fmt.format(layer_path, lineno, error_path)
        syntax_err_msg = ''.join(print_lines)
        syntax_err_msg = syntax_err_msg.rstrip('\n')
        super(Exception, self).__init__(syntax_err_msg)
