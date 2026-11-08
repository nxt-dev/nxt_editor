"""The editor's MCP server, so Claude Code can use the assistant's tools.

A Claude Code sign in is used by running Claude Code (see claude_code),
and Claude Code takes tools from MCP servers. So while a reply is coming,
the editor serves its tools (see tools) over MCP's Streamable HTTP, on
this computer only, behind a key made for that reply alone.

Plain Python, so it works the same in every host.
https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
"""
# Builtin
import http.server
import json
import logging
import secrets
import sys
import threading
import urllib.parse

# Internal
import nxt_editor
from nxt_editor.constants import EDITOR_VERSION

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

NAME = 'nxt'
PATH = '/mcp'
VERSIONS = ('2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05')
LOCAL_HOSTS = ('127.0.0.1', 'localhost', '[::1]')
MAX_BODY = 8 * 1024 * 1024

INSTRUCTIONS = ('Tools for the graph open in the nxt editor: look at it, '
                'search it, change it and run it.')


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'nxt-mcp'
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        logger.debug('MCP: ' + fmt % args)

    def _send(self, status, body=None, headers=None):
        data = b''
        if body is not None:
            data = json.dumps(body).encode('utf-8')
        self.send_response(status)
        if body is not None:
            self.send_header('Content-Type', 'application/json')
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        if data:
            self.wfile.write(data)

    def _allowed(self):
        """Only from this computer, and only with a reply's key."""
        origin = self.headers.get('Origin')
        if origin:
            host = urllib.parse.urlparse(origin).hostname or ''
            if host not in ('127.0.0.1', 'localhost', '::1'):
                self._send(403, {'error': 'Not from this computer'})
                return None
        auth = self.headers.get('Authorization') or ''
        token = auth[7:] if auth.startswith('Bearer ') else ''
        toolbox = self.server.owner.toolbox_for(token)
        if toolbox is None:
            self._send(401, {'error': 'No reply is using the tools'})
            return None
        return toolbox

    def do_GET(self):
        # No stream from the server: everything is answered in the POST.
        self._send(405, None, {'Allow': 'POST'})

    def do_DELETE(self):
        self._send(405, None, {'Allow': 'POST'})

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != PATH:
            self._send(404, {'error': 'Not found'})
            return
        toolbox = self._allowed()
        if toolbox is None:
            return
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            self._send(400, _error(None, -32600, 'Bad request'))
            return
        try:
            message = json.loads(self.rfile.read(length).decode('utf-8'))
        except ValueError:
            self._send(400, _error(None, -32700, 'Parse error'))
            return
        batch = isinstance(message, list)
        answers = [a for a in (handle(toolbox, m) for m in
                               (message if batch else [message]))
                   if a is not None]
        if not answers:
            self._send(202)
        else:
            self._send(200, answers if batch else answers[0])


def _error(msg_id, code, text):
    return {'jsonrpc': '2.0', 'id': msg_id,
            'error': {'code': code, 'message': text}}


def handle(toolbox, message):
    """The answer to one JSON-RPC message, or None for a notification."""
    if not isinstance(message, dict):
        return _error(None, -32600, 'Invalid request')
    method = message.get('method')
    msg_id = message.get('id')
    if msg_id is None:
        return None
    params = message.get('params') or {}
    if method == 'initialize':
        asked = params.get('protocolVersion')
        result = {'protocolVersion': asked if asked in VERSIONS
                  else VERSIONS[0],
                  'capabilities': {'tools': {'listChanged': False}},
                  'serverInfo': {'name': NAME,
                                 'version': EDITOR_VERSION.VERSION_STR},
                  'instructions': INSTRUCTIONS}
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        result = {'tools': toolbox.mcp_tools()}
    elif method == 'tools/call':
        text, failed = toolbox.call(params.get('name'),
                                    params.get('arguments') or {})
        result = {'content': [{'type': 'text', 'text': text}],
                  'isError': bool(failed)}
    else:
        return _error(msg_id, -32601, 'No method {}'.format(method))
    return {'jsonrpc': '2.0', 'id': msg_id, 'result': result}


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def handle_error(self, request, client_address):
        # Claude Code drops its connection when a reply ends; that is not
        # worth a traceback in the output.
        error = sys.exc_info()[1]
        if isinstance(error, (ConnectionError, TimeoutError)):
            logger.debug('MCP connection closed: {}'.format(error))
            return
        logger.exception('MCP request from {} failed'.format(
            client_address))


class McpServer(object):
    """Serves the tools of the replies using them. Started on first use and
    left running; it answers nothing without a reply's key."""

    def __init__(self):
        self._lock = threading.Lock()
        self._server = None
        self._thread = None
        self._toolboxes = {}

    @property
    def url(self):
        self.start()
        host, port = self._server.server_address[:2]
        return 'http://{}:{}{}'.format(host, port, PATH)

    def start(self):
        with self._lock:
            if self._server is not None:
                return
            self._server = _Server(('127.0.0.1', 0), _Handler)
            self._server.owner = self
            self._thread = threading.Thread(target=self._server.serve_forever,
                                            name='nxt-mcp', daemon=True)
            self._thread.start()

    def stop(self):
        with self._lock:
            server, self._server = self._server, None
            self._toolboxes.clear()
        if server is not None:
            server.shutdown()
            server.server_close()

    def open(self, toolbox):
        """Let toolbox be used until close. Gives back its key."""
        self.start()
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._toolboxes[token] = toolbox
        return token

    def close(self, token):
        with self._lock:
            self._toolboxes.pop(token, None)

    def toolbox_for(self, token):
        if not token:
            return None
        with self._lock:
            for key, toolbox in self._toolboxes.items():
                if secrets.compare_digest(key, token):
                    return toolbox
        return None

    def config(self, token):
        """Claude Code's --mcp-config for one reply."""
        return {'mcpServers': {NAME: {
            'type': 'http', 'url': self.url,
            'headers': {'Authorization': 'Bearer ' + token}}}}


_server = None


def server():
    global _server
    if _server is None:
        _server = McpServer()
    return _server
