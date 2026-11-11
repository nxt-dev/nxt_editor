"""The opt in AI assistant: secure storage, signing in, providers and UI.

Nothing here reaches the network. Requests are caught and answered with
what each provider sends back.
"""
# Builtin
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest import mock

# External
from Qt import QtCore, QtWidgets

# Internal
from nxt_editor import user_dir
from nxt_editor.ai import (claude_code, codex, context, providers,
                           secret_store, signin, web)

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

PREF = user_dir.USER_PREF
REAL_FIND_CLI = claude_code.find_cli


def setUpModule():
    providers._models.clear()
    # Whether this computer has Claude Code or Codex is not up to the
    # tests.
    for module in (claude_code, codex):
        patcher = mock.patch.object(module, 'find_cli', return_value=None)
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)


class MemoryBackend(object):
    name = 'Memory'

    def __init__(self, max_size=None):
        self.max_size = max_size
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        if self.max_size:
            assert len(value) <= self.max_size + 64, 'Too long for backend'
        self.data[key] = value

    def delete(self, key):
        self.data.pop(key, None)


def memory_store(max_size=None):
    return secret_store.SecretStore(MemoryBackend(max_size))


def sse(*events):
    """A streamed response made of (event, data) pairs."""
    lines = []
    for event, data in events:
        if event:
            lines.append('event: {}\n'.format(event))
        if not isinstance(data, str):
            data = json.dumps(data)
        lines.append('data: {}\n'.format(data))
        lines.append('\n')
    return contextlib.closing(io.BytesIO(''.join(lines).encode('utf-8')))


class SecretStoreTests(unittest.TestCase):

    def test_a_record_comes_back(self):
        store = memory_store()
        store.set('anthropic.api_key', {'api_key': 'sk-1'})
        self.assertEqual({'api_key': 'sk-1'}, store.get('anthropic.api_key'))

    def test_a_long_record_is_split_and_put_back_together(self):
        store = memory_store(max_size=100)
        record = {'access_token': 'x' * 1000}
        store.set('openai.web', record)
        self.assertGreater(len(store.backend.data), 5)
        self.assertEqual(record, store.get('openai.web'))
        store.set('openai.web', {'small': True})
        self.assertEqual({'small': True}, store.get('openai.web'))
        self.assertEqual(1, len(store.backend.data))
        store.delete('openai.web')
        self.assertEqual({}, store.backend.data)

    def test_no_secure_storage_saves_nothing(self):
        store = secret_store.SecretStore(None)
        self.assertFalse(store.available)
        self.assertIsNone(store.get('anything'))
        with self.assertRaises(secret_store.SecretStoreError):
            store.set('anthropic.api_key', {'api_key': 'sk'})

    def test_the_mac_keychain_is_given_the_secret_on_stdin(self):
        backend = secret_store._MacBackend()
        with mock.patch.object(secret_store.subprocess, 'run') as run:
            run.return_value = mock.Mock(returncode=0, stderr='')
            backend.set('openai.api_key', 'sk-secret')
        args, kwargs = run.call_args
        self.assertEqual(['security', '-i'], args[0])
        self.assertNotIn('sk-secret', ' '.join(args[0]))
        self.assertIn('sk-secret'.encode('utf-8').hex(), kwargs['input'])

    def test_linux_is_given_the_secret_on_stdin(self):
        backend = secret_store._SecretToolBackend()
        with mock.patch.object(secret_store.subprocess, 'run') as run:
            run.return_value = mock.Mock(returncode=0, stderr='')
            backend.set('xai.api_key', 'xai-secret')
        args, kwargs = run.call_args
        self.assertEqual('secret-tool', args[0][0])
        self.assertNotIn('xai-secret', args[0])
        self.assertEqual('xai-secret', kwargs['input'])

    @unittest.skipUnless(sys.platform == 'win32', 'Windows only')
    def test_windows_credential_manager(self):
        store = secret_store.SecretStore(secret_store._WindowsBackend())
        record = {'access_token': 'y' * 6000}
        try:
            store.set('unittest.web', record)
            self.assertEqual(record, store.get('unittest.web'))
        finally:
            store.delete('unittest.web')
        self.assertIsNone(store.get('unittest.web'))


class ProviderAuthTests(unittest.TestCase):

    def setUp(self):
        self.store = memory_store()
        self.prefs = {}
        env = mock.patch.dict('os.environ', {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def provider(self, cls):
        return cls(store=self.store, prefs=self.prefs)

    def test_nothing_set_up(self):
        claude = self.provider(providers.Anthropic)
        self.assertIsNone(claude.auth())
        self.assertEqual('Not set up.', claude.status())
        with self.assertRaises(providers.AuthError):
            list(claude.stream_chat([], 'system', model='m'))

    def test_the_environment_variable_is_used_last(self):
        claude = self.provider(providers.Anthropic)
        with mock.patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'env-key'}):
            self.assertEqual(providers.ENV, claude.auth().kind)
            claude.save_api_key('saved-key')
            self.assertEqual('saved-key', claude.auth().token)

    def test_the_sign_in_is_used_before_a_key_unless_chosen(self):
        openai = self.provider(providers.OpenAI)
        openai.save_api_key('sk-key')
        openai.save_web_record({'access_token': 'web-token',
                                'refresh_token': 'r', 'email': 'a@b.c',
                                'expires_at': time.time() + 3600})
        self.assertEqual('web-token', openai.auth().token)
        self.assertIn('ChatGPT', openai.status())
        openai.method = providers.KEY
        self.assertEqual('sk-key', openai.auth().token)
        self.assertEqual('Using your saved API key.', openai.status())

    def test_a_sign_in_about_to_run_out_is_renewed(self):
        grok = self.provider(providers.XAI)
        grok.save_web_record({'access_token': 'old', 'refresh_token': 'r1',
                              'expires_at': time.time() + 10})
        answer = {'access_token': 'new', 'refresh_token': 'r2',
                  'expires_in': 3600}
        with mock.patch.object(web, 'post_json',
                               return_value=answer) as post:
            self.assertEqual('new', grok.auth().token)
        form = post.call_args[1]['form']
        self.assertEqual('refresh_token', form['grant_type'])
        self.assertEqual('r1', form['refresh_token'])
        self.assertEqual('r2', grok.web_record()['refresh_token'])

    def test_a_refused_renewal_asks_to_sign_in_again(self):
        grok = self.provider(providers.XAI)
        grok.save_web_record({'access_token': 'old', 'refresh_token': 'r1',
                              'expires_at': 0})
        refused = web.WebError('invalid_grant (400)', status=400)
        with mock.patch.object(web, 'post_json', side_effect=refused):
            with self.assertRaises(providers.AuthError):
                grok.auth()

    def test_claude_signs_in_through_claude_code(self):
        claude = self.provider(providers.Anthropic)
        self.assertIsNone(claude.web_record())
        signed_in = {'email': 'me@example.com', 'plan': 'Ultra'}
        with mock.patch.object(claude_code, 'find_cli',
                               return_value='claude'), \
                mock.patch.object(claude_code, 'signed_in',
                                  return_value=signed_in):
            auth = claude.auth()
            self.assertEqual(providers.WEB, auth.kind)
            self.assertIsNone(auth.token)
            self.assertEqual('Using your Claude Code sign in '
                             '(me@example.com, Ultra plan).', claude.status())
            self.assertEqual(claude_code.MODELS, claude.list_models())
            claude.save_api_key('sk-ant')
            self.assertEqual(providers.KEY, claude.auth().kind)
            claude.method = providers.WEB
            self.assertEqual(providers.WEB, claude.auth().kind)

    def test_choices_are_saved_in_prefs_not_keys(self):
        openai = self.provider(providers.OpenAI)
        openai.model = 'gpt-test'
        openai.save_api_key('sk-key')
        self.assertEqual({'openai': 'gpt-test'}, self.prefs[PREF.AI_MODELS])
        self.assertNotIn('sk-key', json.dumps(self.prefs))


