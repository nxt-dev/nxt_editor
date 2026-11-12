"""Use a ChatGPT account through the Codex app the user already has.

Codex signs in to ChatGPT itself (codex login) and can be run headless
(codex exec), so the editor never sees a token: whatever account Codex is
signed in to is the one used, with that account's limits. The assistant's
tools reach it through the editor's MCP server, as they do Claude Code's.
https://developers.openai.com/codex/noninteractive
"""
# Builtin
import base64
import glob
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

INSTALL_URL = 'https://developers.openai.com/codex/cli'
STATUS_LIFE = 30
# The editor's MCP key goes to Codex in this variable, not on the command
# line where other programs can see it.
TOKEN_VAR = 'NXT_MCP_TOKEN'
PLANS = {'free': 'Free', 'go': 'Go', 'plus': 'Plus', 'pro': 'Pro',
         'team': 'Team', 'business': 'Business', 'enterprise': 'Enterprise',
         'edu': 'Edu'}
# Codex's own tools are turned off: it gets only the editor's.
OWN_TOOLS_OFF = ('shell_tool', 'unified_exec', 'multi_agent', 'apps',
                 'plugins', 'browser_use', 'computer_use', 'view_image',
                 'memories', 'hooks', 'goals')
_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0


class CodexError(Exception):
    pass


def _install_places():
    """Where Codex's installers put it, for when a host's PATH (a rez or
    DCC environment) leaves them out."""
    home = os.path.expanduser('~')
    if sys.platform == 'win32':
        appdata = os.environ.get('APPDATA') or os.path.join(
            home, 'AppData', 'Roaming')
        local = os.environ.get('LOCALAPPDATA') or os.path.join(
            home, 'AppData', 'Local')
        return [os.path.join(home, '.local', 'bin', 'codex.exe'),
                os.path.join(appdata, 'npm', 'codex.cmd'),
                os.path.join(local, 'Programs', 'codex', 'codex.exe'),
                os.path.join(local, 'Microsoft', 'WinGet', 'Links',
                             'codex.exe')]
    places = [os.path.join(home, '.local', 'bin', 'codex'),
              os.path.join(home, '.npm-global', 'bin', 'codex'),
              os.path.join(home, '.volta', 'bin', 'codex'),
              os.path.join(home, '.bun', 'bin', 'codex'),
              '/opt/homebrew/bin/codex', '/usr/local/bin/codex',
              '/usr/bin/codex']
    # npm under nvm, newest node first.
    places += sorted(glob.glob(os.path.join(
        home, '.nvm', 'versions', 'node', '*', 'bin', 'codex')),
        reverse=True)
    return places


def _native(package):
    """Codex's own program inside an npm install of it, or None."""
    name = 'codex.exe' if sys.platform == 'win32' else 'codex'
    # The program comes in a package of its own (codex-linux-x64 and so
    # on), inside the codex package or beside it, or in older versions in
    # the codex package itself.
    vendors = [os.path.join(package, 'vendor')]
    for top in (os.path.join(package, 'node_modules', '@openai'),
                os.path.dirname(package)):
        if os.path.isdir(top):
            vendors += [os.path.join(top, entry, 'vendor')
                        for entry in sorted(os.listdir(top))
                        if entry.startswith('codex-')]
    for vendor in vendors:
        for root, _dirs, files in os.walk(vendor):
            if name in files:
                found = os.path.join(root, name)
                if os.access(found, os.X_OK):
                    return found
    return None


def _unwrap(found):
    """npm installs codex as a node script (codex.cmd on Windows). A host
    may not have node on its PATH, and cmd.exe mangles the arguments, so
    the program the script runs is used when it can be found."""
    real = os.path.realpath(found)
    package = None
    if found.lower().endswith('.cmd'):
        package = os.path.join(os.path.dirname(found), 'node_modules',
                               '@openai', 'codex')
    elif real.endswith('.js'):
        # .../node_modules/@openai/codex/bin/codex.js
        package = os.path.dirname(os.path.dirname(real))
    if package:
        return _native(package) or found
    return found


def find_cli():
    """The codex command, or None when Codex is not installed."""
    chosen = user_dir.user_prefs.get(user_dir.USER_PREF.AI_CODEX_PATH)
    if chosen and os.path.isfile(chosen):
        return _unwrap(chosen)
    found = shutil.which('codex')
    if found:
        return _unwrap(found)
    for path in _install_places():
        if os.path.isfile(path):
            return _unwrap(path)
    return None


def _child_env(token=None):
    env = dict(os.environ)
    # Otherwise Codex would bill these instead of the sign in.
    for name in ('CODEX_API_KEY', 'OPENAI_API_KEY'):
        env.pop(name, None)
    if token:
        env[TOKEN_VAR] = token
    return env


def _run(cli, args, timeout=20):
    return subprocess.run([cli] + args, capture_output=True, text=True,
                          encoding='utf-8', errors='replace',
                          timeout=timeout, env=_child_env(),
                          stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)


