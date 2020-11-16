# Built-in
import pickle
import logging
import logging.handlers
import SocketServer
import struct
import threading
import os
import sys
import tempfile
import errno
import time

# Internal
from constants import USER_DIR

VERBOSE_ENV_VAR = 'NXT_VERBOSE'

"""Logging levels are as follows, with custom levels marked with *
CRITICAL    - 50
ERROR       - 40
*GRAPHERROR - 39
WARNING     - 30
INFO        - 20
*NODEOUT    - 19
*EXECINFO   - 18
*COMPINFO   - 17
*SOCKET     - 16
DEBUG       - 10
NOTSET      - 0
"""
SOCKET = 16
GRAPHERROR = 39
NODEOUT = 19
EXECINFO = 18
COMPINFO = 17

COLORS = {
    SOCKET: 'pink',
    GRAPHERROR: 'red',
    NODEOUT: 'light gray',
    EXECINFO: '#039be5',  # Pale blue
    COMPINFO: 'light blue',
    logging.DEBUG: 'white',
    logging.INFO: 'green',
    logging.WARNING: 'orange',
    logging.ERROR: 'red',
    logging.CRITICAL: 'purple',
}


# logging setup
# NOTE probably neeed to be custom logger objects rather than our custom levels
class NXTLogger(logging.getLoggerClass()):
    """Implements custom logging levels for nxt.
    """
    def __init__(self, name):
        super(NXTLogger, self).__init__(name)
        logging.addLevelName(SOCKET, "SOCKET")
        logging.addLevelName(EXECINFO, "EXECUTE")
        logging.addLevelName(GRAPHERROR, "GRAPH ERROR")
        logging.addLevelName(COMPINFO, "COMPOSITE")
        logging.addLevelName(NODEOUT, "NODEOUT")

    def socket(self, message, *args, **kwargs):
        if self.isEnabledFor(SOCKET):
            self._log(SOCKET, message, args, **kwargs)

    def execinfo(self, message, *args, **kwargs):
        if self.isEnabledFor(EXECINFO):
            self._log(EXECINFO, message, args, **kwargs)

    def grapherror(self, message, *args, **kwargs):
        if self.isEnabledFor(GRAPHERROR):
            self._log(GRAPHERROR, message, args, **kwargs)

    def compinfo(self, message, *args, **kwargs):
        if self.isEnabledFor(COMPINFO):
            self._log(COMPINFO, message, args, **kwargs)

    def nodeout(self, message, *args, **kwargs):
        if self.isEnabledFor(NODEOUT):
            self._log(NODEOUT, message, args, **kwargs)

    def _log(self, level, message, args, **kwargs):
        if 'links' in kwargs.keys():
            link_paths = kwargs.pop('links')
            kwargs['extra'] = {'links': link_paths}
        super(NXTLogger, self)._log(level, message, args, **kwargs)


nxt_formatter = logging.Formatter("%(levelname)s: %(message)s")


def track_log_file(path):
    """
    Track given log at `path`, via meta log.
    Clean up old log files tracked by meta log.
    """
    logger = logging.getLogger(__name__)
    meta_log_location = os.path.join(USER_DIR, '.nxt_meta_log')
    remove_age = 60*60*48  # in seconds (currently 48 hours)

    existing_logs = []
    try:
        with open(meta_log_location, 'r') as meta_log_file:
            # stripping of trailing newlines
            existing_logs = [line.rstrip() for line in meta_log_file.readlines()]
    except IOError:
        logger.exception('Error tracking log file!')
        pass
    # Remove old logs
    for log_path in existing_logs[:]:
        is_file = os.path.isfile(log_path)
        age = 0.0
        try:
            mod_time = os.path.getmtime(log_path)
            age = time.time() - mod_time
        except Exception as err:
            try:
                if err.errno is errno.ENOENT:
                    # This is expected behavior. Because files log to tempdir,
                    # they can be removed at any time by the OS or user.
                    age = float("inf")
            except AttributeError:
                pass
        if is_file and age > remove_age:
            try:
                os.remove(log_path)
            except Exception as err:
                logger.exception(err)

        elif not is_file or age > remove_age:
            existing_logs.remove(log_path)
            logger.info('Removing stale log "{}"'.format(log_path))
    # add given log and write meta log
    existing_logs.append(path)
    try:
        with open(meta_log_location, 'w') as meta_log_file:
            # add trailing newlines to make meta log human readable.
            meta_log_file.writelines([line + '\n' for line in existing_logs])
    except IOError:
        logger.exception('Failed to track "{}" log in meta_log'.format(path))


