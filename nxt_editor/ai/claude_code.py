"""Use Claude through the Claude Code app the user already has.

Anthropic does not let other apps sign in to a Claude account, but Claude
Code can be run headless (claude -p) and does the signing in itself. So
the editor never sees a token: whatever account Claude Code is signed in
to (Pro, Max, Ultra, Team, Enterprise or a Console account) is the one
used, with that account's limits.
https://code.claude.com/docs/en/headless
"""
# Builtin
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

# Internal
import nxt_editor
from nxt_editor import user_dir
from nxt_editor.ai import mcp_server

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

INSTALL_URL = 'https://code.claude.com/docs/en/setup'
# Aliases Claude Code turns into the newest model of each kind.
MODELS = ['opus', 'sonnet', 'fable', 'haiku']
PLANS = {'pro': 'Pro', 'max': 'Max', 'ultra': 'Ultra', 'team': 'Team',
         'enterprise': 'Enterprise'}
STATUS_LIFE = 30
# Rounds of tool use in one reply.
MAX_TURNS = 40
_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0


class ClaudeCodeError(Exception):
    pass


def _install_places():
    """Where Claude Code's installers put it, for when a host's PATH (a
    rez or DCC environment) leaves them out."""
    home = os.path.expanduser('~')
    if sys.platform == 'win32':
        appdata = os.environ.get('APPDATA') or os.path.join(
            home, 'AppData', 'Roaming')
        local = os.environ.get('LOCALAPPDATA') or os.path.join(
            home, 'AppData', 'Local')
        return [os.path.join(home, '.local', 'bin', 'claude.exe'),
                os.path.join(appdata, 'npm', 'claude.cmd'),
                os.path.join(local, 'Programs', 'claude', 'claude.exe'),
                os.path.join(local, 'Microsoft', 'WinGet', 'Links',
                             'claude.exe')]
    return [os.path.join(home, '.local', 'bin', 'claude'),
            os.path.join(home, '.claude', 'local', 'claude'),
            os.path.join(home, '.npm-global', 'bin', 'claude'),
            '/opt/homebrew/bin/claude', '/usr/local/bin/claude',
            '/usr/bin/claude']


def _unwrap(found):
    if found.lower().endswith('.cmd'):
        # npm's wrapper goes through cmd.exe; run the program it wraps.
        real = os.path.join(os.path.dirname(found), 'node_modules',
                            '@anthropic-ai', 'claude-code', 'bin',
                            'claude.exe')
        if os.path.isfile(real):
            return real
    return found


def find_cli():
    """The claude command, or None when Claude Code is not installed."""
    chosen = user_dir.user_prefs.get(user_dir.USER_PREF.AI_CLAUDE_CODE_PATH)
    if chosen and os.path.isfile(chosen):
        return _unwrap(chosen)
    found = shutil.which('claude')
    if found:
        return _unwrap(found)
    for path in _install_places():
        if os.path.isfile(path):
            return _unwrap(path)
    return None


def _child_env():
    env = dict(os.environ)
    # Otherwise Claude Code would bill these instead of the sign in.
    for name in ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN'):
        env.pop(name, None)
    return env


_status = {'at': 0, 'value': None}
_status_lock = threading.Lock()


def status(cli=None, cached=True):
    """What `claude auth status` says, or None when Claude Code is not
    installed or did not answer."""
    with _status_lock:
        if cached and time.time() - _status['at'] < STATUS_LIFE:
            return _status['value']
    cli = cli or find_cli()
    value = None
    if cli:
        try:
            result = subprocess.run([cli, 'auth', 'status', '--json'],
                                    capture_output=True, text=True,
                                    encoding='utf-8', errors='replace',
                                    timeout=20, env=_child_env(),
                                    creationflags=_NO_WINDOW)
            value = json.loads(result.stdout)
        except (OSError, ValueError, subprocess.TimeoutExpired) as err:
            logger.debug('Claude Code did not say who is signed in: '
                         '{}'.format(err))
    with _status_lock:
        _status['at'] = time.time()
        _status['value'] = value
    return value


def forget_status(older_than=0):
    """Ask Claude Code again next time, if what it said is older than
    older_than seconds."""
    with _status_lock:
        if time.time() - _status['at'] >= older_than:
            _status['at'] = 0


def signed_in(cli=None, cached=True):
    """Who Claude Code is signed in as, as a record, or None."""
    found = status(cli, cached=cached)
    if not found or not found.get('loggedIn'):
        return None
    plan = found.get('subscriptionType')
    return {'email': found.get('email'),
            'plan': PLANS.get(plan, plan.title() if plan else None),
            'auth_method': found.get('authMethod')}


_URL = re.compile(r'https://\S+')


