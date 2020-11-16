# Builtin
import os
import json
import logging
import socket
import pickle

# Internal
from nxt.stage import Stage
from nxt import nxt_io
from nxt.runtime import GraphError

logger = logging.getLogger('nxt')

HOST = 'localhost'
CMD_PORT = 4435  # Command port number
COM_PORT = 4436  # Communication port number

HEADER_SIZE = 10  # Fixed header len
HANDSHAKE_TIMEOUT = 60  # Seconds to wait before giving up on handshake
# Global objects
global __nxt_model__
__nxt_model__ = None
MODEL_VAR = '__nxt_model__'
global __nxt_server__
__nxt_server__ = None
SERVER_VAR = '__nxt_server__'


class COM_TYPE(object):
    """Constants used as keys in the pickled message dicts sent over to the
    nxt socket server."""
    LOG = 'log'
    CACHE = 'cache'
    SHUTDOWN = 'shutdown'
    PING = 'ping'
    WAIT = 'wait'
    ERR = 'error'


def setup():
    """Setup a connection to the nxt socket server. Sets the global variable
    __nxt_server__ to the newly created socket instance.
    :return: socket instance
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setblocking(1)
    s.connect((HOST, COM_PORT))
    logger.socket('Connected to: {}:{}'.format(HOST, COM_PORT))
    global __nxt_server__
    __nxt_server__ = s
    return s


def format_msg(msg, com_typ, msg_dict=None):
    """Formats the given msg into a dict matching the expected format used by
    nxt socket servers and clients.
    :param msg: Object to be formatted as a socket message
    :param com_typ: COM_TYPE constant
    :param msg_dict: Optionally if you are combining commands you can pass an
    existing msg_dict returned from a previous call to this function.
    :return: dict
    """
    if not msg_dict:
        msg_dict = {}
    msg_dict[com_typ] = msg
    return msg_dict


def get_nxt_model():
    """Gets the existing SocketClientModel instance in global scope, if none is
    found a new one is created and returned. It is stored in the global scope
    to allow maximum context compatibility.
    :return: SocketClientModel instance
    """
    global __nxt_model__
    if __nxt_model__ is None:
        m = SocketClientModel(None)
        __nxt_model__ = m
    return __nxt_model__


class SocketClientModel(object):
    """Simple nxt model used by remote socket clients"""
    def __init__(self, com_server):
        self.filepath = None
        self.exec_order = None
        self.param_filepath = None
        self.file_data = {}
        self.stage = None
        self.comp_layer = None
        self.runtime_layer = None
        self.cache_filepath = None
        self.server = com_server

    def load(self, filepath):
        """Loads the given file path and builds a comp layer ready to be
        executed.
        :param filepath: string of nxt save filepath.
        :return: None
        """
        with IPCWait(self):
            logger.socket('Loading file data from {}...'.format(filepath))
            self.filepath = filepath
            self.file_data = nxt_io.load_file_data(self.filepath)
            logger.socket('Building stage...')
            self.stage = Stage(self.file_data)
            self._rebuild_comp()

    def _run(self, exec_order=()):
        """Private method for executing nodes, not meant to be called outside
        of a IPCWait context manager.
        :param exec_order: Optional list of node paths to execute.
        :raises GraphError
        :return: True if no errors were detected.
        """
        if exec_order:
            self.exec_order = exec_order
        if not self.stage:
            logger.error('No stage built, cannot run!')
            return False
        parameters = {}
        if os.path.isfile(self.param_filepath or ''):
            with open(self.param_filepath, 'r') as fp:
                parameters = json.load(fp)
        if not self.runtime_layer:
            self._rebuild_comp()
        self.runtime_layer = self.stage.execute_nodes(self.exec_order,
                                                      self.runtime_layer,
                                                      parameters=parameters)
        return True

    def run(self, exec_order=()):
        """General purpose run function meant to be called over a socket
        command port. If a GraphError is raised the internal nxt ERR message
        is sent over the socket to the server.
        :param exec_order: Optional list of node paths to execute.
        :return: None
        """
        with IPCWait(self):
            try:
                self._run(exec_order)
            except GraphError:
                send_to_server(format_msg(None, COM_TYPE.ERR))

    def refresh(self):
        """Refresh (rebuild) stage and comp objects.
        :return: None
        """
        with IPCWait(self):
            if not self.filepath:
                logger.error('No filepath, cannot refresh!')
                return
            self.file_data = nxt_io.load_file_data(self.filepath)
            self.stage = Stage(self.file_data)
            self._rebuild_comp()

    def _rebuild_comp(self):
        """Private method for rebuilding comp layer. Not meant to be called
        oustide of a IPCWait context manger.
        :return: None
        """
        with IPCWait(self):
            if not self.stage:
                logger.error('No data loaded, cannot re-build!')
                return

            logger.compinfo('Rebuilding comp...')
            self.comp_layer = self.stage.build_stage()
            logger.compinfo('Rebuilding runtime layer...')
            self.runtime_layer = self.stage.setup_runtime_layer(self.comp_layer)

    def close(self, notify_server=False):
        """Attempts to gracefully close connection to nxt socket server."""
        # with IPCWait(self):
        for log_handler in logger.handlers:
            if isinstance(log_handler, NXTSocketLogHandler):
                logger.removeHandler(log_handler)
                logger.debug('Removed nxt log handler')
                break
        if notify_server:
            send_to_server(format_msg(None, COM_TYPE.SHUTDOWN))
            logger.socket('Telling nxt server to close connection!')
        global __nxt_server__
        if __nxt_server__:
            __nxt_server__.close()
        __nxt_server__ = None
        self.server = __nxt_server__

    def open(self):
        """Opens connection to nxt socket server. Installs
        NXTSocketLogHandler logging handler if none is installed.
        :return: None
        """
        logger.socket('Connecting to listener...')
        self.server = setup()
        global __nxt_server__
        __nxt_server__ = self.server
        setup_socket_log = True
        for log_handler in logger.handlers:
            if isinstance(log_handler, NXTSocketLogHandler):
                setup_socket_log = False
                break
        if setup_socket_log:
            logger.debug('Making new log handler!')
            logger.addHandler(NXTSocketLogHandler())
        logger.socket('Successfully connected to listener!')

    def ping(self):
        """Debug function for testing 2 way communication from the nxt socket
        server to this client.
        :return:
        """
        logger.socket('Pinging...')
        with IPCWait(self):
            send_to_server(format_msg('', COM_TYPE.PING))
        logger.socket('Pinged!')

    def get_cache(self):
        """Method for the nxt socket server to request cache data from this
        client model.
        :return: Save data dict
        """
        with IPCWait(self):
            save_data = self.runtime_layer.cache_layer.save(self.cache_filepath)
            send_to_server(format_msg(save_data, COM_TYPE.CACHE))
        return save_data


def send_log(record):
    """Simple method for sending log records to an nxt socket server.
    :param record: logging record
    :return: None
    """
    links = getattr(record, 'links', None)
    data_dict = format_msg([record.levelno, record.message, links],
                           COM_TYPE.LOG)
    send_to_server(data_dict)


def send_to_server(data_dict):
    """Pickles the given data, assembles fixed length header, casts to bytes
    and sends to the nxt socket server.
    NOTE: This function catches ALL exceptions raised by the socket instance!
    :param data_dict: Dict formatted by format_msg
    :return: None
    """
    # Don't use logging in here as it can cause in infinite loop. The logging
    # handler calls this function.
    global __nxt_server__
    if not __nxt_server__:
        logger.error("No server! Try toggling the command port.")
        return
    msg = pickle.dumps(data_dict)
    header = bytes("{:<{}}".format(len(msg), HEADER_SIZE))
    data = header + msg
    # logger.debug('Size of data: {}'.format(sys.getsizeof(data)))
    try:
        __nxt_server__.sendall(data)
    except Exception as e:
        if e.errno == 10053:  # Stale socket
            __nxt_server__ = None
        else:
            logger.exception('Failed to send data to socket server!')


class IPCWait(object):
    """Simple context manager for telling the server to wait while a command
    is being processed by the client interpreter.
    """
    def __init__(self, model):
        self.model = model
        global __nxt_server__
        self.server = __nxt_server__

    def send_wait_msg(self, state):
        if not self.server:
            logger.error("No server, context manager doesn't know what to do!")
            return
        # logger.debug('Telling nxt to wait {}'.format(state))
        send_to_server(format_msg(state, COM_TYPE.WAIT))
        self.server.settimeout(HANDSHAKE_TIMEOUT)
        try:
            okay = self.server.recv(1024)
        except Exception as e:
            logger.exception('Failed to receive data from server! Try '
                             'toggling the command port.')
            return
        self.server.settimeout(None)
        # logger.debug('Server gave okay msg: {}'.format(okay))
        if not okay:
            logger.error('Failed to handshake!')
            send_to_server(format_msg(False, COM_TYPE.WAIT))
            return

    def __enter__(self):
        self.send_wait_msg(True)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.send_wait_msg(False)


class NXTSocketLogHandler(logging.Handler):
    """Simple logging handler for emitting log records to the nxt socket
    server.
    """
    def __init__(self):
        logging.Handler.__init__(self)

    def emit(self, record):
        send_log(record)
