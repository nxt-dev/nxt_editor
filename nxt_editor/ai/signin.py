"""Signing in to a provider in the web browser.

OpenAI: Sign in with ChatGPT, for open source apps. The browser comes
back to a listener on 127.0.0.1, and the first sign in registers this
editor with the user's account. Requests then count against their
ChatGPT plan.
https://developers.openai.com/siwc/token-sharing-open-source

xAI: the device code sign in. The user approves a short code on
accounts.x.ai and the editor waits for that. Requests then count against
their SuperGrok plan.

Anthropic has no sign in for other apps; a Claude account can only be
used in Anthropic's own apps. For Claude the browser opens the Console,
where an API key is made.
"""
# Builtin
import base64
import hashlib
import json
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

# Internal
from nxt_editor.ai import web


class SignInError(Exception):
    pass


class Cancelled(SignInError):
    def __init__(self):
        super(Cancelled, self).__init__('Sign in was cancelled.')


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def pkce_pair():
    """A PKCE verifier and its S256 challenge."""
    verifier = _b64url(os.urandom(48))
    challenge = _b64url(hashlib.sha256(verifier.encode('ascii')).digest())
    return verifier, challenge


def jwt_claims(token):
    """The claims in a JWT, unchecked. Only used to show who signed in."""
    try:
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload.encode('ascii')))
    except (AttributeError, IndexError, ValueError):
        return {}


def _expires_at(token_data):
    return time.time() + float(token_data.get('expires_in') or 3600)


_PAGE = ('<!doctype html><meta charset="utf-8"><title>nxt</title>'
         '<body style="font-family:sans-serif;padding:3em">'
         '<h2>{}</h2></body>')
DONE_PAGE = _PAGE.format('You can close this tab and go back to nxt.'
                         ).encode('utf-8')
FAILED_PAGE = _PAGE.format('The sign in did not finish. Go back to nxt to '
                           'see why.').encode('utf-8')

# What OpenAI's sign in errors mean, said plainly.
_OPENAI_ERRORS = {
    'access_denied': 'The sign in was turned down in the browser, so nxt '
                     'can not use your ChatGPT plan. Sign in again and '
                     'allow it, or use an API key.',
    'invalid_grant': 'OpenAI did not accept the sign in code. Codes only '
                     'work once and run out quickly, so press Sign in '
                     'again.',
    'invalid_client': 'OpenAI does not know this copy of nxt any more. '
                      'Press Sign in again to register it again.',
    'invalid_request': 'OpenAI turned down the sign in request.',
    'invalid_scope': 'OpenAI would not share your ChatGPT plan with nxt. '
                     'Your plan or workspace may not allow it. Use an API '
                     'key instead.',
    'unauthorized_client': 'OpenAI would not share your ChatGPT plan with '
                           'nxt. Your plan or workspace may not allow it. '
                           'Use an API key instead.',
    'temporarily_unavailable': 'OpenAI sign in is busy right now. Try '
                               'again in a minute.',
    'server_error': 'OpenAI sign in had a problem on its side. Try again '
                    'in a minute.',
}


def explain_openai_error(code, detail=None):
    """A sign in error from OpenAI, as something to tell the user."""
    message = _OPENAI_ERRORS.get(code)
    if not message:
        return detail or code or 'The sign in did not finish.'
    if detail and detail != code:
        message = '{} ({})'.format(message, detail)
    return message


class _CallbackHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path != self.server.callback_path:
            self.send_response(404)
            self.end_headers()
            return
        query = urllib.parse.parse_qs(url.query)
        result = {k: v[0] for k, v in query.items()}
        self.server.result = result
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(FAILED_PAGE if result.get('error') else DONE_PAGE)

    def log_message(self, *args):
        pass


class LoopbackListener(object):
    """Waits for the browser to come back to http://127.0.0.1:<port>/..."""

    def __init__(self, path='/auth/callback'):
        self.server = HTTPServer(('127.0.0.1', 0), _CallbackHandler)
        self.server.callback_path = path
        self.server.result = None
        self.server.timeout = 0.25
        self.redirect_uri = 'http://127.0.0.1:{}{}'.format(
            self.server.server_address[1], path)

    def wait(self, cancelled, timeout=600):
        end = time.monotonic() + timeout
        try:
            while self.server.result is None:
                if cancelled.is_set():
                    raise Cancelled()
                if time.monotonic() > end:
                    raise SignInError('Gave up waiting for the browser. '
                                      'Press Sign in to try again.')
                self.server.handle_request()
            return self.server.result
        finally:
            self.server.server_close()


class OpenAI(object):
    ISSUER = 'https://auth.openai.com'
    AUTHORIZE_URL = ISSUER + '/api/accounts/authorize'
    TOKEN_URL = ISSUER + '/api/accounts/oauth/token'
    DISCOVERY_URL = ISSUER + '/.well-known/openid-configuration'
    RESOURCE = 'https://api.openai.com/v1'
    REGISTER_CLIENT = 'dynamic_agent_client'
    PLAN_SCOPE = 'chatgpt.tokens.use.direct'
    SCOPE = ('openid profile email offline_access resource.invoke ' +
             PLAN_SCOPE)
    APP_NAME = 'nxt editor'
    # OpenAI only takes this path back; the port may change.
    CALLBACK_PATH = '/auth/callback'

    @classmethod
    def new_host_id(cls):
        return 'urn:uuid:{}'.format(
            '-'.join([os.urandom(n).hex() for n in (4, 2, 2, 2, 6)]))

    @classmethod
    def sign_in(cls, open_browser, host_id, client_id=None, cancelled=None,
                listener=None, timeout=600, previous=None,
                on_client_id=None):
        """Sign in with ChatGPT in the browser. Gives back the record to
        save.

        :param open_browser: Called with the URL to open.
        :param host_id: This computer's ext_agent_host_id, kept in prefs.
        :param client_id: The client_id OpenAI gave this editor last time.
        :param previous: The last sign in with that client, if any, so the
            browser can go straight to the same account.
        :param on_client_id: Called with a newly issued client_id as soon as
            OpenAI gives it, so it is kept even if the rest fails.
        """
        cancelled = cancelled or threading.Event()
        listener = listener or LoopbackListener(cls.CALLBACK_PATH)
        verifier, challenge = pkce_pair()
        state = _b64url(os.urandom(24))
        nonce = _b64url(os.urandom(24))
        params = {
            'client_id': client_id or cls.REGISTER_CLIENT,
            'ext_agent_host_id': host_id,
            'response_type': 'code',
            'redirect_uri': listener.redirect_uri,
            'scope': cls.SCOPE,
            'resource': cls.RESOURCE,
            'state': state,
            'nonce': nonce,
            'code_challenge_method': 'S256',
            'code_challenge': challenge,
        }
        if not client_id:
            params['agent_name_hint'] = cls.APP_NAME
        elif previous:
            # Goes straight back to the account signed in last time.
            if previous.get('id_token'):
                params['id_token_hint'] = previous['id_token']
            if previous.get('email'):
                params['login_hint'] = previous['email']
        open_browser(cls.AUTHORIZE_URL + '?' +
                     urllib.parse.urlencode(params))
        answer = listener.wait(cancelled, timeout=timeout)
        if answer.get('state') != state:
            raise SignInError('The browser answered a different sign in. '
                              'Try again.')
        if answer.get('error'):
            raise SignInError(explain_openai_error(
                answer['error'], answer.get('error_description')))
        if not answer.get('code'):
            raise SignInError('OpenAI did not finish the sign in. Try '
                              'again.')
        issued = answer.get('client_id')
        if client_id and issued and issued != client_id:
            raise SignInError('OpenAI answered for a different registration '
                              'of nxt. Try again.')
        if issued and not client_id:
            client_id = issued
            if on_client_id:
                on_client_id(client_id)
        if not client_id:
            raise SignInError('OpenAI did not register the editor. Try '
                              'again.')
        try:
            tokens = web.post_json(cls.TOKEN_URL, form={
                'grant_type': 'authorization_code',
                'client_id': client_id,
                'code': answer['code'],
                'code_verifier': verifier,
                'redirect_uri': listener.redirect_uri,
                'resource': cls.RESOURCE,
            })
        except web.WebError as err:
            if err.code in _OPENAI_ERRORS:
                raise SignInError(explain_openai_error(err.code))
            raise SignInError('OpenAI did not finish the sign in: '
                              '{}'.format(err))
        if not tokens.get('access_token'):
            raise SignInError('OpenAI did not send back a sign in. Try '
                              'again.')
        claims = jwt_claims(tokens.get('id_token'))
        if claims.get('nonce') not in (None, nonce):
            raise SignInError('The sign in could not be checked. Try again.')
        scopes = (tokens.get('scope') or answer.get('scope') or '').replace(
            '+', ' ').split()
        if scopes and cls.PLAN_SCOPE not in scopes:
            raise SignInError('Your ChatGPT plan was not shared with the '
                              'editor. Sign in again and allow it, or use '
                              'an API key.')
        return {
            'client_id': client_id,
            'ext_agent_host_id': host_id,
            'email': claims.get('email'),
            'id_token': tokens.get('id_token'),
            'access_token': tokens['access_token'],
            'refresh_token': tokens.get('refresh_token'),
            'expires_at': _expires_at(tokens),
            'scopes': scopes,
        }

    @classmethod
    def refresh(cls, record):
        tokens = web.post_json(cls.TOKEN_URL, form={
            'grant_type': 'refresh_token',
            'client_id': record['client_id'],
            'refresh_token': record['refresh_token'],
            'resource': cls.RESOURCE,
        })
        record = dict(record)
        record['access_token'] = tokens['access_token']
        record['refresh_token'] = (tokens.get('refresh_token') or
                                   record['refresh_token'])
        if tokens.get('id_token'):
            record['id_token'] = tokens['id_token']
        record['expires_at'] = _expires_at(tokens)
        return record

    @classmethod
    def sign_out(cls, record):
        """Tell OpenAI to forget the sign in. Best effort."""
        token = record.get('refresh_token')
        if not token:
            return
        try:
            config = web.get_json(cls.DISCOVERY_URL, timeout=10)
            url = config.get('revocation_endpoint')
            if url:
                web.post_json(url, form={'token': token,
                                         'token_type_hint': 'refresh_token',
                                         'client_id': record['client_id']},
                              timeout=10)
        except (web.WebError, ValueError):
            pass