def _codex_home():
    return os.environ.get('CODEX_HOME') or os.path.join(
        os.path.expanduser('~'), '.codex')


def _account():
    """Who Codex is signed in as, from its auth file, if it keeps one."""
    path = os.path.join(_codex_home(), 'auth.json')
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        token = (data.get('tokens') or {}).get('id_token') or ''
        if isinstance(token, dict):
            token = token.get('raw_jwt') or ''
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload.encode()))
    except (OSError, ValueError, AttributeError, IndexError, TypeError):
        return {}
    auth = claims.get('https://api.openai.com/auth') or {}
    plan = auth.get('chatgpt_plan_type')
    return {'email': claims.get('email'),
            'plan': PLANS.get(plan, plan.title() if plan else None)}


_status = {'at': 0, 'value': None}
_status_lock = threading.Lock()


def status(cli=None, cached=True):
    """What `codex login status` says, as a dict, or None when Codex is
    not installed or did not answer."""
    with _status_lock:
        if cached and time.time() - _status['at'] < STATUS_LIFE:
            return _status['value']
    cli = cli or find_cli()
    value = None
    if cli:
        try:
            result = _run(cli, ['login', 'status'])
            said = (result.stdout + '\n' + result.stderr).strip()
            lines = [l for l in said.splitlines()
                     if l.strip() and not l.startswith('WARNING')]
            text = lines[-1].strip() if lines else ''
            value = {'logged_in': (result.returncode == 0 and
                                   text.lower().startswith('logged in')),
                     'text': text}
        except (OSError, subprocess.TimeoutExpired) as err:
            logger.debug('Codex did not say who is signed in: '
                         '{}'.format(err))
    with _status_lock:
        _status['at'] = time.time()
        _status['value'] = value
    return value


def forget_status(older_than=0):
    """Ask Codex again next time, if what it said is older than older_than
    seconds."""
    with _status_lock:
        if time.time() - _status['at'] >= older_than:
            _status['at'] = 0


def signed_in(cli=None, cached=True):
    """Who Codex is signed in as, as a record, or None."""
    found = status(cli, cached=cached)
    if not found or not found.get('logged_in'):
        return None
    record = {'auth_method': ('api key' if 'api key' in
                              found['text'].lower() else 'chatgpt')}
    if record['auth_method'] == 'chatgpt':
        record.update(_account())
    return record


def list_models(cli=None):
    """The models Codex offers, in its own order."""
    cli = cli or find_cli()
    if not cli:
        raise CodexError('Codex is not installed.')
    try:
        result = _run(cli, ['debug', 'models'], timeout=30)
        data = json.loads(result.stdout)
    except (OSError, ValueError, TypeError,
            subprocess.TimeoutExpired) as err:
        raise CodexError('Codex did not list its models: {}'.format(err))
    models = [m for m in data.get('models', [])
              if m.get('visibility', 'list') == 'list' and m.get('slug')]
    models.sort(key=lambda m: m.get('priority', 1000))
    return [m['slug'] for m in models]


_URL = re.compile(r'https://[^\s\x1b]+')
_COLOR = re.compile(r'\x1b\[[0-9;]*m')


class Login(object):
    """`codex login`, run without a window. Codex opens the browser itself
    and waits for it on this computer."""

    def __init__(self, cli=None, popen=subprocess.Popen):
        cli = cli or find_cli()
        if not cli:
            raise CodexError('Codex is not installed.')
        forget_status()
        self.url = None
        self.output = []
        self.got_url = threading.Event()
        self.process = popen([cli, 'login'], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, env=_child_env(),
                             creationflags=_NO_WINDOW)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        for raw in self.process.stdout:
            line = _COLOR.sub('', raw.decode('utf-8', 'replace')).strip()
            self.output.append(line)
            found = _URL.search(line)
            if found and not self.url and 'auth' in found.group(0):
                self.url = found.group(0)
                self.got_url.set()
        self.got_url.set()

    def wait(self, cancelled, timeout=900, interval=0.25, sleep=time.sleep):
        """Wait for the sign in to finish. Gives back who is signed in."""
        end = time.monotonic() + timeout
        while self.process.poll() is None:
            if cancelled.is_set():
                self.cancel()
                return None
            if time.monotonic() > end:
                self.cancel()
                raise CodexError('Gave up waiting for the ChatGPT sign in.')
            sleep(interval)
        forget_status()
        record = signed_in(cached=False)
        if self.process.returncode or not record:
            said = [l for l in self.output
                    if l and not _URL.search(l) and
                    not l.startswith('WARNING')]
            raise CodexError(_explain(said[-1]) if said else
                             'Codex did not sign in.')
        return record

    def cancel(self):
        if self.process.poll() is None:
            self.process.kill()


