# Builin
import os
import sys

import subprocess
import logging.handlers
import json
from SocketServer import ThreadingMixIn
from SimpleXMLRPCServer import SimpleXMLRPCServer

# Internal
import nxt
from nxt.remote import RPC_HOST, RPC_PORT
from nxt import nxt_path, nxt_io, nxt_log

server = None
logger = logging.getLogger('nxt')


class NxtServerException(Exception):
    pass


class NxtServer(ThreadingMixIn, SimpleXMLRPCServer):
    def __init__(self, address, allow_none=True, log_requests=False):
        """Simple Threaded XMLRPCServer.
        :param address: tuple of (HOST, PORT)
        :param allow_none: If True None type objects are marshaled.
        :param log_requests: If True connection requests are logged.
        """
        SimpleXMLRPCServer.__init__(self, addr=address,
                                    allow_none=allow_none,
                                    logRequests=log_requests)


class ServerFunctions(object):
    def __init__(self, log_filepath):
        self.cache_file = None
        self.log_filepath = log_filepath

    def get_log_location(self):
        """Simple method for getting the filepath of the file the server is
        logging to. May be an empty string if the server isn't logging to a
        custom filepath.
        :return: str
        """
        return self.log_filepath or ''

    @staticmethod
    def is_alive():
        """Simple method for clients to use to check if the server is still
        alive.
        :return: True
        """
        logger.info("rpc server is alive and ready")
        return True

    @staticmethod
    def exec_in_headless(filepath, start_node, cache_path,
                         parameters, context_name):
        """Executed the given graph (filepath) with the given start_node in the
        dcc exe (as a sub-process). The temp path (if provided) must be a
        location that the server can read/write. If no temp path is given one
        will be generated. The file at the temp path is used to store the
        cache data to be returned to the caller. Only the file path is
        returned to the caller, not the actual data.
        :param filepath: Path to nxt save file
        :param start_node: start node path
        :param cache_path: Path to store output cache data (if none is given
        one will be generated)
        :param parameters: Optional parameters dict
        :param context_name: name of context, defaults to python
        :return: filepath to temp file
        """
        # Fixme: Contexts must be accessed like this to avoid importing them
        #  again and thus emptying the list of user contexts.
        context = nxt.remote.contexts.find_context_by_name(context_name)
        if not context:
            known = nxt.remote.contexts.iter_context_names()
            logger.debug('Known contexts: \n{}'.format('\n'.join(known)))
            raise NameError('Unknown context "{}"'.format(context_name))
        context_exe = context.exe
        if not context or not context_exe:
            raise TypeError('Unable to find context exe for: '
                            '{}'.format(context))

        context_graph = context.graph
        context_graph = nxt_path.full_file_expand(context_graph)
        if not context_graph:
            raise TypeError('No launch script found for context: '
                            '{}'.format(context))
        # Setup cache file if none provided
        if not cache_path:
            cache_path = nxt_io.generate_temp_file()
        cache_path = cache_path.replace(os.sep, '/')
        # Setup parameters file if parameters provided
        if parameters:
            parameters_file = nxt_io.generate_temp_file()
            parameters_file = parameters_file.replace(os.sep, '/')
            with open(parameters_file, 'w+') as fp:
                json.dump(parameters, fp)
        else:
            parameters_file = ''
        context_graph = context_graph.replace(os.sep, '/')
        logger.info('Starting \n'
                    'Context: {} \n'
                    'Interpreter: {} \n'
                    'Context Graph: {}\n'.format(context, context_exe,
                                                 context_graph))
        logger.info('Cache location: {}\n'.format(cache_path))
        # Format the cli call
        save_graph_path = nxt_path.full_file_expand(filepath)
        # open context with graph and parameters
        os.environ[nxt_log.VERBOSE_ENV_VAR] = 'socket'
        args = [context_exe, '-m', 'nxt.cli', 'exec', context_graph, '-p',
                '/.graph_file', save_graph_path,
                '/.cache_file', cache_path,
                '/.parameters_file', parameters_file]
        if start_node:
            args += ['/.start_node', start_node]
        logger.info('call:  {}'.format(args))
        dcc = subprocess.Popen(args)
        poll = None
        while poll is None:
            poll = dcc.poll()
        exit_code = dcc.returncode
        if exit_code != 0:
            raise NxtServerException(exit_code)
        return cache_path

    def kill(self):
        """Shuts down the running rpc server and attemps to remove the server
        log file if there is one.
        :return: None
        """
        global server
        if server:
            logger.warning('Shutting down rpc server!')
            server.shutdown()
            if self.log_filepath:
                try:
                    logger.debug('Removing server log file: '
                                 '{}'.format(self.log_filepath))
                    os.remove(self.log_filepath)
                except:
                    logger.warning('Failed to remove server log file, '
                                   'if it was an autogenerated file nxt_log '
                                   'will remove it when determined it is '
                                   'stale.')


def run_server(host=RPC_HOST, port=RPC_PORT, log_filepath='',
               log_requests=False):
    nxt_root = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                            '../..')).replace(os.sep, '/')
    os.chdir(nxt_root)
    global server
    server = NxtServer((host, port), log_requests=log_requests)
    server.register_instance(ServerFunctions(log_filepath=log_filepath))
    server.allow_reuse_address = True
    logger.info('Threaded nxt rpc server started!')
    logger.debug('Listening on:   {}:{}'.format(host, port))
    server.serve_forever()


if __name__ == '__main__':
    try:
        log_file = sys.argv[1]
    except IndexError:
        log_file = None
    logger.info('Available contexts: '
                '{}'.format(list(nxt.remote.contexts.iter_context_names())))
    logger.debug('Logging to: {}'.format(log_file))
    logger.info('Starting up server...')
    run_server(log_filepath=log_file)
    logger.info('Logging rpc stdout to: {}'.format(log_file))