def initial_setup():
    """
    module-wide logging boilerplate.
    Sets logging level.
    Builds and sets up default handlers.
    """
    if logging.getLoggerClass() is NXTLogger:
        logging.info('nxt logger already setup!')
        return
    logging.setLoggerClass(NXTLogger)
    root_logger = logging.getLogger('nxt')
    root_logger.setLevel(logging.DEBUG)
    root_logger.propagate = False
    null_handler = logging.NullHandler()
    root_logger.addHandler(null_handler)

    env_verbosity = os.environ.get(VERBOSE_ENV_VAR)
    global verbose_handler
    verbose_handler = None
    if env_verbosity is None:
        return
    verbose_handler = set_verbosity(env_verbosity)


def set_verbosity(level):
    """Set the verbosity of nxt logging. Controls what to output to stderr.
    3 legal levels specified by integer. NOTE node prints are not affected.
    0 - Nothing
    1 - EXECINFO and higher
    2 - Everything

    TODO when the swap to dedicated loggers is made. Level 1 should install
    a stderr handler only to the node execution logger.

    :param level: level to set stderr verbosity to: 0, 1, or 2
    :type level: int
    :return: stderr handler, if there is one
    :rtype: logging.StreamHandler or None
    """
    root_logger = logging.getLogger('nxt')
    global verbose_handler
    if level == 'socket':
        _log_port = logging.handlers.DEFAULT_TCP_LOGGING_PORT
        socket_handler = logging.handlers.SocketHandler('localhost', _log_port)
        # Add socket handler
        root_logger.addHandler(socket_handler)
        return
    level = int(level)
    if level == 0:
        if not verbose_handler:
            return
        root_logger.removeHandler(verbose_handler)
        return
    if level > 0:
        if verbose_handler:
            stderr_handler = verbose_handler
        else:
            stderr_handler = logging.StreamHandler(sys.stderr)
            stderr_handler.setFormatter(nxt_formatter)
            root_logger.addHandler(stderr_handler)
        if level == 1:
            stderr_handler.setLevel(EXECINFO)
        return stderr_handler


# Dictionary mapping filenames to filehandlers, allows them to be removed.
SESSION_LOG_HANDLERS = {}


def make_session_log(filename=None):
    """Begin saving log at `filename` if given, otherwise
    track to a generated file inside default temporary directory.

    :param filename: file to log to, defaults to None
    :type filename: str, optional
    :return: file being logged to, `filename` if given.
    :rtype: str
    """
    logger = logging.getLogger(__name__)
    if not filename:
        filename = get_new_session_log_filename()
    file_handler = logging.FileHandler(filename)
    file_handler.setFormatter(nxt_formatter)
    root_logger = logging.getLogger('nxt')
    root_logger.addHandler(file_handler)
    SESSION_LOG_HANDLERS[filename] = file_handler
    logger.info("logging to {}".format(filename))
    os.chmod(filename, 0o777)
    track_log_file(filename)
    return filename


def get_new_session_log_filename():
    """Get a new log filename for an nxt session inside the default logs directory.
    Attempts to create logs directory.

    :return: filename to use for session log.
    :rtype: str
    """
    logger = logging.getLogger(__name__)
    log_dir = os.path.join(tempfile.gettempdir(), 'nxt_logs')
    try:
        os.makedirs(log_dir)
        os.chmod(log_dir, 0o777)
    except OSError as err:
        if err.errno is errno.EEXIST:
            logger.debug("Not creating logs directory because it exists.")
        else:
            raise
    log_filename_template = "nxt_session_{time}.log"
    log_filename = log_filename_template.format(time=str(int(time.time())))
    return os.path.join(log_dir, log_filename)