class Login(object):
    """`claude auth login`, run without a window.

    Claude Code opens the browser itself, where the user picks the Claude
    account. Its sign in page can also show a code to paste back, which
    send_code passes on.
    """

    def __init__(self, cli=None, popen=subprocess.Popen):
        cli = cli or find_cli()
        if not cli:
            raise ClaudeCodeError('Claude Code is not installed.')
        forget_status()
        self.url = None
        self.output = []
        self.got_url = threading.Event()
        self.process = popen([cli, 'auth', 'login'], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, env=_child_env(),
                             creationflags=_NO_WINDOW)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for raw in self.process.stdout:
            line = raw.decode('utf-8', 'replace').strip()
            self.output.append(line)
            found = _URL.search(line)
            if found and not self.url:
                self.url = found.group(0)
                self.got_url.set()
        self.got_url.set()

    def send_code(self, code):
        code = (code or '').strip()
        if not code or self.process.poll() is not None:
            return
        self.process.stdin.write((code + '\n').encode('utf-8'))
        self.process.stdin.flush()

    def wait(self, cancelled, timeout=900, interval=0.25, sleep=time.sleep):
        """Wait for the sign in to finish. Gives back who is signed in."""
        end = time.monotonic() + timeout
        while self.process.poll() is None:
            if cancelled.is_set():
                self.cancel()
                return None
            if time.monotonic() > end:
                self.cancel()
                raise ClaudeCodeError('Gave up waiting for the Claude sign '
                                      'in.')
            sleep(interval)
        forget_status()
        record = signed_in(cached=False)
        if self.process.returncode or not record:
            said = [l for l in self.output if l and not _URL.search(l)]
            raise ClaudeCodeError(said[-1] if said else
                                  'Claude Code did not sign in.')
        return record

    def cancel(self):
        if self.process.poll() is None:
            self.process.kill()


def logout(cli=None):
    cli = cli or find_cli()
    forget_status()
    if cli:
        subprocess.run([cli, 'auth', 'logout'], capture_output=True,
                       timeout=30, env=_child_env(),
                       creationflags=_NO_WINDOW)


def as_prompt(messages):
    """claude -p takes one prompt, so earlier turns go in front of it."""
    if len(messages) == 1:
        return messages[0]['content']
    lines = ['The chat so far:']
    for message in messages[:-1]:
        who = 'User' if message['role'] == 'user' else 'You'
        lines.append('{}: {}'.format(who, message['content']))
    lines.append('')
    lines.append('Answer this next message from the user:')
    lines.append(messages[-1]['content'])
    return '\n\n'.join(lines)


def _work_dir():
    # An empty folder of its own, so no project's CLAUDE.md is picked up.
    path = os.path.join(user_dir.PREF_DIR, 'claude_code')
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def stream_chat(messages, system, model=None, cli=None, tools=None):
    """Yield Claude's reply a piece at a time, from claude -p.

    :param tools: a tools.Toolbox. Its tools are served to Claude Code by
        the editor's MCP server, and are the only tools it gets.
    """
    cli = cli or find_cli()
    if not cli:
        raise ClaudeCodeError('Claude Code is not installed.')
    handle, system_file = tempfile.mkstemp(prefix='nxt_ai_', suffix='.txt')
    with os.fdopen(handle, 'w', encoding='utf-8') as f:
        f.write(system)
    # None of Claude Code's own tools, and no MCP servers but the editor's.
    args = [cli, '-p', '--output-format', 'stream-json', '--verbose',
            '--include-partial-messages', '--system-prompt-file',
            system_file, '--tools', '', '--no-session-persistence',
            '--strict-mcp-config', '--disable-slash-commands']
    if model:
        args += ['--model', model]
    server = token = config_file = None
    if tools is not None and tools.available():
        server = mcp_server.server()
        token = server.open(tools)
        handle, config_file = tempfile.mkstemp(prefix='nxt_mcp_',
                                               suffix='.json')
        with os.fdopen(handle, 'w', encoding='utf-8') as f:
            json.dump(server.config(token), f)
        args += ['--mcp-config', config_file,
                 '--allowedTools', 'mcp__' + mcp_server.NAME,
                 '--max-turns', str(MAX_TURNS)]
    process = None
    try:
        process = subprocess.Popen(args, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=_work_dir(),
                                   env=_child_env(),
                                   creationflags=_NO_WINDOW)
        process.stdin.write(as_prompt(messages).encode('utf-8'))
        process.stdin.close()
        streamed = False
        # Text from before and after a tool is used, kept apart.
        gap = False
        for raw in process.stdout:
            try:
                data = json.loads(raw.decode('utf-8'))
            except ValueError:
                continue
            kind = data.get('type')
            if kind == 'stream_event':
                event = data.get('event', {})
                delta = event.get('delta', {})
                if event.get('type') == 'message_start' and streamed:
                    gap = True
                elif (event.get('type') == 'content_block_delta' and
                        delta.get('type') == 'text_delta'):
                    if gap:
                        gap = False
                        yield '\n\n'
                    streamed = True
                    yield delta.get('text', '')
            elif kind == 'result':
                if data.get('is_error'):
                    raise ClaudeCodeError(data.get('result') or
                                          'Claude Code stopped with an '
                                          'error.')
                if not streamed and data.get('result'):
                    yield data['result']
                return
        process.wait(30)
        error = process.stderr.read().decode('utf-8', 'replace').strip()
        raise ClaudeCodeError(error.splitlines()[-1] if error else
                              'Claude Code stopped without answering.')
    finally:
        if process is not None and process.poll() is None:
            process.kill()
        if token:
            server.close(token)
        for path in (system_file, config_file):
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass
