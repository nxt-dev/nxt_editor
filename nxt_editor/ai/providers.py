"""The AI providers the assistant can talk to, and how each is signed in.

Each provider can use a sign in from the web browser or an API key, and
falls back to the usual environment variable. Sign ins and keys are kept
in the operating system's secure store (see secret_store), everything
else in the user prefs.
"""
# Builtin
import logging
import os
import threading
import time

# Internal
import nxt_editor
from nxt_editor import user_dir
from nxt_editor.ai import claude_code, secret_store, signin, web

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

WEB = 'web'
KEY = 'key'
ENV = 'env'


class AuthError(Exception):
    pass


class Auth(object):
    """What a request is sent with."""
    def __init__(self, kind, token, label):
        self.kind = kind
        self.token = token
        self.label = label


# The models each provider offered last, so the panel and the settings
# do not both ask.
_models = {}


class Provider(object):
    id = None
    label = None
    env_var = None
    # Where a user makes an API key.
    keys_url = None
    # True when the provider's own sign in can be used from the editor.
    # Otherwise "Sign in on the web" opens keys_url.
    web_sign_in = False
    web_plan = None
    max_tokens = 8192

    def __init__(self, store=None, prefs=None):
        self._store = store
        self._prefs = prefs

    @property
    def store(self):
        return self._store or secret_store.get_store()

    @property
    def prefs(self):
        return self._prefs if self._prefs is not None else user_dir.user_prefs

    # Saved credentials
    @property
    def _key_name(self):
        return '{}.api_key'.format(self.id)

    @property
    def _web_name(self):
        return '{}.web'.format(self.id)

    def saved_api_key(self):
        record = self.store.get(self._key_name)
        return (record or {}).get('api_key')

    def save_api_key(self, api_key):
        api_key = (api_key or '').strip()
        if not api_key:
            self.store.delete(self._key_name)
            return
        self.store.set(self._key_name, {'api_key': api_key})
        self.method = KEY
        self.forget_models()

    def remove_api_key(self):
        self.store.delete(self._key_name)
        self.forget_models()

    def web_record(self):
        if not self.web_sign_in:
            return None
        return self.store.get(self._web_name)

    def save_web_record(self, record):
        self.store.set(self._web_name, record)
        self.method = WEB
        self.forget_models()

    def sign_out(self):
        record = self.web_record()
        self.store.delete(self._web_name)
        self.forget_models()
        if record:
            self._revoke(record)

    def _revoke(self, record):
        pass

    def env_api_key(self):
        if not self.env_var:
            return None
        return os.environ.get(self.env_var) or None

    # Which one is used
    def _pref_dict(self, key):
        value = self.prefs.get(key, {})
        return value if isinstance(value, dict) else {}

    def _set_pref_dict(self, key, name, value):
        data = self._pref_dict(key)
        data[name] = value
        self.prefs[key] = data

    @property
    def method(self):
        return self._pref_dict(user_dir.USER_PREF.AI_AUTH).get(self.id)

    @method.setter
    def method(self, value):
        if value != self.method:
            self.forget_models()
        self._set_pref_dict(user_dir.USER_PREF.AI_AUTH, self.id, value)

    @property
    def model(self):
        return self._pref_dict(user_dir.USER_PREF.AI_MODELS).get(self.id, '')

    @model.setter
    def model(self, value):
        self._set_pref_dict(user_dir.USER_PREF.AI_MODELS, self.id, value)

    def auth(self):
        """How to send a request now, or None when nothing is set up.

        The chosen way is tried first, then the other, then the environment
        variable. A web sign in about to run out is refreshed.
        """
        order = [WEB, KEY] if self.method != KEY else [KEY, WEB]
        for kind in order:
            if kind == WEB:
                record = self.web_record()
                if record:
                    record = self._fresh(record)
                    return Auth(WEB, record.get('access_token'),
                                self.web_label(record))
            else:
                api_key = self.saved_api_key()
                if api_key:
                    return Auth(KEY, api_key, 'saved API key')
        api_key = self.env_api_key()
        if api_key:
            return Auth(ENV, api_key, '{} from the environment'.format(
                self.env_var))
        return None

    def web_label(self, record):
        return '{} sign in ({})'.format(
            self.web_plan, record.get('email') or 'your account')

    def _refresh(self, record):
        raise NotImplementedError

    def _fresh(self, record):
        if record.get('expires_at', 0) - 120 > time.time():
            return record
        if not record.get('refresh_token'):
            raise AuthError('Your {} sign in ran out. Sign in again in '
                            'Options > AI Assistant.'.format(self.label))
        try:
            record = self._refresh(record)
        except web.WebError as err:
            if err.status in (400, 401, 403):
                raise AuthError('Your {} sign in ran out. Sign in again in '
                                'Options > AI Assistant.'.format(self.label))
            raise
        self.store.set(self._web_name, record)
        return record

    def status(self):
        """One line on how this provider is set up. Asks nothing of the
        network, unlike auth()."""
        record = self.web_record()
        web_label = self.web_label(record) if record else None
        key_label = 'saved API key' if self.saved_api_key() else None
        order = ([key_label, web_label] if self.method == KEY
                 else [web_label, key_label])
        for label in order:
            if label:
                return 'Using your {}.'.format(label)
        if self.env_api_key():
            return 'Using {} from the environment.'.format(self.env_var)
        return 'Not set up.'

    # Requests
    def _require_auth(self, auth):
        auth = auth or self.auth()
        if not auth:
            raise AuthError('{} is not set up. Sign in or add an API key in '
                            'Options > AI Assistant.'.format(self.label))
        return auth

    def list_models(self, auth=None):
        """The model ids to choose from, newest first."""
        raise NotImplementedError

    def models(self, refresh=False):
        """The models this provider offers now, asked for once."""
        if not refresh and self.id in _models:
            return list(_models[self.id])
        found = self.list_models()
        _models[self.id] = list(found)
        return found

    def cached_models(self):
        """The models from the last time they were asked for, or None."""
        found = _models.get(self.id)
        return list(found) if found is not None else None

    def forget_models(self):
        """Called when what the provider is signed in with changes."""
        _models.pop(self.id, None)

    def choose_model(self, models):
        """The saved model if it is offered, otherwise the first one."""
        if self.model in models:
            return self.model
        return models[0] if models else ''

    def stream_chat(self, messages, system, model=None, auth=None):
        """Yield the reply a piece at a time.

        :param messages: [{'role': 'user' or 'assistant', 'content': str}]
        :param system: Instructions for the model.
        """
        raise NotImplementedError

    @staticmethod
    def _newest_first(models):
        return [m['id'] for m in sorted(
            models, key=lambda m: m.get('created') or 0, reverse=True)]