class ProviderRequestTests(unittest.TestCase):

    def setUp(self):
        self.store = memory_store()
        self.prefs = {}

    def provider(self, cls):
        provider = cls(store=self.store, prefs=self.prefs)
        provider.save_api_key('test-key')
        return provider

    def test_claude_streams_text(self):
        claude = self.provider(providers.Anthropic)
        reply = sse(('message_start', {'type': 'message_start'}),
                    ('content_block_delta', {
                        'type': 'content_block_delta',
                        'delta': {'type': 'text_delta', 'text': 'Hel'}}),
                    ('content_block_delta', {
                        'type': 'content_block_delta',
                        'delta': {'type': 'text_delta', 'text': 'lo'}}),
                    ('message_stop', {'type': 'message_stop'}))
        with mock.patch.object(web, 'request', return_value=reply) as req:
            text = ''.join(claude.stream_chat(
                [{'role': 'user', 'content': 'hi'}], 'sys', model='c-1'))
        self.assertEqual('Hello', text)
        url = req.call_args[0][0]
        kwargs = req.call_args[1]
        self.assertEqual('https://api.anthropic.com/v1/messages', url)
        self.assertEqual('test-key', kwargs['headers']['x-api-key'])
        self.assertEqual('sys', kwargs['data']['system'])
        self.assertTrue(kwargs['data']['stream'])

    def test_openai_streams_text_without_storing_it(self):
        openai = self.provider(providers.OpenAI)
        reply = sse(('response.output_text.delta',
                     {'type': 'response.output_text.delta', 'delta': 'Hi'}),
                    ('response.output_text.delta',
                     {'type': 'response.output_text.delta', 'delta': '!'}),
                    ('response.completed', {'type': 'response.completed'}))
        with mock.patch.object(web, 'request', return_value=reply) as req:
            text = ''.join(openai.stream_chat(
                [{'role': 'user', 'content': 'hi'}], 'sys', model='g'))
        self.assertEqual('Hi!', text)
        body = req.call_args[1]['data']
        self.assertEqual('https://api.openai.com/v1/responses',
                         req.call_args[0][0])
        self.assertFalse(body['store'])
        self.assertTrue(body['stream'])
        self.assertEqual('Bearer test-key',
                         req.call_args[1]['headers']['Authorization'])

    def test_openai_reports_a_used_up_plan(self):
        openai = self.provider(providers.OpenAI)
        reply = sse(('response.failed', {
            'type': 'response.failed', 'response': {'error': {
                'code': 'subscription_sharing_usage_limit_exceeded',
                'message': 'Usage limit reached'}}}))
        with mock.patch.object(web, 'request', return_value=reply):
            with self.assertRaises(web.WebError) as caught:
                list(openai.stream_chat([], 'sys', model='g'))
        self.assertIn('chatgpt.com/settings/usage', str(caught.exception))

    def test_grok_streams_text(self):
        grok = self.provider(providers.XAI)
        reply = sse((None, {'choices': [{'delta': {'content': 'Yo'}}]}),
                    (None, {'choices': [{'delta': {}}]}),
                    (None, '[DONE]'))
        with mock.patch.object(web, 'request', return_value=reply) as req:
            text = ''.join(grok.stream_chat(
                [{'role': 'user', 'content': 'hi'}], 'sys', model='grok'))
        self.assertEqual('Yo', text)
        messages = req.call_args[1]['data']['messages']
        self.assertEqual({'role': 'system', 'content': 'sys'}, messages[0])

    def test_models_are_listed_newest_first_without_non_chat_ones(self):
        openai = self.provider(providers.OpenAI)
        listed = {'data': [{'id': 'gpt-old', 'created': 1},
                           {'id': 'text-embedding-3', 'created': 5},
                           {'id': 'gpt-new', 'created': 9}]}
        with mock.patch.object(web, 'get_json', return_value=listed):
            self.assertEqual(['gpt-new', 'gpt-old'], openai.list_models())

    def test_a_chatgpt_plan_lists_only_the_models_it_shows(self):
        openai = self.provider(providers.OpenAI)
        listed = {'data': [{'id': 'gpt-a', 'visibility': 'list'},
                           {'id': 'gpt-b', 'visibility': 'hide'}]}
        with mock.patch.object(web, 'get_json', return_value=listed):
            self.assertEqual(['gpt-a'], openai.list_models())

    def test_an_error_body_is_made_readable(self):
        body = json.dumps({'error': {'message': 'invalid x-api-key',
                                     'type': 'authentication_error'}})
        err = urllib.error.HTTPError('u', 401, 'Unauthorized', {},
                                     io.BytesIO(body.encode('utf-8')))
        with mock.patch.object(urllib.request, 'urlopen', side_effect=err):
            with self.assertRaises(web.WebError) as caught:
                web.request('https://api.anthropic.com/v1/models')
        self.assertEqual('invalid x-api-key (401)', str(caught.exception))
        self.assertEqual(401, caught.exception.status)