def logout(cli=None):
    cli = cli or find_cli()
    forget_status()
    if cli:
        _run(cli, ['logout'], timeout=30)


def _explain(message):
    """What Codex said went wrong, with what to do about it."""
    lower = message.lower()
    if '401' in lower or 'unauthorized' in lower or 'not logged in' in lower:
        return ('Codex is not signed in, or its sign in ran out. Sign in '
                'with Codex in Options > AI Assistant. ({})'.format(message))
    if 'address already in use' in lower or 'port' in lower and \
            'in use' in lower:
        return ('Another Codex sign in is already waiting. Finish or close '
                'it, then try again. ({})'.format(message))
    if '429' in lower or 'usage limit' in lower or 'rate limit' in lower:
        return ('Your ChatGPT plan has hit its Codex limit for now. Try '
                'again later. ({})'.format(message))
    return message


def as_prompt(messages):
    """codex exec takes one prompt, so earlier turns go in front of it."""
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
    # An empty folder of its own, so no project's AGENTS.md is picked up.
    path = os.path.join(user_dir.PREF_DIR, 'codex')
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def _toml(value):
    """A value for codex -c, which reads TOML."""
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def exec_args(cli, system_file, model=None, mcp_url=None, extra=None):
    """The codex exec command for one reply."""
    config = {'approval_policy': 'never', 'web_search': 'disabled',
              'model_instructions_file': system_file,
              'history.persistence': 'none'}
    for feature in OWN_TOOLS_OFF:
        config['features.' + feature] = False
    if mcp_url:
        prefix = 'mcp_servers.{}.'.format(mcp_server.NAME)
        config[prefix + 'url'] = mcp_url
        config[prefix + 'bearer_token_env_var'] = TOKEN_VAR
        config[prefix + 'default_tools_approval_mode'] = 'approve'
        config[prefix + 'tool_timeout_sec'] = 600
    config.update(extra or {})
    args = [cli, 'exec', '--json', '--skip-git-repo-check', '--ephemeral',
            '--ignore-user-config', '--ignore-rules', '--sandbox',
            'read-only', '--color', 'never']
    for key, value in config.items():
        args += ['-c', '{}={}'.format(key, _toml(value))]
    if model:
        args += ['--model', model]
    # The prompt comes on stdin.
    args.append('-')
    return args


def stream_chat(messages, system, model=None, cli=None, tools=None,
                popen=subprocess.Popen, extra=None):
    """Yield Codex's reply a piece at a time, from codex exec.

    :param tools: a tools.Toolbox. Its tools are served to Codex by the
        editor's MCP server, and are the only tools it gets.
    """
    cli = cli or find_cli()
    if not cli:
        raise CodexError('Codex is not installed.')
    handle, system_file = tempfile.mkstemp(prefix='nxt_ai_', suffix='.md')
    with os.fdopen(handle, 'w', encoding='utf-8') as f:
        f.write(system)
    server = token = None
    mcp_url = None
    if tools is not None and tools.available():
        server = mcp_server.server()
        token = server.open(tools)
        mcp_url = server.url
    args = exec_args(cli, system_file, model=model, mcp_url=mcp_url,
                     extra=extra)
    process = None
    errors = []
    try:
        with tempfile.TemporaryFile() as stderr:
            process = popen(args, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=stderr,
                            cwd=_work_dir(), env=_child_env(token),
                            creationflags=_NO_WINDOW)
            process.stdin.write(as_prompt(messages).encode('utf-8'))
            process.stdin.close()
            said = False
            # Text so far of each message, by id, for ones that grow.
            texts = {}
            for raw in process.stdout:
                try:
                    data = json.loads(raw.decode('utf-8'))
                except ValueError:
                    continue
                kind = data.get('type')
                item = data.get('item') or {}
                if (kind in ('item.updated', 'item.completed') and
                        item.get('type') == 'agent_message'):
                    text = item.get('text') or ''
                    key = item.get('id')
                    before = texts.get(key, '')
                    if text.startswith(before) and len(text) > len(before):
                        if not before and said:
                            yield '\n\n'
                        yield text[len(before):]
                        said = True
                        texts[key] = text
                elif kind == 'error':
                    errors.append(data.get('message') or '')
                elif kind == 'turn.failed':
                    error = data.get('error') or {}
                    raise CodexError(_explain(
                        error.get('message') or 'Codex stopped with an '
                        'error.'))
                elif kind == 'turn.completed':
                    return
            process.wait(30)
            stderr.seek(0)
            said_err = stderr.read().decode('utf-8', 'replace').strip()
        lines = [l for l in said_err.splitlines()
                 if l.strip() and 'WARN' not in l]
        last = (errors[-1] if errors else lines[-1] if lines else
                'Codex stopped without answering.')
        raise CodexError(_explain(last))
    finally:
        if process is not None and process.poll() is None:
            process.kill()
        if token:
            server.close(token)
        try:
            os.remove(system_file)
        except OSError:
            pass