class Anthropic(Provider):
    """Claude, through the user's own Claude Code sign in or an API key.

    Anthropic has no sign in for other apps, so a signed in Claude account
    is used by running Claude Code (see claude_code), which signs in
    itself.
    """
    id = 'anthropic'
    label = 'Claude'
    env_var = 'ANTHROPIC_API_KEY'
    keys_url = 'https://console.anthropic.com/settings/keys'
    web_sign_in = True
    web_plan = 'Claude Code'
    API = 'https://api.anthropic.com/v1'
    VERSION = '2023-06-01'

    @property
    def cli(self):
        return claude_code.find_cli()

    def web_record(self):
        if not self.cli:
            return None
        return claude_code.signed_in(self.cli)

    def save_web_record(self, record):
        self.method = WEB
        self.forget_models()

    def web_label(self, record):
        who = record.get('email') or 'your account'
        if record.get('plan'):
            who = '{}, {} plan'.format(who, record['plan'])
        return 'Claude Code sign in ({})'.format(who)

    def _fresh(self, record):
        # Claude Code keeps its own sign in fresh.
        return record

    def start_sign_in(self):
        """Sign Claude Code in, or switch its account. Opens the browser.
        Gives back the Login to wait on."""
        return claude_code.Login(self.cli)

    def finish_sign_in(self, login, cancelled=None):
        record = login.wait(cancelled or threading.Event())
        if record:
            self.method = WEB
        return record

    def sign_out(self):
        claude_code.logout(self.cli)
        self.forget_models()

    def _headers(self, auth):
        return {'x-api-key': auth.token, 'anthropic-version': self.VERSION}

    def list_models(self, auth=None):
        auth = self._require_auth(auth)
        if auth.kind == WEB:
            return list(claude_code.MODELS)
        data = web.get_json(self.API + '/models?limit=100',
                            headers=self._headers(auth))
        # Already newest first.
        return [m['id'] for m in data.get('data', [])]

    def _newest(self, alias, auth):
        """The API's newest model for a Claude Code alias like opus."""
        for model_id in self.list_models(auth):
            if alias in model_id:
                return model_id
        return alias

    def stream_chat(self, messages, system, model=None, auth=None):
        auth = self._require_auth(auth)
        if auth.kind == WEB:
            for text in claude_code.stream_chat(messages, system,
                                                model=model or self.model,
                                                cli=self.cli):
                yield text
            return
        model = model or self.model
        if model in claude_code.MODELS:
            model = self._newest(model, auth)
        body = {'model': model, 'max_tokens': self.max_tokens,
                'system': system, 'messages': messages, 'stream': True}
        with web.request(self.API + '/messages', data=body,
                         headers=self._headers(auth)) as response:
            for event, data in web.iter_sse(response):
                if not isinstance(data, dict):
                    continue
                kind = data.get('type', event)
                if kind == 'content_block_delta':
                    delta = data.get('delta', {})
                    if delta.get('type') == 'text_delta':
                        yield delta.get('text', '')
                elif kind == 'error':
                    raise web.WebError(data.get('error', {}).get(
                        'message', 'Claude stopped with an error.'))
                elif kind == 'message_stop':
                    return


class OpenAI(Provider):
    id = 'openai'
    label = 'OpenAI'
    env_var = 'OPENAI_API_KEY'
    keys_url = 'https://platform.openai.com/api-keys'
    web_sign_in = True
    web_plan = 'ChatGPT'
    API = 'https://api.openai.com/v1'
    # Not chat models.
    SKIP = ('embedding', 'tts', 'whisper', 'dall-e', 'moderation', 'image',
            'audio', 'realtime', 'transcribe', 'search', 'babbage',
            'davinci', 'sora')

    @property
    def host_id(self):
        """Who this computer is to Sign in with ChatGPT; made once."""
        key = user_dir.USER_PREF.AI_OPENAI_HOST_ID
        host_id = self.prefs.get(key)
        if not host_id:
            host_id = signin.OpenAI.new_host_id()
            self.prefs[key] = host_id
        return host_id

    def sign_in(self, open_browser, cancelled=None):
        previous = self.store.get(self._web_name) or {}
        client_id = previous.get('client_id') or self.prefs.get(
            user_dir.USER_PREF.AI_OPENAI_CLIENT_ID)
        record = signin.OpenAI.sign_in(open_browser, self.host_id,
                                       client_id=client_id,
                                       cancelled=cancelled)
        # Kept apart from the sign in, so signing in again reuses it.
        self.prefs[user_dir.USER_PREF.AI_OPENAI_CLIENT_ID] = \
            record['client_id']
        self.save_web_record(record)
        return record

    def _refresh(self, record):
        return signin.OpenAI.refresh(record)

    def _revoke(self, record):
        signin.OpenAI.sign_out(record)

    def _headers(self, auth):
        return {'Authorization': 'Bearer ' + auth.token}

    def list_models(self, auth=None):
        auth = self._require_auth(auth)
        data = web.get_json(self.API + '/models', headers=self._headers(auth))
        models = data.get('data', [])
        if any('visibility' in m for m in models):
            models = [m for m in models if m.get('visibility') == 'list']
        models = [m for m in models
                  if not any(s in m['id'] for s in self.SKIP)]
        return self._newest_first(models)

    def stream_chat(self, messages, system, model=None, auth=None):
        auth = self._require_auth(auth)
        # A ChatGPT plan needs stream on and store off; both suit an API
        # key as well.
        body = {'model': model or self.model, 'instructions': system,
                'input': messages, 'stream': True, 'store': False}
        with web.request(self.API + '/responses', data=body,
                         headers=self._headers(auth)) as response:
            for event, data in web.iter_sse(response):
                if not isinstance(data, dict):
                    continue
                kind = data.get('type', event)
                if kind == 'response.output_text.delta':
                    yield data.get('delta', '')
                elif kind == 'response.failed':
                    error = (data.get('response') or {}).get('error') or {}
                    raise web.WebError(error.get('message') or
                                       'OpenAI stopped with an error.',
                                       code=error.get('code'))
                elif kind == 'error':
                    raise web.WebError(data.get('message') or
                                       'OpenAI stopped with an error.',
                                       code=data.get('code'))
                elif kind == 'response.completed':
                    return


class XAI(Provider):
    id = 'xai'
    label = 'Grok'
    env_var = 'XAI_API_KEY'
    keys_url = 'https://console.x.ai'
    web_sign_in = True
    web_plan = 'SuperGrok'
    API = 'https://api.x.ai/v1'

    def start_sign_in(self):
        return signin.XAI.start()

    def finish_sign_in(self, device, cancelled=None):
        record = signin.XAI.wait(device, cancelled=cancelled)
        self.save_web_record(record)
        return record

    def _refresh(self, record):
        return signin.XAI.refresh(record)

    def _headers(self, auth):
        return {'Authorization': 'Bearer ' + auth.token}

    def list_models(self, auth=None):
        auth = self._require_auth(auth)
        data = web.get_json(self.API + '/models', headers=self._headers(auth))
        models = [m for m in data.get('data', [])
                  if 'image' not in m['id'] and 'video' not in m['id']]
        return self._newest_first(models)

    def stream_chat(self, messages, system, model=None, auth=None):
        auth = self._require_auth(auth)
        for text in stream_chat_completions(
                self.API, self._headers(auth), model or self.model,
                messages, system, self.label):
            yield text


def stream_chat_completions(api, headers, model, messages, system, label,
                            timeout=web.TIMEOUT):
    """Stream from an OpenAI style /chat/completions, which xAI and every
    local server speak."""
    body = {'model': model, 'stream': True,
            'messages': [{'role': 'system', 'content': system}] +
            list(messages)}
    with web.request(api + '/chat/completions', data=body, headers=headers,
                     timeout=timeout) as response:
        for event, data in web.iter_sse(response):
            if data == '[DONE]':
                return
            if not isinstance(data, dict):
                continue
            if data.get('error'):
                error = data['error']
                message = (error.get('message') if isinstance(error, dict)
                           else str(error))
                raise web.WebError(message or '{} stopped with an '
                                   'error.'.format(label))
            for choice in data.get('choices', []):
                text = (choice.get('delta') or {}).get('content')
                if text:
                    yield text


class Local(Provider):
    """A model running on this computer or the local network.

    Ollama, LM Studio, llama.cpp, vLLM and Jan all serve the same OpenAI
    style API, so one provider covers them: only the server address
    changes. Nothing leaves the computer unless the address is elsewhere.
    """
    id = 'local'
    label = 'Local Model'
    env_var = None
    keys_url = None
    # Where each one listens unless told otherwise.
    KNOWN_SERVERS = (('Ollama', 'http://localhost:11434/v1'),
                     ('LM Studio', 'http://localhost:1234/v1'),
                     ('llama.cpp', 'http://localhost:8080/v1'),
                     ('vLLM', 'http://localhost:8000/v1'),
                     ('Jan', 'http://localhost:1337/v1'))
    # Local models can take a while to load and to answer.
    TIMEOUT = 600

    @property
    def base_url(self):
        return (self.prefs.get(user_dir.USER_PREF.AI_LOCAL_URL) or
                '').strip().rstrip('/')

    @base_url.setter
    def base_url(self, url):
        url = (url or '').strip().rstrip('/')
        if url and '://' not in url:
            url = 'http://' + url
        if url and not url.endswith('/v1'):
            url += '/v1'
        if url != self.base_url:
            self.forget_models()
        self.prefs[user_dir.USER_PREF.AI_LOCAL_URL] = url

    def auth(self):
        if not self.base_url:
            return None
        # Most local servers need no key; some are set up to want one.
        return Auth(KEY, self.saved_api_key(),
                    'local server at {}'.format(self.base_url))

    def status(self):
        if not self.base_url:
            return 'Not set up.'
        return 'Using the local server at {}.'.format(self.base_url)

    def _headers(self, auth):
        if auth and auth.token:
            return {'Authorization': 'Bearer ' + auth.token}
        return {}

    def _require_auth(self, auth):
        auth = auth or self.auth()
        if not auth:
            raise AuthError('Choose a local server in Options > AI '
                            'Assistant.')
        return auth

    def list_models(self, auth=None):
        auth = self._require_auth(auth)
        data = web.get_json(self.base_url + '/models',
                            headers=self._headers(auth), timeout=10)
        return [m['id'] for m in data.get('data', [])]

    def stream_chat(self, messages, system, model=None, auth=None):
        auth = self._require_auth(auth)
        for text in stream_chat_completions(
                self.base_url, self._headers(auth), model or self.model,
                messages, system, self.label, timeout=self.TIMEOUT):
            yield text

    @classmethod
    def find_servers(cls, timeout=1.0):
        """The known local servers that are running, as (name, url,
        models)."""
        found = []
        for name, url in cls.KNOWN_SERVERS:
            try:
                data = web.get_json(url + '/models', timeout=timeout)
            except (web.WebError, ValueError, OSError):
                continue
            found.append((name, url,
                          [m['id'] for m in data.get('data', [])]))
        return found


PROVIDERS = (Anthropic, OpenAI, XAI, Local)


def get_providers(store=None, prefs=None):
    return [cls(store=store, prefs=prefs) for cls in PROVIDERS]


def get_provider(provider_id, store=None, prefs=None):
    for cls in PROVIDERS:
        if cls.id == provider_id:
            return cls(store=store, prefs=prefs)
    return None


def is_enabled(prefs=None):
    prefs = prefs if prefs is not None else user_dir.user_prefs
    return bool(prefs.get(user_dir.USER_PREF.AI_ENABLED, False))