class OpenAISignInTests(unittest.TestCase):

    def browser(self, answer_with):
        """Stands in for the web browser: goes straight to the redirect."""
        self.opened = []

        def open_browser(url):
            self.opened.append(url)
            query = dict(urllib.parse.parse_qsl(
                urllib.parse.urlparse(url).query))
            answer = answer_with(query)

            def go():
                target = query['redirect_uri'] + '?' + \
                    urllib.parse.urlencode(answer)
                urllib.request.urlopen(target, timeout=5).read()
            threading.Thread(target=go, daemon=True).start()
        return open_browser

    def test_the_first_sign_in_registers_the_editor(self):
        def answer(query):
            return {'code': 'the-code', 'state': query['state'],
                    'client_id': 'oaiapp_123',
                    'scope': signin.OpenAI.SCOPE}
        id_token = 'x.' + signin._b64url(json.dumps(
            {'email': 'me@example.com'}).encode('utf-8')) + '.y'
        tokens = {'access_token': 'at', 'refresh_token': 'rt',
                  'id_token': id_token, 'expires_in': 3600}
        with mock.patch.object(web, 'post_json',
                               return_value=tokens) as post:
            record = signin.OpenAI.sign_in(self.browser(answer),
                                           'urn:uuid:host', timeout=10)
        query = dict(urllib.parse.parse_qsl(
            urllib.parse.urlparse(self.opened[0]).query))
        self.assertEqual('dynamic_agent_client', query['client_id'])
        self.assertEqual('nxt editor', query['agent_name_hint'])
        self.assertEqual('urn:uuid:host', query['ext_agent_host_id'])
        self.assertEqual('S256', query['code_challenge_method'])
        self.assertTrue(query['redirect_uri'].startswith(
            'http://127.0.0.1:'))
        self.assertTrue(query['redirect_uri'].endswith('/auth/callback'))
        form = post.call_args[1]['form']
        self.assertEqual('oaiapp_123', form['client_id'])
        self.assertEqual('the-code', form['code'])
        self.assertEqual('oaiapp_123', record['client_id'])
        self.assertEqual('me@example.com', record['email'])
        self.assertEqual('rt', record['refresh_token'])

    def test_signing_in_again_reuses_the_client(self):
        def answer(query):
            return {'code': 'c', 'state': query['state']}
        tokens = {'access_token': 'at', 'refresh_token': 'rt'}
        with mock.patch.object(web, 'post_json', return_value=tokens):
            record = signin.OpenAI.sign_in(self.browser(answer), 'urn:uuid:h',
                                           client_id='oaiapp_9', timeout=10)
        query = dict(urllib.parse.parse_qsl(
            urllib.parse.urlparse(self.opened[0]).query))
        self.assertEqual('oaiapp_9', query['client_id'])
        self.assertNotIn('agent_name_hint', query)
        self.assertEqual('oaiapp_9', record['client_id'])

    def test_an_answer_for_another_sign_in_is_refused(self):
        def answer(query):
            return {'code': 'c', 'state': 'someone-else'}
        with mock.patch.object(web, 'post_json') as post:
            with self.assertRaises(signin.SignInError):
                signin.OpenAI.sign_in(self.browser(answer), 'h', timeout=10)
        post.assert_not_called()

    def test_a_plan_not_shared_is_explained(self):
        def answer(query):
            return {'code': 'c', 'state': query['state'],
                    'client_id': 'oaiapp_1', 'scope': 'openid email'}
        tokens = {'access_token': 'at', 'scope': 'openid email'}
        with mock.patch.object(web, 'post_json', return_value=tokens):
            with self.assertRaises(signin.SignInError) as caught:
                signin.OpenAI.sign_in(self.browser(answer), 'h', timeout=10)
        self.assertIn('plan', str(caught.exception))

    def test_cancel_stops_waiting(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(signin.Cancelled):
            signin.OpenAI.sign_in(lambda url: None, 'h', cancelled=cancelled)

    def test_the_provider_keeps_the_host_and_client(self):
        prefs = {}
        openai = providers.OpenAI(store=memory_store(), prefs=prefs)
        record = {'client_id': 'oaiapp_5', 'access_token': 'at',
                  'expires_at': time.time() + 3600}
        with mock.patch.object(signin.OpenAI, 'sign_in',
                               return_value=record) as sign_in:
            openai.sign_in(lambda url: None)
        host_id = prefs[PREF.AI_OPENAI_HOST_ID]
        self.assertTrue(host_id.startswith('urn:uuid:'))
        self.assertEqual(host_id, sign_in.call_args[0][1])
        self.assertEqual('oaiapp_5', prefs[PREF.AI_OPENAI_CLIENT_ID])
        self.assertEqual('at', openai.auth().token)


class XAISignInTests(unittest.TestCase):

    DEVICE = {'device_code': 'dc', 'user_code': 'ABCD-1234',
              'verification_uri': 'https://accounts.x.ai/device',
              'verification_uri_complete':
                  'https://accounts.x.ai/device?code=ABCD-1234',
              'interval': 1, 'expires_in': 600}

    def test_a_code_is_given(self):
        with mock.patch.object(web, 'post_json',
                               return_value=self.DEVICE) as post:
            device = signin.XAI.start()
        self.assertEqual('ABCD-1234', device['user_code'])
        self.assertEqual(signin.XAI.DEVICE_URL, post.call_args[0][0])

    def test_a_code_that_is_not_https_is_refused(self):
        device = dict(self.DEVICE, verification_uri='http://x',
                      verification_uri_complete=None)
        with mock.patch.object(web, 'post_json', return_value=device):
            with self.assertRaises(signin.SignInError):
                signin.XAI.start()

    def test_waits_until_the_code_is_approved(self):
        answers = [web.WebError('pending', code='authorization_pending'),
                   web.WebError('slow', code='slow_down'),
                   {'access_token': 'at', 'refresh_token': 'rt',
                    'expires_in': 3600}]
        with mock.patch.object(web, 'post_json', side_effect=answers) as post:
            record = signin.XAI.wait(self.DEVICE, sleep=lambda s: None)
        self.assertEqual(3, post.call_count)
        self.assertEqual(signin.XAI.DEVICE_GRANT,
                         post.call_args[1]['form']['grant_type'])
        self.assertEqual('at', record['access_token'])

    def test_a_turned_down_code_stops(self):
        refused = web.WebError('no', code='access_denied')
        with mock.patch.object(web, 'post_json', side_effect=refused):
            with self.assertRaises(signin.SignInError):
                signin.XAI.wait(self.DEVICE, sleep=lambda s: None)


class FakeProcess(object):
    """Stands in for claude -p."""
    def __init__(self, lines, stderr=b''):
        self.stdin = io.BytesIO()
        self.stdin.close = lambda: None
        self.stdout = [l if isinstance(l, bytes)
                       else json.dumps(l).encode('utf-8') + b'\n'
                       for l in lines]
        self.stderr = io.BytesIO(stderr)
        self.killed = False

    def poll(self):
        return 1 if self.killed else None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


def delta(text):
    return {'type': 'stream_event', 'event': {
        'type': 'content_block_delta',
        'delta': {'type': 'text_delta', 'text': text}}}


class ClaudeCodeTests(unittest.TestCase):

    def setUp(self):
        claude_code.forget_status()
        self.addCleanup(claude_code.forget_status)

    def run_chat(self, process, messages=None, model='opus'):
        messages = messages or [{'role': 'user', 'content': 'hi'}]
        with mock.patch.object(claude_code.subprocess, 'Popen',
                               return_value=process) as popen, \
                mock.patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'k'}):
            text = ''.join(claude_code.stream_chat(
                messages, 'the system', model=model, cli='claude'))
        return text, popen

    def test_a_reply_streams_from_claude_code(self):
        process = FakeProcess([
            {'type': 'system', 'subtype': 'init'},
            b'not json\n',
            delta('Hel'), delta('lo'),
            {'type': 'result', 'is_error': False, 'result': 'Hello'}])
        text, popen = self.run_chat(process)
        self.assertEqual('Hello', text)
        args = popen.call_args[0][0]
        self.assertEqual(['claude', '-p'], args[:2])
        self.assertIn('--no-session-persistence', args)
        self.assertEqual('', args[args.index('--tools') + 1])
        self.assertEqual('opus', args[args.index('--model') + 1])
        self.assertEqual(b'hi', process.stdin.getvalue())
        # The sign in is used, not a key that happens to be set.
        self.assertNotIn('ANTHROPIC_API_KEY', popen.call_args[1]['env'])
        system_file = args[args.index('--system-prompt-file') + 1]
        self.assertFalse(os.path.exists(system_file))

    def test_an_error_from_claude_code_is_shown(self):
        process = FakeProcess([{'type': 'result', 'is_error': True,
                                'result': 'Not logged in'}])
        with self.assertRaises(claude_code.ClaudeCodeError) as caught:
            self.run_chat(process)
        self.assertEqual('Not logged in', str(caught.exception))

    def test_claude_code_ending_early_is_explained(self):
        process = FakeProcess([], stderr=b'line one\nit broke\n')
        with self.assertRaises(claude_code.ClaudeCodeError) as caught:
            self.run_chat(process)
        self.assertEqual('it broke', str(caught.exception))

    def test_earlier_turns_go_in_the_prompt(self):
        prompt = claude_code.as_prompt([
            {'role': 'user', 'content': 'first'},
            {'role': 'assistant', 'content': 'answer'},
            {'role': 'user', 'content': 'second'}])
        self.assertIn('User: first', prompt)
        self.assertIn('You: answer', prompt)
        self.assertTrue(prompt.endswith('second'))

    def test_who_is_signed_in(self):
        answer = mock.Mock(stdout=json.dumps({
            'loggedIn': True, 'email': 'me@example.com',
            'subscriptionType': 'ultra', 'authMethod': 'claude.ai'}))
        with mock.patch.object(claude_code.subprocess, 'run',
                               return_value=answer) as run:
            record = claude_code.signed_in('claude')
            claude_code.signed_in('claude')
        self.assertEqual({'email': 'me@example.com', 'plan': 'Ultra',
                          'auth_method': 'claude.ai'}, record)
        self.assertEqual(['claude', 'auth', 'status', '--json'],
                         run.call_args[0][0])
        # Asked once, then remembered for a while.
        self.assertEqual(1, run.call_count)

    def test_not_signed_in(self):
        answer = mock.Mock(stdout=json.dumps({'loggedIn': False}))
        with mock.patch.object(claude_code.subprocess, 'run',
                               return_value=answer):
            self.assertIsNone(claude_code.signed_in('claude'))

    def login(self, lines, returncode=0):
        process = mock.Mock()
        process.stdout = [l.encode('utf-8') + b'\n' for l in lines]
        process.returncode = returncode
        process.poll.return_value = returncode
        popen = mock.Mock(return_value=process)
        login = claude_code.Login('claude', popen=popen)
        login.reader.join(2)
        return login, process, popen

    def test_signing_in_opens_the_browser_without_a_window(self):
        url = 'https://claude.com/cai/oauth/authorize?code=true&state=x'
        login, process, popen = self.login([
            'Opening browser to sign in...',
            'If the browser didn\'t open, visit: ' + url,
            'Paste code here if prompted >'])
        self.assertEqual(['claude', 'auth', 'login'], popen.call_args[0][0])
        self.assertEqual(claude_code._NO_WINDOW,
                         popen.call_args[1]['creationflags'])
        self.assertEqual(url, login.url)

    def test_a_pasted_code_goes_to_claude_code(self):
        login, process, popen = self.login([])
        process.poll.return_value = None
        login.send_code('  the-code  ')
        process.stdin.write.assert_called_once_with(b'the-code\n')

    def test_signing_in_again_with_the_same_account_finishes(self):
        login, process, popen = self.login(['Login successful.'])
        record = {'email': 'me@example.com', 'plan': 'Ultra'}
        with mock.patch.object(claude_code, 'signed_in',
                               return_value=record) as signed_in:
            self.assertEqual(record, login.wait(threading.Event()))
        self.assertFalse(signed_in.call_args[1]['cached'])

    def test_a_failed_sign_in_says_why(self):
        login, process, popen = self.login(['OAuth error: denied'],
                                           returncode=1)
        with mock.patch.object(claude_code, 'signed_in', return_value=None):
            with self.assertRaises(claude_code.ClaudeCodeError) as caught:
                login.wait(threading.Event())
        self.assertEqual('OAuth error: denied', str(caught.exception))

    def test_cancel_stops_the_sign_in(self):
        login, process, popen = self.login([])
        process.poll.return_value = None
        cancelled = threading.Event()
        cancelled.set()
        self.assertIsNone(login.wait(cancelled))
        process.kill.assert_called_once()

    def test_not_installed(self):
        with self.assertRaises(claude_code.ClaudeCodeError):
            claude_code.Login(None)

    def test_found_where_the_installer_put_it_when_not_on_path(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        cli = os.path.join(folder, 'claude.exe')
        open(cli, 'w').close()
        with mock.patch.object(claude_code.shutil, 'which',
                               return_value=None),                 mock.patch.object(claude_code, '_install_places',
                                  return_value=['/nope/claude', cli]),                 mock.patch.object(user_dir.user_prefs, 'get',
                                  return_value=None):
            self.assertEqual(cli, REAL_FIND_CLI())
            with mock.patch.object(claude_code, '_install_places',
                                   return_value=[]):
                self.assertIsNone(REAL_FIND_CLI())

    def test_a_chosen_claude_code_comes_first(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        cli = os.path.join(folder, 'claude.exe')
        open(cli, 'w').close()
        with mock.patch.object(user_dir.user_prefs, 'get',
                               return_value=cli):
            self.assertEqual(cli, REAL_FIND_CLI())

    def test_the_api_gets_a_real_model_for_an_alias(self):
        claude = providers.Anthropic(store=memory_store(), prefs={})
        claude.save_api_key('sk-ant')
        listed = {'data': [{'id': 'claude-opus-9'},
                           {'id': 'claude-sonnet-9'}]}
        reply = sse(('message_stop', {'type': 'message_stop'}))
        with mock.patch.object(web, 'get_json', return_value=listed), \
                mock.patch.object(web, 'request', return_value=reply) as req:
            list(claude.stream_chat([], 'sys', model='sonnet'))
        self.assertEqual('claude-sonnet-9', req.call_args[1]['data']['model'])


class LocalModelTests(unittest.TestCase):

    def setUp(self):
        self.prefs = {}
        self.local = providers.Local(store=memory_store(), prefs=self.prefs)

    def test_not_set_up_until_a_server_is_chosen(self):
        self.assertIsNone(self.local.auth())
        self.assertEqual('Not set up.', self.local.status())

    def test_a_typed_address_is_tidied(self):
        self.local.base_url = 'localhost:11434/'
        self.assertEqual('http://localhost:11434/v1', self.local.base_url)
        self.local.base_url = 'http://gpu-box:8000/v1'
        self.assertEqual('http://gpu-box:8000/v1',
                         self.prefs[PREF.AI_LOCAL_URL])

    def test_it_streams_from_the_server_without_a_key(self):
        self.local.base_url = 'http://localhost:1234/v1'
        reply = sse((None, {'choices': [{'delta': {'content': 'Hi'}}]}),
                    (None, '[DONE]'))
        with mock.patch.object(web, 'request', return_value=reply) as req:
            text = ''.join(self.local.stream_chat(
                [{'role': 'user', 'content': 'hi'}], 'sys', model='qwen'))
        self.assertEqual('Hi', text)
        self.assertEqual('http://localhost:1234/v1/chat/completions',
                         req.call_args[0][0])
        self.assertEqual({}, req.call_args[1]['headers'])
        self.assertEqual(providers.Local.TIMEOUT,
                         req.call_args[1]['timeout'])

    def test_a_server_that_wants_a_key_gets_it(self):
        self.local.base_url = 'http://localhost:8000/v1'
        self.local.save_api_key('local-key')
        with mock.patch.object(web, 'get_json',
                               return_value={'data': [{'id': 'm'}]}) as get:
            self.assertEqual(['m'], self.local.list_models())
        self.assertEqual('Bearer local-key',
                         get.call_args[1]['headers']['Authorization'])

    def test_running_servers_are_found(self):
        def answer(url, timeout=None, **kwargs):
            if ':11434' in url:
                return {'data': [{'id': 'llama3.2'}]}
            raise web.WebError('Could not reach it')
        with mock.patch.object(web, 'get_json', side_effect=answer):
            found = providers.Local.find_servers()
        self.assertEqual([('Ollama', 'http://localhost:11434/v1',
                           ['llama3.2'])], found)


class ContextTests(unittest.TestCase):

    def model(self):
        model = mock.Mock()
        model.selection = ['/node']
        model.target_layer.get_alias.return_value = 'top'
        model.target_layer.real_path = '/graphs/top.nxt'
        model.get_node_instance_path.return_value = '/source'
        model.get_node_enabled.return_value = False
        model.get_node_attr_names.return_value = ['count', '_internal']
        model.get_node_attr_value.return_value = '3'
        model.get_node_code_string.return_value = 'print(self.count)'
        return model

    def test_the_selected_node_is_described(self):
        text = context.describe_selection(self.model())
        self.assertIn('Node /node', text)
        self.assertIn('Instance of: /source', text)
        self.assertIn('Disabled', text)
        self.assertIn('count = 3', text)
        self.assertIn('print(self.count)', text)
        self.assertIn('top.nxt', text)

    def test_nothing_selected_says_nothing(self):
        model = self.model()
        model.selection = []
        self.assertEqual('', context.describe_selection(model))
        self.assertEqual('', context.describe_selection(None))

    def test_the_last_code_block_is_found(self):
        reply = ('Try:\n```python\nold()\n```\nor better\n'
                 '```python\nnew()\nmore()\n```\nDone.')
        self.assertEqual('new()\nmore()', context.last_code_block(reply))
        self.assertIsNone(context.last_code_block('No code here.'))


class FakeProvider(providers.Provider):
    id = 'anthropic'
    label = 'Claude'
    reply = ['Here:\n```python\n', 'print("hi")\n', '```']

    def list_models(self, auth=None):
        return ['claude-test', 'claude-other']

    def stream_chat(self, messages, system, model=None, auth=None,
                    tools=None):
        self.sent = messages
        for part in self.reply:
            yield part


def wait_for(condition, timeout=5):
    end = time.time() + timeout
    while not condition() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


class AssistantPanelTests(unittest.TestCase):

    def setUp(self):
        from nxt_editor.dockwidgets.ai_assistant import AiAssistant
        self.store = memory_store()
        self.prefs = {PREF.AI_ENABLED: True}
        claude = providers.Anthropic(store=self.store, prefs=self.prefs)
        claude.save_api_key('k')
        claude.model = 'claude-test'
        self.fake = FakeProvider(store=self.store, prefs=self.prefs)
        patcher = mock.patch.object(providers, 'get_provider',
                                    return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        providers._models.clear()
        self.panel = AiAssistant(store=self.store, prefs=self.prefs)
        wait_for(lambda: self.panel.model_combo.count())
        self.model = mock.Mock()
        self.model.selection = ['/node']
        self.panel.stage_model = self.model
        context_patch = mock.patch.object(
            context, 'describe_selection', return_value='Node /node')
        context_patch.start()
        self.addCleanup(context_patch.stop)
        graph_patch = mock.patch(
            'nxt_editor.ai.graph_actions.describe_graph',
            return_value='The graph')
        graph_patch.start()
        self.addCleanup(graph_patch.stop)

    def tearDown(self):
        self.panel.stop()
        if self.panel.thread:
            self.panel.thread.wait(2000)
        self.panel.deleteLater()

    def ask(self, text):
        self.panel.send(text)
        wait_for(lambda: not self.panel.busy and self.panel.messages and
                 self.panel.messages[-1]['role'] == 'assistant')

    def test_a_question_gets_an_answer(self):
        self.assertTrue(self.panel.setup_label.isHidden())
        self.ask('What does this do?')
        self.assertEqual(2, len(self.panel.messages))
        self.assertIn('print("hi")', self.panel.messages[1]['content'])
        self.assertIn('print("hi")', self.panel.transcript.toPlainText())

    def test_the_selection_goes_with_the_question(self):
        self.ask('What does this do?')
        self.assertIn('Node /node', self.fake.sent[0]['content'])
        self.assertNotIn('Node /node',
                         self.panel.transcript.toPlainText())

    def test_the_selection_can_be_left_out(self):
        self.panel.include_check.setChecked(False)
        self.panel.edit_check.setChecked(False)
        self.assertFalse(self.prefs[PREF.AI_INCLUDE_SELECTION])
        self.ask('Hello')
        self.assertEqual('Hello', self.fake.sent[0]['content'])

    def test_code_from_the_reply_is_applied_to_the_node(self):
        self.ask('Write code')
        self.panel.update_buttons()
        self.assertTrue(self.panel.apply_button.isEnabled())
        self.panel.apply_code()
        self.model.set_node_code_lines.assert_called_once_with(
            '/node', ['print("hi")'])

    def test_a_failure_puts_the_question_back(self):
        def broken(*args, **kwargs):
            raise web.WebError('No credit left (402)')
            yield
        self.fake.stream_chat = broken
        self.panel.send('Hello')
        wait_for(lambda: not self.panel.busy and
                 self.panel.input.toPlainText())
        self.assertEqual([], self.panel.messages)
        self.assertEqual('Hello', self.panel.input.toPlainText())
        self.assertIn('No credit left', self.panel.status_label.text())

    def test_only_offered_models_can_be_chosen_and_one_is(self):
        combo = self.panel.model_combo
        self.assertFalse(combo.isEditable())
        self.assertEqual(['claude-test', 'claude-other'],
                         [combo.itemText(i) for i in range(combo.count())])
        self.assertEqual('claude-test', combo.currentText())
        self.assertTrue(self.panel.send_button.isEnabled())

    def test_a_model_list_that_fails_says_why(self):
        self.panel.on_models_failed(self.fake, 'You have run out of credits '
                                    '(403)')
        self.assertEqual(0, self.panel.model_combo.count())
        self.assertFalse(self.panel.model_combo.isEnabled())
        self.assertFalse(self.panel.send_button.isEnabled())
        self.assertIn('run out of credits', self.panel.status_label.text())

    def test_new_chat_starts_over(self):
        self.ask('Hello')
        self.panel.new_chat()
        self.assertEqual([], self.panel.messages)
        self.assertEqual('', self.panel.transcript.toPlainText())


class NotSetUpPanelTests(unittest.TestCase):

    def test_it_points_to_the_settings(self):
        from nxt_editor.dockwidgets.ai_assistant import AiAssistant
        with mock.patch.dict('os.environ', {}, clear=True):
            panel = AiAssistant(store=memory_store(), prefs={})
        self.assertFalse(panel.setup_label.isHidden())
        opened = []
        panel.open_settings.connect(lambda: opened.append(True))
        panel.setup_label.linkActivated.emit('settings')
        self.assertEqual([True], opened)


class SettingsDialogTests(unittest.TestCase):

    def setUp(self):
        self.prefs = {PREF.AI_ENABLED: True}
        self.store = memory_store()
        env = mock.patch.dict('os.environ', {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        providers._models.clear()
        self.dialog = self.make_dialog()

    def make_dialog(self):
        from nxt_editor.ai.settings_dialog import AiSettingsDialog
        return AiSettingsDialog(store=self.store, prefs=self.prefs)

    def tearDown(self):
        self.dialog.done(0)
        self.dialog.deleteLater()

    def box(self, provider_id):
        for box in self.dialog.boxes:
            if box.provider.id == provider_id:
                return box

    def test_it_is_off_until_turned_on(self):
        self.dialog.done(0)
        self.prefs.clear()
        self.dialog = self.make_dialog()
        self.assertFalse(self.dialog.enable_check.isChecked())
        self.assertFalse(self.dialog.body.isEnabled())
        seen = []
        self.dialog.enabled_changed.connect(seen.append)
        self.dialog.enable_check.setChecked(True)
        self.assertTrue(self.prefs[PREF.AI_ENABLED])
        self.assertTrue(self.dialog.body.isEnabled())
        self.assertEqual([True], seen)

    def test_every_provider_has_a_web_button_and_a_key(self):
        labels = {b.provider.id: b.web_button.text()
                  for b in self.dialog.boxes}
        self.assertEqual('Install Claude Code to Sign In',
                         labels['anthropic'])
        self.assertEqual('Sign in with ChatGPT', labels['openai'])
        self.assertEqual('Sign in with SuperGrok', labels['xai'])
        for box in self.dialog.boxes:
            self.assertTrue(box.key_edit.isEnabled())

    def test_without_claude_code_it_points_to_the_install(self):
        box = self.box('anthropic')
        with mock.patch('nxt_editor.ai.settings_dialog.open_url') as opened:
            box.sign_in()
        opened.assert_called_once_with(claude_code.INSTALL_URL)

    def test_claude_code_signs_in_with_any_account(self):
        box = self.box('anthropic')
        record = {'email': 'me@example.com', 'plan': 'Ultra'}
        login = mock.Mock(url='https://claude.com/cai/oauth/authorize')
        with mock.patch.object(claude_code, 'find_cli',
                               return_value='claude'), \
                mock.patch.object(providers.Anthropic, 'start_sign_in',
                                  return_value=login), \
                mock.patch.object(providers.Anthropic, 'finish_sign_in',
                                  return_value=record) as finish, \
                mock.patch.object(claude_code, 'signed_in',
                                  return_value=None):
            box.refresh()
            self.assertEqual('Sign in with Claude Code',
                             box.web_button.text())
            with mock.patch.object(box, 'check'):
                box.sign_in()
                self.assertFalse(box.wait_dialog.paste_widget.isHidden())
                box.wait_dialog.paste_edit.setText('abc')
                box.wait_dialog.paste_button.click()
                login.send_code.assert_called_once_with('abc')
                wait_for(lambda: box.wait_dialog is None)
            finish.assert_called_once()
        with mock.patch.object(claude_code, 'find_cli',
                               return_value='claude'), \
                mock.patch.object(claude_code, 'signed_in',
                                  return_value=record):
            box.refresh()
            self.assertEqual('Switch Account', box.web_button.text())
            self.assertTrue(box.sign_out_button.isEnabled())
            self.assertIn('Ultra', box.status_label.text())

    def test_showing_the_window_picks_up_a_new_sign_in(self):
        box = self.box('anthropic')
        record = {'email': 'me@example.com', 'plan': 'Ultra'}
        with mock.patch.object(claude_code, 'find_cli',
                               return_value='claude'), \
                mock.patch.object(claude_code, 'signed_in',
                                  return_value=record):
            self.dialog.show()
            app.processEvents()
        self.assertIn('me@example.com', box.status_label.text())
        self.dialog.hide()

    def test_a_local_server_is_found(self):
        box = self.box('local')
        self.assertTrue(box.web_button.isHidden())
        found = [('LM Studio', 'http://localhost:1234/v1', ['qwen', 'gemma'])]
        box.on_servers(found)
        self.assertEqual('http://localhost:1234/v1', box.url_edit.text())
        self.assertEqual('qwen', box.model_combo.currentText())
        self.assertIn('LM Studio', box.status_label.text())
        box.on_servers([])
        self.assertIn('No local server', box.status_label.text())

    def test_a_typed_server_is_saved(self):
        box = self.box('local')
        box.url_edit.setText('localhost:11434')
        with mock.patch.object(box, 'check') as check:
            box.on_url_edited()
        check.assert_called_once()
        self.assertEqual('http://localhost:11434/v1',
                         self.prefs[PREF.AI_LOCAL_URL])


    def test_a_saved_key_goes_to_the_secure_store(self):
        box = self.box('anthropic')
        box.key_edit.setText('sk-ant-test')
        with mock.patch.object(box, 'check') as check:
            box.save_key()
        check.assert_called_once()
        self.assertEqual({'api_key': 'sk-ant-test'},
                         self.store.get('anthropic.api_key'))
        self.assertEqual('', box.key_edit.text())
        self.assertNotIn('sk-ant-test', json.dumps(self.prefs))
        self.assertTrue(box.remove_key_button.isEnabled())
        box.remove_key()
        self.assertIsNone(self.store.get('anthropic.api_key'))

    def test_grok_shows_the_code_to_approve(self):
        box = self.box('xai')
        device = XAISignInTests.DEVICE
        started = threading.Event()

        def finish(dev, cancelled=None):
            started.set()
            cancelled.wait(5)
            raise signin.Cancelled()
        with mock.patch.object(providers.XAI, 'start_sign_in',
                               return_value=device), \
                mock.patch.object(providers.XAI, 'finish_sign_in',
                                  side_effect=finish), \
                mock.patch('nxt_editor.ai.settings_dialog.open_url') as opened:
            box.sign_in()
            wait_for(started.is_set)
            self.assertEqual('ABCD-1234', box.wait_dialog.code_label.text())
            opened.assert_called_once_with(
                device['verification_uri_complete'])
            box.wait_dialog.reject()
            box.thread.wait(2000)

    def test_both_ways_signed_in_lets_you_choose(self):
        box = self.box('openai')
        box.provider.save_api_key('sk')
        box.provider.save_web_record({'access_token': 'a',
                                      'expires_at': time.time() + 999})
        with mock.patch.object(box, 'load_models'):
            box.refresh()
            self.assertFalse(box.use_widget.isHidden())
            box.use_key.setChecked(True)
        self.assertEqual(providers.KEY, box.provider.method)

    def test_the_models_are_loaded(self):
        box = self.box('xai')
        self.assertFalse(box.model_combo.isEditable())
        box.on_models(['grok-new', 'grok-old'])
        self.assertEqual('grok-new', box.model_combo.currentText())
        self.assertEqual('grok-new', box.provider.model)
        box.provider.model = 'grok-old'
        box.on_models(['grok-new', 'grok-old'])
        self.assertEqual('grok-old', box.model_combo.currentText())

    def test_a_saved_model_no_longer_offered_is_replaced(self):
        box = self.box('xai')
        box.provider.model = 'grok-gone'
        box.on_models(['grok-new'])
        self.assertEqual('grok-new', box.provider.model)

    def test_a_refused_sign_in_shows_the_reason(self):
        box = self.box('xai')
        box.on_models_failed('You have run out of credits or need a Grok '
                             'subscription. (403)')
        self.assertIn('need a Grok subscription', box.status_label.text())
        self.assertFalse(box.model_combo.isEnabled())

    def test_models_load_by_themselves_once_set_up(self):
        box = self.box('xai')
        self.assertFalse(box.model_combo.isEnabled())
        with mock.patch.object(providers.XAI, 'list_models',
                               return_value=['grok-a', 'grok-b']):
            box.provider.save_api_key('xai-key')
            box.refresh()
            wait_for(lambda: box.model_combo.count())
        self.assertEqual('grok-a', box.model_combo.currentText())
        self.assertTrue(box.model_combo.isEnabled())


class FailingBackend(MemoryBackend):
    """A keyring that is there but can not save, like secret-tool with no
    keyring set up."""
    name = 'Secret Service'
    PROBLEM = ("No such object path "
               "'/org/freedesktop/secrets/aliases/default'")

    def get(self, key):
        raise secret_store.SecretStoreError(self.PROBLEM)

    def set(self, key, value):
        raise secret_store.SecretStoreError(self.PROBLEM)


class SecretStoreFallbackTests(unittest.TestCase):

    def setUp(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.path = os.path.join(folder, 'ai_sign_ins.json')
        self.file = secret_store._FileBackend(self.path)

    def test_a_keyring_that_can_not_save_falls_back_to_a_private_file(self):
        store = secret_store.SecretStore(FailingBackend(), fallback=self.file)
        store.set('openai.api_key', {'api_key': 'sk-1'})
        self.assertEqual({'api_key': 'sk-1'}, store.get('openai.api_key'))
        self.assertTrue(os.path.isfile(self.path))
        said = store.describe()
        self.assertIn('Secret Service could not save', said)
        self.assertIn('aliases/default', said)
        self.assertIn(self.path, said)
        if sys.platform != 'win32':
            self.assertEqual(0o600, os.stat(self.path).st_mode & 0o777)

    def test_no_keyring_at_all_uses_the_file(self):
        store = secret_store.SecretStore(None, fallback=self.file)
        self.assertTrue(store.available)
        store.set('xai.web', {'access_token': 't'})
        self.assertEqual({'access_token': 't'}, store.get('xai.web'))
        self.assertIn('no keyring', store.describe())

    def test_a_working_keyring_is_used_and_the_file_left_alone(self):
        store = secret_store.SecretStore(MemoryBackend(), fallback=self.file)
        store.set('openai.api_key', {'api_key': 'sk-1'})
        self.assertFalse(os.path.exists(self.path))
        self.assertIn('Memory', store.describe())

    def test_removing_clears_the_file_too(self):
        store = secret_store.SecretStore(FailingBackend(), fallback=self.file)
        store.set('openai.api_key', {'api_key': 'sk-1'})
        store.delete('openai.api_key')
        self.assertIsNone(store.get('openai.api_key'))
        self.assertFalse(os.path.exists(self.path))

    def test_saving_a_key_works_without_a_keyring(self):
        store = secret_store.SecretStore(FailingBackend(), fallback=self.file)
        openai = providers.OpenAI(store=store, prefs={})
        openai.save_api_key('sk-saved')
        self.assertEqual('sk-saved', openai.auth().token)


class OpenAISignInFeedbackTests(unittest.TestCase):

    browser = OpenAISignInTests.browser

    def test_a_turned_down_code_keeps_the_client_and_says_try_again(self):
        prefs = {}
        openai = providers.OpenAI(store=memory_store(), prefs=prefs)

        def answer(query):
            return {'code': 'c', 'state': query['state'],
                    'client_id': 'oaiapp_7'}
        refused = web.WebError('invalid_grant (400)', status=400,
                               code='invalid_grant')
        with mock.patch.object(web, 'post_json', side_effect=refused):
            with self.assertRaises(signin.SignInError) as caught:
                openai.sign_in(self.browser(answer))
        self.assertIn('Sign in again', str(caught.exception))
        self.assertNotIn('invalid_grant (400)', str(caught.exception))
        # Kept, so the next try goes back to the same registration.
        self.assertEqual('oaiapp_7', prefs[PREF.AI_OPENAI_CLIENT_ID])

    def test_signing_in_again_goes_back_to_the_same_account(self):
        store = memory_store()
        prefs = {PREF.AI_OPENAI_CLIENT_ID: 'oaiapp_3'}
        store.set('openai.web', {'client_id': 'oaiapp_3', 'id_token': 'idt',
                                 'email': 'me@example.com'})
        openai = providers.OpenAI(store=store, prefs=prefs)

        def answer(query):
            return {'code': 'c', 'state': query['state']}
        tokens = {'access_token': 'at', 'refresh_token': 'rt'}
        with mock.patch.object(web, 'post_json', return_value=tokens):
            openai.sign_in(self.browser(answer))
        query = dict(urllib.parse.parse_qsl(
            urllib.parse.urlparse(self.opened[0]).query))
        self.assertEqual('oaiapp_3', query['client_id'])
        self.assertEqual('idt', query['id_token_hint'])
        self.assertEqual('me@example.com', query['login_hint'])

    def test_an_answer_for_another_registration_is_refused(self):
        def answer(query):
            return {'code': 'c', 'state': query['state'],
                    'client_id': 'oaiapp_other'}
        with mock.patch.object(web, 'post_json') as post:
            with self.assertRaises(signin.SignInError):
                signin.OpenAI.sign_in(self.browser(answer), 'h',
                                      client_id='oaiapp_mine', timeout=10)
        post.assert_not_called()

    def test_turning_it_down_in_the_browser_is_explained(self):
        def answer(query):
            return {'error': 'access_denied', 'state': query['state']}
        with self.assertRaises(signin.SignInError) as caught:
            signin.OpenAI.sign_in(self.browser(answer), 'h', timeout=10)
        self.assertIn('turned down', str(caught.exception))
        self.assertIn('API key', str(caught.exception))


class FakeToolbox(object):
    def __init__(self):
        self.cancelled = threading.Event()
        self.calls = []

    def available(self):
        return True

    def responses_tools(self):
        return [{'type': 'function', 'name': 'get_node',
                 'description': 'd', 'parameters': {'type': 'object'}}]

    def call(self, name, args):
        self.calls.append((name, args))
        return 'the node', False


class ProviderFeedbackTests(unittest.TestCase):

    def setUp(self):
        self.store = memory_store()
        self.prefs = {}
        env = mock.patch.dict('os.environ', {}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        providers._models.clear()

    def signed_in_openai(self):
        openai = providers.OpenAI(store=self.store, prefs=self.prefs)
        openai.save_web_record({'access_token': 'at', 'client_id': 'c',
                                'expires_at': time.time() + 3600})
        return openai

    def test_a_chatgpt_plan_lists_its_own_models(self):
        openai = self.signed_in_openai()
        listed = {'models': [{'slug': 'gpt-a', 'visibility': 'list'},
                             {'slug': 'gpt-b', 'visibility': 'hide'},
                             {'slug': 'gpt-c', 'visibility': 'list'}]}
        with mock.patch.object(web, 'get_json', return_value=listed):
            self.assertEqual(['gpt-a', 'gpt-c'], openai.models())

    def test_a_chatgpt_plan_gets_the_tools_in_a_namespace(self):
        openai = self.signed_in_openai()
        toolbox = FakeToolbox()
        call = {'type': 'function_call', 'call_id': 'call_1',
                'name': 'get_node', 'namespace': 'nxt', 'arguments': '{}'}
        replies = [sse(('response.output_item.done',
                        {'type': 'response.output_item.done',
                         'item': call}),
                       ('response.completed',
                        {'type': 'response.completed'})),
                   sse(('response.output_text.delta',
                        {'type': 'response.output_text.delta',
                         'delta': 'Done'}),
                       ('response.completed',
                        {'type': 'response.completed'}))]
        with mock.patch.object(web, 'request',
                               side_effect=replies) as req:
            text = ''.join(openai.stream_chat(
                [{'role': 'user', 'content': 'hi'}], 'sys', model='g',
                tools=toolbox))
        self.assertEqual('Done', text)
        self.assertEqual([('get_node', '{}')], toolbox.calls)
        first = req.call_args_list[0][1]['data']
        self.assertEqual('namespace', first['tools'][0]['type'])
        self.assertEqual('get_node', first['tools'][0]['tools'][0]['name'])
        second = req.call_args_list[1][1]['data']
        echoed = [i for i in second['input']
                  if i.get('type') == 'function_call'][0]
        self.assertEqual('nxt', echoed['namespace'])

    def test_an_api_key_gets_the_tools_as_they_are(self):
        openai = providers.OpenAI(store=self.store, prefs=self.prefs)
        openai.save_api_key('sk')
        reply = sse(('response.completed', {'type': 'response.completed'}))
        with mock.patch.object(web, 'request', return_value=reply) as req:
            list(openai.stream_chat([], 'sys', model='g',
                                    tools=FakeToolbox()))
        self.assertEqual('function', req.call_args[1]['data']['tools'][0][
            'type'])

    def test_a_key_that_is_turned_down_says_what_to_do(self):
        claude = providers.Anthropic(store=self.store, prefs=self.prefs)
        claude.save_api_key('bad')
        refused = web.WebError('invalid x-api-key (401)', status=401,
                               code='authentication_error')
        with mock.patch.object(web, 'get_json', side_effect=refused):
            with self.assertRaises(web.WebError) as caught:
                claude.models(refresh=True)
        said = str(caught.exception)
        self.assertIn('Claude did not accept the saved API key', said)
        self.assertIn('invalid x-api-key', said)

    def test_a_sign_in_that_is_turned_down_says_sign_in_again(self):
        openai = self.signed_in_openai()
        refused = web.WebError('Unauthorized (401)', status=401)
        with mock.patch.object(web, 'request', side_effect=refused):
            with self.assertRaises(web.WebError) as caught:
                list(openai.stream_chat([], 'sys', model='g'))
        self.assertIn('Sign in again', str(caught.exception))

    def test_a_detail_error_body_is_read(self):
        body = json.dumps({'detail': 'Direct routing is not enabled'})
        err = urllib.error.HTTPError('u', 503, 'Unavailable', {},
                                     io.BytesIO(body.encode('utf-8')))
        with mock.patch.object(urllib.request, 'urlopen', side_effect=err):
            with self.assertRaises(web.WebError) as caught:
                web.request('https://api.openai.com/v1/responses')
        self.assertIn('Direct routing is not enabled',
                      str(caught.exception))


def codex_event(kind, **fields):
    data = {'type': kind}
    data.update(fields)
    return data


class CodexTests(unittest.TestCase):

    def setUp(self):
        codex.forget_status()
        self.addCleanup(codex.forget_status)
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        work = mock.patch.object(codex, '_work_dir', return_value=folder)
        work.start()
        self.addCleanup(work.stop)

    def run_chat(self, process, tools=None, messages=None):
        messages = messages or [{'role': 'user', 'content': 'hi'}]
        popen = mock.Mock(return_value=process)
        with mock.patch.dict('os.environ', {'OPENAI_API_KEY': 'k',
                                            'CODEX_API_KEY': 'k2'}):
            text = ''.join(codex.stream_chat(
                messages, 'the system', model='gpt-a', cli='codex',
                tools=tools, popen=popen))
        return text, popen

    def test_a_reply_comes_from_codex_exec(self):
        process = FakeProcess([
            codex_event('thread.started', thread_id='t'),
            codex_event('item.completed', item={
                'id': 'item_0', 'type': 'error',
                'message': 'Code Mode is unavailable'}),
            codex_event('turn.started'),
            b'not json\n',
            codex_event('item.completed', item={
                'id': 'item_1', 'type': 'agent_message', 'text': 'Hello'}),
            codex_event('turn.completed', usage={})])
        text, popen = self.run_chat(process)
        self.assertEqual('Hello', text)
        args = popen.call_args[0][0]
        self.assertEqual(['codex', 'exec', '--json'], args[:3])
        self.assertEqual('-', args[-1])
        self.assertIn('--ephemeral', args)
        self.assertIn('--ignore-user-config', args)
        self.assertIn('features.shell_tool=false', args)
        self.assertIn('approval_policy="never"', args)
        self.assertIn('gpt-a', args)
        env = popen.call_args[1]['env']
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertNotIn('CODEX_API_KEY', env)
        self.assertEqual(b'hi', process.stdin.getvalue())

    def test_the_tools_come_from_the_editor_by_a_hidden_key(self):
        process = FakeProcess([codex_event('turn.completed')])
        server = mock.Mock(url='http://127.0.0.1:5000/mcp')
        server.open.return_value = 'secret-token'
        tools = mock.Mock()
        tools.available.return_value = True
        with mock.patch.object(codex.mcp_server, 'server',
                               return_value=server):
            _text, popen = self.run_chat(process, tools=tools)
        args = popen.call_args[0][0]
        self.assertIn('mcp_servers.nxt.url="http://127.0.0.1:5000/mcp"',
                      args)
        self.assertIn('mcp_servers.nxt.bearer_token_env_var="{}"'.format(
            codex.TOKEN_VAR), args)
        self.assertNotIn('secret-token', ' '.join(args))
        self.assertEqual('secret-token',
                         popen.call_args[1]['env'][codex.TOKEN_VAR])
        server.close.assert_called_once_with('secret-token')

    def test_text_before_and_after_a_tool_is_kept_apart(self):
        process = FakeProcess([
            codex_event('item.completed', item={
                'id': 'a', 'type': 'agent_message', 'text': 'Looking.'}),
            codex_event('item.completed', item={
                'id': 'b', 'type': 'mcp_tool_call', 'tool': 'get_node'}),
            codex_event('item.updated', item={
                'id': 'c', 'type': 'agent_message', 'text': 'Fou'}),
            codex_event('item.completed', item={
                'id': 'c', 'type': 'agent_message', 'text': 'Found it.'}),
            codex_event('turn.completed')])
        text, _popen = self.run_chat(process)
        self.assertEqual('Looking.\n\nFound it.', text)

    def test_a_failed_turn_says_to_sign_in(self):
        process = FakeProcess([
            codex_event('error', message='Reconnecting... 1/5'),
            codex_event('turn.failed', error={
                'message': 'unexpected status 401 Unauthorized'})])
        with self.assertRaises(codex.CodexError) as caught:
            self.run_chat(process)
        self.assertIn('Sign in with Codex', str(caught.exception))

    def test_codex_ending_early_says_why(self):
        process = FakeProcess([codex_event('error', message='boom')])
        with self.assertRaises(codex.CodexError) as caught:
            self.run_chat(process)
        self.assertIn('boom', str(caught.exception))

    def test_who_is_signed_in(self):
        said = mock.Mock(returncode=0, stdout='Logged in using ChatGPT\n',
                         stderr='')
        with mock.patch.object(codex, '_run', return_value=said), \
                mock.patch.object(codex, '_account', return_value={
                    'email': 'me@example.com', 'plan': 'Plus'}):
            record = codex.signed_in('codex')
        self.assertEqual('me@example.com', record['email'])
        self.assertEqual('Plus', record['plan'])
        provider = providers.Codex(store=memory_store(), prefs={})
        self.assertIn('me@example.com, Plus plan',
                      provider.web_label(record))

    def test_not_signed_in(self):
        said = mock.Mock(returncode=1, stdout='Not logged in\n', stderr='')
        with mock.patch.object(codex, '_run', return_value=said):
            self.assertIsNone(codex.signed_in('codex'))

    def test_the_account_is_read_from_codex_auth_file(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        claims = {'email': 'me@example.com',
                  'https://api.openai.com/auth': {
                      'chatgpt_plan_type': 'pro'}}
        token = 'x.' + signin._b64url(json.dumps(claims).encode()) + '.y'
        with open(os.path.join(folder, 'auth.json'), 'w') as f:
            json.dump({'tokens': {'id_token': token}}, f)
        with mock.patch.dict('os.environ', {'CODEX_HOME': folder}):
            self.assertEqual({'email': 'me@example.com', 'plan': 'Pro'},
                             codex._account())

    def test_the_models_are_codex_own_in_its_order(self):
        catalog = {'models': [
            {'slug': 'b', 'visibility': 'list', 'priority': 2},
            {'slug': 'hidden', 'visibility': 'hide', 'priority': 0},
            {'slug': 'a', 'visibility': 'list', 'priority': 1}]}
        said = mock.Mock(returncode=0, stdout=json.dumps(catalog), stderr='')
        with mock.patch.object(codex, '_run', return_value=said):
            self.assertEqual(['a', 'b'], codex.list_models('codex'))

    def test_signing_in_finds_the_page_and_finishes(self):
        process = FakeProcess([
            b'\x1b[94mhttps://auth.openai.com/oauth/authorize?x=1\x1b[0m\n',
            b'Successfully logged in\n'])
        process.poll = lambda: 0
        process.returncode = 0
        with mock.patch.object(codex, 'signed_in', return_value={
                'email': 'me@example.com'}):
            login = codex.Login('codex', popen=mock.Mock(
                return_value=process))
            login.reader.join(2)
            record = login.wait(threading.Event())
        self.assertEqual('https://auth.openai.com/oauth/authorize?x=1',
                         login.url)
        self.assertEqual('me@example.com', record['email'])

    def test_a_failed_sign_in_says_why(self):
        process = FakeProcess([b'Error: address already in use\n'])
        process.poll = lambda: 1
        process.returncode = 1
        with mock.patch.object(codex, 'signed_in', return_value=None):
            login = codex.Login('codex', popen=mock.Mock(
                return_value=process))
            login.reader.join(2)
            with self.assertRaises(codex.CodexError) as caught:
                login.wait(threading.Event())
        self.assertIn('Another Codex sign in', str(caught.exception))

    def make_file(self, *parts):
        path = os.path.join(*parts)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write('')
        os.chmod(path, 0o755)
        return path

    def test_npm_on_windows_runs_the_program_not_the_cmd(self):
        top = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, top, True)
        cmd = self.make_file(top, 'npm', 'codex.cmd')
        exe = self.make_file(top, 'npm', 'node_modules', '@openai', 'codex',
                             'node_modules', '@openai', 'codex-win32-x64',
                             'vendor', 'x86_64-pc-windows-msvc', 'codex',
                             'codex.exe')
        with mock.patch.object(codex.sys, 'platform', 'win32'):
            self.assertEqual(exe, codex._unwrap(cmd))

    def test_npm_on_mac_and_linux_runs_the_program_not_node(self):
        top = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, top, True)
        modules = os.path.join(top, 'lib', 'node_modules', '@openai')
        script = self.make_file(modules, 'codex', 'bin', 'codex.js')
        for platform, package, triple in (
                ('linux', 'codex-linux-x64', 'x86_64-unknown-linux-musl'),
                ('darwin', 'codex-darwin-arm64', 'aarch64-apple-darwin')):
            program = self.make_file(modules, package, 'vendor', triple,
                                     'codex', 'codex')
            with mock.patch.object(codex.sys, 'platform', platform):
                self.assertEqual(program, codex._unwrap(script))
            os.remove(program)

    def test_an_install_without_node_is_used_as_it_is(self):
        top = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, top, True)
        native = self.make_file(top, 'bin', 'codex')
        self.assertEqual(native, codex._unwrap(native))
        # A wrapper whose program is missing is still better than nothing.
        cmd = self.make_file(top, 'npm', 'codex.cmd')
        self.assertEqual(cmd, codex._unwrap(cmd))

    def test_codex_is_found_where_installers_put_it(self):
        top = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, top, True)
        for platform in ('win32', 'darwin', 'linux'):
            with mock.patch.object(codex.sys, 'platform', platform),                     mock.patch.object(codex.os.path, 'expanduser',
                                      return_value=top):
                places = codex._install_places()
            name = 'codex.exe' if platform == 'win32' else 'codex'
            self.assertIn(os.path.join(top, '.local', 'bin', name), places)
        nvm = self.make_file(top, '.nvm', 'versions', 'node', 'v22.1.0',
                             'bin', 'codex')
        with mock.patch.object(codex.sys, 'platform', 'linux'),                 mock.patch.object(codex.os.path, 'expanduser',
                                  return_value=top):
            self.assertIn(nvm, codex._install_places())

    def test_not_installed(self):
        provider = providers.Codex(store=memory_store(), prefs={})
        self.assertIsNone(provider.auth())
        self.assertEqual('Not set up.', provider.status())
        with self.assertRaises(providers.AuthError) as caught:
            provider.models()
        self.assertIn('not installed', str(caught.exception))


class CodexSettingsTests(unittest.TestCase):

    setUp = SettingsDialogTests.setUp
    make_dialog = SettingsDialogTests.make_dialog
    tearDown = SettingsDialogTests.tearDown
    box = SettingsDialogTests.box

    def test_codex_has_no_api_key_and_points_to_the_install(self):
        box = self.box('codex')
        self.assertEqual('Install Codex to Sign In', box.web_button.text())
        self.assertTrue(box.key_edit.isHidden())
        self.assertFalse(box.locate_button.isHidden())
        with mock.patch('nxt_editor.ai.settings_dialog.open_url') as opened:
            box.sign_in()
        opened.assert_called_once_with(codex.INSTALL_URL)
        self.assertNotIn('API key', box.status_label.text())

    def test_codex_signs_in_without_a_code_to_paste(self):
        box = self.box('codex')
        login = mock.Mock(spec=['url', 'wait', 'cancel'],
                          url='https://auth.openai.com/oauth/authorize')
        started = threading.Event()

        def finish(lg, cancelled=None):
            started.set()
            cancelled.wait(5)
            return None
        with mock.patch.object(providers.Codex, 'cli', 'codex'), \
                mock.patch.object(providers.Codex, 'start_sign_in',
                                  return_value=login), \
                mock.patch.object(providers.Codex, 'finish_sign_in',
                                  side_effect=finish), \
                mock.patch.object(codex, 'signed_in', return_value=None):
            box.refresh()
            self.assertEqual('Sign in with Codex', box.web_button.text())
            box.sign_in()
            wait_for(started.is_set)
            self.assertTrue(box.wait_dialog.paste_widget.isHidden())
            self.assertIn('ChatGPT', box.wait_dialog.label.text())
            box.wait_dialog.reject()
            box.thread.wait(2000)

    def test_the_storage_line_says_when_the_keyring_failed(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        self.dialog.done(0)
        self.store = secret_store.SecretStore(
            FailingBackend(), fallback=secret_store._FileBackend(
                os.path.join(folder, 'ai.json')))
        self.dialog = self.make_dialog()
        box = self.box('openai')
        box.key_edit.setText('sk-new')
        with mock.patch.object(box, 'check'):
            box.save_key()
        self.assertIn('could not save', self.dialog.store_label.text())
        self.assertIn('private file', self.dialog.store_label.text())
        self.assertEqual('sk-new', box.provider.saved_api_key())


class MainWindowTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from nxt_editor.main_window import MainWindow
        cls.win = MainWindow()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win.deleteLater()
        app.processEvents()
        cls.win = None

    def window_menu_texts(self):
        self.win.menu_bar.populate_window_menu()
        return [a.text() for a in self.win.menu_bar.window_menu.actions()]

    def test_the_options_menu_has_the_settings(self):
        action = self.win.app_actions.ai_settings_action
        self.assertIn(action, self.win.menu_bar.options_menu.actions())

    def test_the_panel_is_only_in_the_window_menu_when_turned_on(self):
        target = 'nxt_editor.main_window.ai_providers.is_enabled'
        with mock.patch(target, return_value=False):
            self.assertNotIn('AI Assistant', self.window_menu_texts())
        with mock.patch(target, return_value=True):
            self.assertIn('AI Assistant', self.window_menu_texts())

    def test_turning_it_on_shows_the_panel(self):
        self.win.on_ai_enabled_changed(True)
        self.assertFalse(self.win.ai_assistant.isHidden())
        self.win.on_ai_enabled_changed(False)
        self.assertTrue(self.win.ai_assistant.isHidden())


if __name__ == '__main__':
    unittest.main()