def stop_session_log(filename):
    """Stops outputting log to given filename.

    :param filename: filename to stop outputting to.
    :type filename: str, required
    """
    handler = SESSION_LOG_HANDLERS.get(filename)
    if not handler:
        return
    root_logger = logging.getLogger('nxt')
    root_logger.removeHandler(handler)


def make_link(value):
    """Wrap given `value` in html href syntax.

    :param value: value to wrap
    :type value: str
    """
    # TODO: Maybe someone smarter can find the answer but this thread says
    #  you can not set link colors in the qss
    #  https://stackoverflow.com/questions/13416183/qt-stylesheet-how-to-set-color-of-qpalettelink-and-qplattelinkvisited
    return '<a style="color: #039be5" href=\"{}\">{}</a>'.format(value, value)


class LogRecordStreamHandler(SocketServer.StreamRequestHandler):
    """Lifted from: https://docs.python.org/2.7/howto/logging-cookbook.html
    Handler for a streaming logging request.

    This basically logs the record using whatever logging policy is
    configured locally.
    """

    def handle(self):
        """
        Handle multiple requests - each expected to be a 4-byte length,
        followed by the LogRecord in pickle format. Logs the record
        according to whatever policy is configured locally.
        """
        while True:
            chunk = self.connection.recv(4)
            if len(chunk) < 4:
                break
            slen = struct.unpack('>L', chunk)[0]
            chunk = self.connection.recv(slen)
            while len(chunk) < slen:
                chunk = chunk + self.connection.recv(slen - len(chunk))
            obj = self.un_pickle(chunk)
            level_name = obj.get('levelname')
            if level_name:
                obj['levelname'] = 'remote.' + obj['levelname']
            record = logging.makeLogRecord(obj)
            self.handle_log_record(record)

    def un_pickle(self, data):
        return pickle.loads(data)

    def handle_log_record(self, record):
        # if a name is specified, we use the named logger rather than the one
        # implied by the record.
        if self.server.logname is not None:
            name = self.server.logname
        else:
            name = record.name
        logger = logging.getLogger(name)
        # N.B. EVERY record gets logged. This is because Logger.handle
        # is normally called AFTER logger-level filtering. If you want
        # to do filtering, do it at the client end to save wasting
        # cycles and network bandwidth!
        logger.handle(record)


class LogRecordSocketReceiver(SocketServer.ThreadingTCPServer):
    """Lifted from: https://docs.python.org/2.7/howto/logging-cookbook.html
    Simple TCP socket-based logging receiver suitable for testing.
    """

    allow_reuse_address = 1

    def __init__(self, host='localhost',
                 port=logging.handlers.DEFAULT_TCP_LOGGING_PORT,
                 handler=LogRecordStreamHandler):
        SocketServer.ThreadingTCPServer.__init__(self, (host, port), handler)
        self.abort = 0
        self.timeout = 1
        self.logname = None
        self.kill = False

    def serve_until_stopped(self):
        import select
        abort = 0
        while not abort and not self.kill:
            rd, wr, ex = select.select([self.socket.fileno()],
                                       [], [],
                                       self.timeout)
            if rd:
                self.handle_request()
            abort = self.abort


record_receiver = None


def startup_log_socket(stream_handler=LogRecordStreamHandler):
    """Starts threaded logging socket receiver, if using a visual app a
    thread safe stream handler should be provided.
    :param stream_handler: Logging stream handler default LogRecordStreamHandler
    :return: LogRecordSocketReceiver()
    """
    global record_receiver
    stream_handler = stream_handler or LogRecordStreamHandler
    record_receiver = LogRecordSocketReceiver(handler=stream_handler)
    logging.info('About to start logging TCP server...')
    tcp_thread = threading.Thread(target=record_receiver.serve_until_stopped)
    tcp_thread.start()


def shutdown_log_socket():
    global record_receiver
    if record_receiver:
        record_receiver.kill = True