class XAI(object):
    DEVICE_URL = 'https://auth.x.ai/oauth2/device/code'
    TOKEN_URL = 'https://auth.x.ai/oauth2/token'
    # The public client xAI's own Grok CLI signs in with. xAI has no way
    # for other apps to register one of their own yet.
    CLIENT_ID = 'b1a00492-073a-47ea-816f-4c329264a828'
    SCOPE = 'openid profile email offline_access api:access'
    DEVICE_GRANT = 'urn:ietf:params:oauth:grant-type:device_code'

    @classmethod
    def start(cls):
        """Ask for a code. The answer has user_code, verification_uri and
        verification_uri_complete for the user."""
        device = web.post_json(cls.DEVICE_URL, form={
            'client_id': cls.CLIENT_ID,
            'scope': cls.SCOPE,
            'referrer': 'nxt',
        })
        uri = device.get('verification_uri_complete') or device.get(
            'verification_uri') or ''
        if not uri.startswith('https://') or not device.get('device_code'):
            raise SignInError('xAI did not give a sign in code.')
        return device

    @classmethod
    def wait(cls, device, cancelled=None, sleep=time.sleep):
        """Wait for the user to approve the code. Gives back the record to
        save."""
        cancelled = cancelled or threading.Event()
        interval = float(device.get('interval') or 5)
        end = time.monotonic() + float(device.get('expires_in') or 900)
        while True:
            if cancelled.is_set():
                raise Cancelled()
            if time.monotonic() > end:
                raise SignInError('The code ran out. Sign in again.')
            try:
                tokens = web.post_json(cls.TOKEN_URL, form={
                    'grant_type': cls.DEVICE_GRANT,
                    'client_id': cls.CLIENT_ID,
                    'device_code': device['device_code'],
                })
            except web.WebError as err:
                if err.code == 'authorization_pending':
                    pass
                elif err.code == 'slow_down':
                    interval += 5
                elif err.code == 'access_denied':
                    raise SignInError('The sign in was turned down.')
                elif err.code == 'expired_token':
                    raise SignInError('The code ran out. Sign in again.')
                else:
                    raise SignInError(str(err))
            else:
                claims = jwt_claims(tokens.get('id_token'))
                return {
                    'email': claims.get('email'),
                    'access_token': tokens['access_token'],
                    'refresh_token': tokens.get('refresh_token'),
                    'expires_at': _expires_at(tokens),
                }
            # Sleep in short steps so Cancel is quick.
            waited = 0.0
            while waited < interval and not cancelled.is_set():
                sleep(0.25)
                waited += 0.25

    @classmethod
    def refresh(cls, record):
        tokens = web.post_json(cls.TOKEN_URL, form={
            'grant_type': 'refresh_token',
            'client_id': cls.CLIENT_ID,
            'refresh_token': record['refresh_token'],
        })
        record = dict(record)
        record['access_token'] = tokens['access_token']
        record['refresh_token'] = (tokens.get('refresh_token') or
                                   record['refresh_token'])
        record['expires_at'] = _expires_at(tokens)
        return record

    @classmethod
    def sign_out(cls, record):
        pass
