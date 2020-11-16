# Built-in
import os
import logging
import subprocess
import sys
import time
import socket

# Internal
import nxt_log
import nxt_io
import nxt_path
import remote
import remote.client
import remote.server
import remote.contexts
from stage import Stage

logger = logging.getLogger(__name__)


class Session(object):
    """Nxt Session, manages loading, saving, and execution of graphs."""
    def __init__(self):
        self._loaded_files = {}
        self.log_file = nxt_log.make_session_log()
        self.rpc_server = None

    @property
    def loaded_files(self):
        return self._loaded_files

    def new_file(self):
        """Create a new (empty) graph.

        :return: New graph object.
        """
        new_graph = Stage(name=self.get_unused_graph_name('untitled'))
        self._loaded_files[new_graph.uid] = new_graph
        return new_graph

    def get_unused_graph_name(self, name):
        """Used by new_file() to make sure that any new graph created won't
        conflict with the names of currently open graphs.

        :param name: Name preference, adjusted to remove conflicts if needed.
        :type name: str

        :return: Resulting name, may not match input name preference.
        """
        def test_name(n):
            for stage in self._loaded_files.values():
                if n == stage._name:
                    return False
            return True

        result_name = ''
        num_suffix = 0
        potential_name = name
        while result_name == '':
            if test_name(potential_name):
                result_name = potential_name
            else:
                num_suffix += 1
                potential_name = name + str(num_suffix)

        return result_name

    def load_file(self, filepath):
        """Create a new graph from given filepath.

        :param filepath: Path to .json file to load.
        :type filepath: str

        :return: New graph object, if load succeeded. Otherwise None.
        :rtype: Graph
        """
        e = None
        try:
            layer_data = nxt_io.load_file_data(filepath)
            new_stage = Stage(layer_data=layer_data)
        except IOError as e:
            logger.exception('Failed to open: "{}"'.format(filepath))
            new_stage = None

        if not new_stage:
            new_stage = Stage(name='File Error')
            d = {'comment': 'Failed to load the file {}\n'
                            '{}'.format(filepath, e.message)}
            new_stage.add_node(name='ERR', data=d)
            new_stage.top_layer.color = 'red'
            new_stage.top_layer.alias = 'Failed_Open'
        self._loaded_files[new_stage.uid] = new_stage
        return new_stage

    def unload_file(self, uid):
        unload_key = [k for k in self.loaded_files.keys() if k == uid]
        uid_lst = [k for k in self.loaded_files.keys()]
        if not unload_key:
            err_format = ('Unable to find a graph with the uuid {uid} '
                          'exsisting uuids are {uidLst}')
            raise LookupError(err_format.format(uid=uid, uidLst=uid_lst))
        unload_key = unload_key[0]
        self.loaded_files.pop(unload_key)

    def save_file(self, graph_file_path, new_path=None):
        """The file to save is specified via graph_file_path.
        If new_path is specified, it will change the path used to
        identify the graph in the future.

        :param graph_file_path: path used to locate file to save in currently
                                loaded files.
        :type graph_file_path: str

        :param new_path: If specified, saves the specified file to a new path.
        :type new_path: str

        :return: True/False if successful
        """
        target_path = graph_file_path
        if new_path:
            target_path = os.path.normcase(new_path)
        current_path = None
        if graph_file_path:
            current_path = os.path.normcase(graph_file_path)
        if current_path in (k[0] for k in self._loaded_files.keys()):
            self._loaded_files[current_path].save_layer(filepath=target_path)
            if current_path != target_path:
                changed_graph = self._loaded_files.pop(current_path)
                self._loaded_files[target_path] = changed_graph
            return True
        else:
            return False

    def save_layer(self, layer, filepath=None):
        layer.save(filepath=filepath)

    def get_stage(self, path):
        """Get the graph object for a specified file path.
        If the file is not already loaded, it will be.

        :param path: Path to file the graph is loaded from.
        :type path: str

        :return: Graph object, if found, otherwise None.
        """
        norm_path = os.path.normcase(path)
        for uid, data in self._loaded_files.iteritems():
            if data.filepath == norm_path:
                return self._loaded_files[uid]
        else:
            return self.load_file(path)

    def execute_graph(self, filepath, start=None, parameters=None):
        """Execute the graph at the given file path. Optionally at given
        start. You may provided parameters to the parameter arg. The data
        should be formatted as follows:
            {
                '/node.attr': 'New value!',
                '/another.count: 5
            }
        If the node does not exist an error will be logged but the execution
        will continue. If the attr does not exist (but the node does) it
        will be created.

        :param filepath: Path to the graph file.
        :type filepath: str

        :param start: Path to the node to begin execution from OR int
        of start node index
        :type start: str or int

        :param parameters: Dict where key is attr path and value is new attr
        value.
        :type parameters: dict

        :return: a runtime CompLayer.
        """
        stage = self.get_stage(filepath)
        self.start_rpc_if_needed(stage)
        try:
            return stage.execute(start=start, parameters=parameters)
        finally:
            self.shutdown_rpc_server()

    def execute_nodes(self, filepath, node_paths, parameters=None):
        stage = self.get_stage(filepath)
        self.start_rpc_if_needed(stage)
        comp_layer = stage.build_stage()
        try:
            return stage.execute_nodes(node_paths=node_paths,
                                       layer=comp_layer, parameters=parameters)
        finally:
            self.shutdown_rpc_server()

    def start_rpc_if_needed(self, stage):
        """Given a stage this method parses for the remote context node,
        if it is found in the stage's sub_layers an rpc is started.
        (if one is already run a new on will NOT be started)
        :param stage: stage.Stage instance
        :return: None
        """
        # Remote Graphs
        remote_node_name = remote.contexts.REMOTE_CONTEXT_BUILTIN_NODE
        remote_path = nxt_path.join_node_paths(nxt_path.NODE_SEP,
                                               remote_node_name)
        # Sub-graphs that might call remote graphs
        sub_graph_node_name = remote.contexts.SUB_GRAPH_BUILTIN_NODE
        sub_graph_path = nxt_path.join_node_paths(nxt_path.NODE_SEP,
                                                  sub_graph_node_name)
        start_rpc = False
        for layer in stage._sub_layers:
            if layer.lookup(remote_path) or layer.lookup(sub_graph_path):
                start_rpc = True
                break
        if start_rpc:
            self._start_rpc_server()
            return
        logger.info('It was determined you do not need an rpc server.')

    def _start_rpc_server(self, custom_stdout=False, rpc_log_filepath=None,
                          socket_log=False, stream_handler=None):
        """Directly start the RPC server regardless of need for it.
        :param custom_stdout: If True the stdout and stderr of the rpc server
        will be directed to a file on disc
        :param rpc_log_filepath: Optional filepath to be used for custom_stdout.
        The file must be writeable. If custom_stdout is False this kwarg has
        no effect.
        :param socket_log: If True the a nxt logging messages will be
        directed to a socket handler.
        :return: None
        """
        logger.debug('Starting rpc server!')
        rpc_server = RPCServerProcess.start(use_custom_stdout=custom_stdout,
                                            stdout_filepath=rpc_log_filepath,
                                            socket_log=socket_log,
                                            stream_handler=stream_handler)
        self.rpc_server = rpc_server

    def shutdown_rpc_server(self):
        """Attempts to close THIS session's rpc server, if this session
        doesn't own the server it will not shut it down.
        :return: None
        """
        if not self.rpc_server:
            logger.debug('This session does not own an rpc server.')
            return
        logger.debug('Trying to shutdown rpc server...')
        try:
            self.rpc_server.terminate()
        except:
            logging.exception('Failed to shut down rpc server!')
            pass
        self.rpc_server = None


class RPCServerProcess(object):
    STARTUP_TIMEOUT = 5

    def __init__(self, use_custom_stdout=False, stdout_filepath=None,
                 socket_log=False, stream_handler=None):
        """Uses a subprocess to start remote/server.py
        If it is determined there is already a server running somewhere on
        the host address then run will early exit. If for some reason the
        port is occupied by another process that is not our RPC server an
        exception is raised.
        :param use_custom_stdout: If True the stdout/stderr of the subprocess
        is populated by a file handle to a custom filepath.
        :param stdout_filepath: Optionally, if you don't want a generated
        temp file as the stdout file a path to your desired output file can
        be passed here. Has no effect if use_custom_stdout is False.
        :param socket_log: If True the a nxt logging messages will be
        :param stream_handler: Logging stream handler only needed if calling
        from visual app.
        directed to a socket handler.
        """
        self.terminal = None
        self.use_custom_stdout = use_custom_stdout
        self.server_log_file = stdout_filepath or ''
        self.socket_logging = socket_log
        self.stream_handler = stream_handler

    @classmethod
    def start(cls, use_custom_stdout=False, stdout_filepath=None,
              socket_log=False, stream_handler=None):
        """Quick start method for starting and returning a server if needed
        :param use_custom_stdout: see __init__
        :param stdout_filepath: see __init__
        :param socket_log: see __init__
        :return: None or RPCServerProcess instance
        """
        if 'maya' in sys.executable.lower():
            # Maya's reimplementation of subprocess prevents our rpc server
            # from working.
            logger.warning('The nxt rpc server cannot be started from inside '
                           'Maya.')
            return
        rpc_server = cls(use_custom_stdout=use_custom_stdout,
                         stdout_filepath=stdout_filepath,
                         socket_log=socket_log, stream_handler=stream_handler)
        if rpc_server.run():
            return rpc_server

    def run(self):
        """Method for starting rpc server sub-process
        :raises: OSError
        :return: True if server was started, else False.
        """
        if self.is_running():
            logger.info('Server already running somewhere...')
            return False
        elif not self.is_port_available():
            raise OSError('Port {} is not available!'.format(remote.RPC_PORT))
        old_env_verbosity = os.environ.get(nxt_log.VERBOSE_ENV_VAR, None)
        if self.socket_logging:
            os.environ[nxt_log.VERBOSE_ENV_VAR] = 'socket'
        if self.use_custom_stdout:
            if not self.server_log_file:
                _ext = '.nxtlog'
                self.server_log_file = nxt_io.generate_temp_file(suffix=_ext)
                nxt_log.track_log_file(self.server_log_file)
            server_log_handle = open(self.server_log_file, 'w')
            nxt_log.startup_log_socket(stream_handler=self.stream_handler)
        else:
            server_log_handle = None
        call = [sys.executable, '-m', 'nxt.remote.server', self.server_log_file]
        logger.debug("Calling: ")
        logger.debug(str(call))
        self.terminal = subprocess.Popen(call, stdout=server_log_handle,
                                         stderr=server_log_handle)
        count = 0
        while count < self.STARTUP_TIMEOUT:
            logger.debug('Waiting on rpc server...')
            time.sleep(1)
            count += 1
            if self.is_running():
                break
        if count == self.STARTUP_TIMEOUT:
            raise OSError('Failed to start RPC server!')
        logger.debug('rpc server started')
        if old_env_verbosity is not None:
            os.environ[nxt_log.VERBOSE_ENV_VAR] = old_env_verbosity
        return True

    def is_running(self):
        """Attempts to connect to the rpc server as a client, if that fails
        because the connection is refused the subprocess is polled. If this
        instance doesn't own the subprocess and it fails to connect as a
        client False is returned.
        :return: bool of server running state
        """
        is_running = False
        try:
            proxy = remote.client.NxtClient()
            is_running = proxy.is_alive()
        except Exception as e:
            # Connection refused
            if getattr(e, 'errno', -1) == 10061 and self.terminal:
                poll = self.terminal.poll()
                if poll is None:
                    is_running = True
        return is_running

    def terminate(self):
        """Attempts to kill the rpc server.
        Note: The server is killed even if it isn't owned by this class!
        :return: None
        """
        try:
            proxy = remote.client.NxtClient()
            proxy.kill()
        except Exception as e:
            if getattr(e, 'errno', -1) == 10061 and self.terminal:
                try:
                    logger.info('Telling rpc server to shutdown...')
                    proxy = remote.client.NxtClient()
                    proxy.kill()
                    self.server_log_file = ''
                except:
                    logger.warning(
                        'Unable to tell rpc server to shutdown!')
                try:
                    self.terminal.terminate()
                    self.terminal = None
                    logger.debug('RPC server has shutdown!')
                except:
                    logger.warning('Unable to kill rpc process!')
        nxt_log.shutdown_log_socket()

    @staticmethod
    def is_port_available():
        """Checks if the rpc port is occupied.
        :return: bool
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        address = (remote.RPC_HOST, remote.RPC_PORT)
        results = s.connect_ex(address)
        s.close()
        if results == 0:
            return False
        return True
