"""The assistant's tools, the MCP server Claude Code uses them through, and
each provider's own way of using them.

Nothing here reaches the network: provider requests are caught and
answered as each provider would, and the MCP server is only spoken to from
this computer.
"""
# Builtin
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

# External
from Qt import QtCore, QtWidgets

# Internal
from nxt.session import Session
from nxt_editor import stage_model
from nxt_editor.ai import (claude_code, mcp_server, providers, tools,
                           web)
from nxt_editor.ai.memory import Memory
from nxt_editor.test.test_ai_assistant import (PREF, FakeProvider, app,
                                               memory_store, sse, wait_for)

GRAPH = {
    'version': '1.17', 'alias': 'top',
    'nodes': {
        '/init': {'start_point': True, 'code': ['print("init", self.side)'],
                  'attrs': {'side': {'value': 'L'}},
                  'comment': 'Starts the rig'},
        '/rig': {'execute_in': '/init', 'attrs': {'scale': {'value': '2'}},
                 'code': ['import math', 'value = math.pi']},
        '/rig/arm_ctrl': {'attrs': {'color': {'value': 'red'}}},
        '/rig/leg_ctrl': {'instance': '/rig/arm_ctrl'},
        '/broken': {'execute_in': '/nowhere'},
        '/fails': {'code': ['print("before")', 'raise ValueError("boom")']},
    },
}


class GraphCase(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='nxt_tools_')
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        path = os.path.join(self.folder, 'top.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.model = stage_model.StageModel(Session().load_file(
            filepath=path))
        self.box = self.toolbox()

    def toolbox(self, can_edit=True, can_run=True):
        box = tools.Toolbox(self.model, can_edit=can_edit, can_run=can_run,
                            memory=Memory({}))
        self.steps = []
        box.activity.connect(self.steps.append)
        return box

    def call(self, name, **args):
        text, failed = self.box.call(name, args)
        self.assertFalse(failed, text)
        try:
            return json.loads(text)
        except ValueError:
            return text

    def nodes(self):
        return sorted(self.model.comp_layer.descendants('/'))


class LookingTests(GraphCase):

    def test_the_overview(self):
        self.model.set_selection(['/rig'])
        seen = self.call('get_graph_overview')
        self.assertEqual(['top'], [l['alias'] for l in seen['layers']])
        self.assertTrue(seen['layers'][0]['target'])
        self.assertEqual(['/init'], seen['start_points'])
        self.assertEqual(['/rig'], seen['selected'])
        self.assertIn('/rig', [n['path'] for n in seen['top_level_nodes']])
        self.assertEqual(6, seen['node_count'])

    def test_listing_nodes(self):
        text = self.call('list_nodes', path='/', depth=2)
        self.assertIn('/rig/arm_ctrl', text)
        self.assertIn('/init  [start point]', text)
        self.assertIn('instance of /rig/arm_ctrl', text)
        self.assertNotIn('/rig/arm_ctrl', self.call('list_nodes', depth=1))
        self.assertIn('and 3 more', self.call('list_nodes', depth=2,
                                              limit=3))

    def test_reading_a_node(self):
        node = self.call('get_node', path='/rig/leg_ctrl')
        self.assertEqual({'value': 'red', 'from': 'instance'},
                         node['attrs']['color'])
        self.assertIn('instance of /rig/arm_ctrl', node['flags'])
        init = self.call('get_node', path='init')
        self.assertEqual('print("init", self.side)', init['code'])
        self.assertEqual('Starts the rig', init['comment'])
        self.assertEqual('local', init['attrs']['side']['from'])
        text, failed = self.box.call('get_node', {'path': '/nope'})
        self.assertTrue(failed)
        self.assertIn('There is no node /nope', text)

    def test_searching(self):
        self.assertIn('/rig/arm_ctrl', self.call('find_nodes', text='*ctrl'))
        hits = self.call('find_nodes', text='math.pi')
        self.assertIn('/rig  (code line 2: value = math.pi)', hits)
        self.assertIn('attr color',
                      self.call('find_nodes', text='RED', where=['attrs']))
        self.assertEqual('Nothing matched.',
                         self.call('find_nodes', text='zebra'))

    def test_the_build_order_and_problems(self):
        order = self.call('get_build_order')
        self.assertEqual('/init', order['start'])
        self.assertEqual(['/init', '/rig'], order['order'][:2])
        problems = self.call('find_problems')
        self.assertIn('/broken', problems)

    def test_selecting_frames_the_nodes(self):
        framed = []
        self.model.frame_items.connect(framed.append)
        text = self.call('select_nodes', paths=['/rig', '/missing'])
        self.assertEqual(['/rig'], list(self.model.selection))
        self.assertEqual([('/rig',)], framed)
        self.assertIn('Not found: /missing', text)

    def test_each_step_is_told_to_the_panel(self):
        self.call('get_node', path='/rig')
        self.assertEqual(['running', 'done'],
                         [s['state'] for s in self.steps])
        self.assertEqual('Read /rig', self.steps[-1]['label'])
        self.assertEqual('read', self.steps[-1]['kind'])


class ChangingTests(GraphCase):

    def test_changes_are_made(self):
        text = self.call('change_graph', changes=[
            {'action': 'add_node', 'path': '/new/child',
             'attrs': {'a': 1}},
            {'action': 'set_code', 'path': '/rig', 'code': 'x = 1'}])
        self.assertIn('Done: Made /new/child', text)
        self.assertIn('/new/child', self.nodes())
        self.assertEqual(['Made /new/child', 'Set the code of /rig'],
                         self.box.done)

    def test_a_reply_is_one_undo_step(self):
        before = self.nodes()
        self.call('change_graph', changes=[{'action': 'add_node',
                                            'path': '/one'}])
        self.call('change_graph', changes=[{'action': 'add_node',
                                            'path': '/two'}])
        self.box.finish()
        self.assertIn('/two', self.nodes())
        self.model.undo_stack.undo()
        self.assertEqual(before, self.nodes())

    def test_what_could_not_be_done_is_said(self):
        text = self.call('change_graph', changes=[
            {'action': 'set_code', 'path': '/nope', 'code': 'x'}])
        self.assertIn('Could not: There is no node /nope', text)
        self.box.finish()

    def test_changing_needs_edit_graph(self):
        self.box = self.toolbox(can_edit=False, can_run=False)
        names = [t.name for t in self.box.available()]
        self.assertIn('get_node', names)
        self.assertIn('select_nodes', names)
        self.assertNotIn('change_graph', names)
        self.assertNotIn('run_build', names)
        text, failed = self.box.call('change_graph', {'changes': [
            {'action': 'add_node', 'path': '/sneaky'}]})
        self.assertTrue(failed)
        self.assertIn('Edit graph', text)
        self.assertNotIn('/sneaky', self.nodes())
        text, failed = self.box.call('run_nodes', {'paths': ['/init']})
        self.assertTrue(failed)
        self.assertIn('Run code', text)

    def test_no_graph_no_graph_tools(self):
        names = [t.name for t in tools.Toolbox(
            None, memory=Memory({})).available()]
        self.assertNotIn('get_node', names)
        self.assertIn('read_file', names)
        self.assertIn('inspect_import', names)


class RunningTests(GraphCase):

    def test_running_nodes_gives_back_what_they_printed(self):
        result = self.call('run_nodes', paths=['/init'])
        self.assertEqual('finished', result['state'])
        self.assertIn('init L', result['printed'])
        self.assertNotIn('errors', result)

    def test_an_error_is_given_back(self):
        result = self.call('run_nodes', paths=['/fails'])
        self.assertIn('before', result['printed'])
        self.assertTrue(any('boom' in e for e in result['errors']))

    def test_running_the_build(self):
        result = self.call('run_build')
        self.assertEqual('finished', result['state'])
        self.assertIn('init L', result['printed'])

    def test_running_a_snippet_as_a_node(self):
        result = self.call('run_snippet', code='print("side is", self.side)',
                           node='/init')
        self.assertIn('side is L', result['printed'])

    def test_the_log_is_there_to_read(self):
        self.call('run_nodes', paths=['/fails'])
        self.assertIn('boom', self.call('get_output_log', errors_only=True))


class MainThreadTests(GraphCase):

    def test_a_call_from_another_thread_runs_on_the_main_thread(self):
        seen = []
        real = self.box.tools['get_node'].handler

        def where(args):
            seen.append(QtCore.QThread.currentThread() is app.thread())
            return real(args)

        self.box.tools['get_node'].handler = where
        answers = []
        worker = threading.Thread(target=lambda: answers.append(
            self.box.call('get_node', {'path': '/rig'})))
        worker.start()
        wait_for(lambda: answers)
        worker.join(5)
        self.assertEqual([True], seen)
        self.assertFalse(answers[0][1])

    def test_a_stopped_reply_uses_no_more_tools(self):
        self.box.cancel()
        text, failed = self.box.call('get_node', {'path': '/rig'})
        self.assertTrue(failed)


class McpServerTests(GraphCase):

    def setUp(self):
        super(McpServerTests, self).setUp()
        self.server = mcp_server.McpServer()
        self.addCleanup(self.server.stop)
        self.token = self.server.open(self.box)

    def post(self, body, token=None, origin=None):
        """Sent from a thread, as Claude Code would, while this one keeps
        the editor going."""
        headers = {'Content-Type': 'application/json',
                   'Accept': 'application/json, text/event-stream'}
        if token is not False:
            headers['Authorization'] = 'Bearer ' + (token or self.token)
        if origin:
            headers['Origin'] = origin
        request = urllib.request.Request(
            self.server.url, data=json.dumps(body).encode('utf-8'),
            headers=headers, method='POST')
        answer = []

        def send():
            try:
                with urllib.request.urlopen(request, timeout=10) as reply:
                    data = reply.read()
                    answer.append((reply.status,
                                   json.loads(data) if data else None))
            except urllib.error.HTTPError as err:
                answer.append((err.code, None))

        threading.Thread(target=send).start()
        wait_for(lambda: answer, timeout=10)
        return answer[0]

    def rpc(self, method, params=None, msg_id=1):
        return self.post({'jsonrpc': '2.0', 'id': msg_id, 'method': method,
                          'params': params or {}})

    def test_claude_code_can_start_list_and_call(self):
        status, body = self.rpc('initialize', {
            'protocolVersion': '2025-06-18', 'capabilities': {},
            'clientInfo': {'name': 'claude-code', 'version': '2'}})
        self.assertEqual(200, status)
        self.assertEqual('2025-06-18', body['result']['protocolVersion'])
        self.assertEqual('nxt', body['result']['serverInfo']['name'])
        self.assertEqual(202, self.post({
            'jsonrpc': '2.0', 'method': 'notifications/initialized'})[0])
        names = [t['name'] for t in
                 self.rpc('tools/list')[1]['result']['tools']]
        self.assertIn('change_graph', names)
        self.assertIn('inputSchema', self.rpc('tools/list')[1]['result'][
            'tools'][0])
        result = self.rpc('tools/call', {'name': 'get_node',
                                         'arguments': {'path': '/rig'}})[1]
        self.assertFalse(result['result']['isError'])
        self.assertIn('math.pi', result['result']['content'][0]['text'])
        result = self.rpc('tools/call', {'name': 'change_graph',
                                         'arguments': {'changes': [{
                                             'action': 'add_node',
                                             'path': '/from_mcp'}]}})[1]
        self.assertIn('/from_mcp', self.nodes())
        self.box.finish()

    def test_a_tool_that_fails_says_so(self):
        result = self.rpc('tools/call', {'name': 'get_node',
                                         'arguments': {'path': '/no'}})[1]
        self.assertTrue(result['result']['isError'])

    def test_an_unknown_method(self):
        self.assertEqual(-32601, self.rpc('nope')[1]['error']['code'])

    def test_only_with_the_replys_key(self):
        self.assertEqual(401, self.post({'jsonrpc': '2.0', 'id': 1,
                                         'method': 'ping'}, token=False)[0])
        self.assertEqual(401, self.post({'jsonrpc': '2.0', 'id': 1,
                                         'method': 'ping'},
                                        token='guess')[0])
        self.server.close(self.token)
        self.assertEqual(401, self.rpc('ping')[0])

    def test_not_from_a_web_page(self):
        self.assertEqual(403, self.post({'jsonrpc': '2.0', 'id': 1,
                                         'method': 'ping'},
                                        origin='https://evil.example')[0])
        self.assertEqual(200, self.post({'jsonrpc': '2.0', 'id': 1,
                                         'method': 'ping'},
                                        origin='http://localhost:3000')[0])

    def test_a_dropped_connection_is_not_an_error(self):
        server = self.server._server
        with mock.patch.object(mcp_server.logger, 'exception') as noisy:
            try:
                raise ConnectionResetError(10054, 'forcibly closed')
            except ConnectionResetError:
                server.handle_error(None, ('127.0.0.1', 1))
            noisy.assert_not_called()
            try:
                raise ValueError('a real problem')
            except ValueError:
                server.handle_error(None, ('127.0.0.1', 1))
            noisy.assert_called_once()

    def test_it_only_listens_on_this_computer(self):
        self.assertTrue(self.server.url.startswith('http://127.0.0.1:'))

    def test_the_config_for_claude_code(self):
        config = self.server.config(self.token)['mcpServers']['nxt']
        self.assertEqual('http', config['type'])
        self.assertEqual(self.server.url, config['url'])
        self.assertEqual('Bearer ' + self.token,
                         config['headers']['Authorization'])


class ClaudeCodeGetsTheTools(GraphCase):

    def test_the_editors_server_is_the_only_one(self):
        seen = {}

        class Process(object):
            def __init__(self, args, **kwargs):
                seen['args'] = args
                config = args[args.index('--mcp-config') + 1]
                with open(config) as fp:
                    seen['config'] = json.load(fp)
                self.stdin = mock.Mock()
                self.stdout = iter([json.dumps(
                    {'type': 'result', 'result': 'done'}).encode('utf-8')])

            def poll(self):
                return 0

        with mock.patch.object(claude_code.subprocess, 'Popen', Process):
            text = ''.join(claude_code.stream_chat(
                [{'role': 'user', 'content': 'hi'}], 'sys', cli='claude',
                tools=self.box))
        self.assertEqual('done', text)
        args = seen['args']
        self.assertIn('--strict-mcp-config', args)
        self.assertEqual('', args[args.index('--tools') + 1])
        self.assertEqual('mcp__nxt', args[args.index('--allowedTools') + 1])
        server = seen['config']['mcpServers']['nxt']
        self.assertTrue(server['url'].startswith('http://127.0.0.1:'))
        token = server['headers']['Authorization'][7:]
        # The key ends with the reply, and the config file is gone.
        self.assertIsNone(mcp_server.server().toolbox_for(token))
        self.assertFalse(os.path.exists(args[args.index('--mcp-config') +
                                             1]))

    def test_text_either_side_of_a_tool_is_kept_apart(self):
        def event(kind, **data):
            return json.dumps({'type': 'stream_event', 'event': dict(
                type=kind, **data)}).encode('utf-8')

        lines = [event('message_start'),
                 event('content_block_delta',
                       delta={'type': 'text_delta', 'text': 'Looking.'}),
                 event('message_start'),
                 event('content_block_delta',
                       delta={'type': 'text_delta', 'text': 'Found it.'}),
                 json.dumps({'type': 'result', 'result': ''}).encode()]

        class Process(object):
            def __init__(self, args, **kwargs):
                self.stdin = mock.Mock()
                self.stdout = iter(lines)

            def poll(self):
                return 0

        with mock.patch.object(claude_code.subprocess, 'Popen', Process):
            text = ''.join(claude_code.stream_chat(
                [{'role': 'user', 'content': 'hi'}], 'sys', cli='claude'))
        self.assertEqual('Looking.\n\nFound it.', text)


class ProviderToolLoops(GraphCase):
    """Each provider asks for a tool, gets the answer and finishes."""

    def setUp(self):
        super(ProviderToolLoops, self).setUp()
        self.store = memory_store()
        self.prefs = {}
        self.bodies = []

    def provider(self, cls):
        provider = cls(store=self.store, prefs=self.prefs)
        provider.save_api_key('test-key')
        return provider

    def replies(self, *answers):
        answers = list(answers)

        def request(url, data=None, **kwargs):
            self.bodies.append(json.loads(json.dumps(data)))
            return answers.pop(0)
        return mock.patch.object(web, 'request', side_effect=request)

    def test_claude_with_an_api_key(self):
        first = sse(
            ('content_block_start', {'type': 'content_block_start',
                                     'index': 0, 'content_block': {
                                         'type': 'text', 'text': ''}}),
            ('content_block_delta', {'type': 'content_block_delta',
                                     'index': 0, 'delta': {
                                         'type': 'text_delta',
                                         'text': 'Looking.'}}),
            ('content_block_start', {'type': 'content_block_start',
                                     'index': 1, 'content_block': {
                                         'type': 'tool_use', 'id': 'tu_1',
                                         'name': 'get_node', 'input': {}}}),
            ('content_block_delta', {'type': 'content_block_delta',
                                     'index': 1, 'delta': {
                                         'type': 'input_json_delta',
                                         'partial_json': '{"path": "/r'}}),
            ('content_block_delta', {'type': 'content_block_delta',
                                     'index': 1, 'delta': {
                                         'type': 'input_json_delta',
                                         'partial_json': 'ig"}'}}),
            ('message_delta', {'type': 'message_delta',
                               'delta': {'stop_reason': 'tool_use'}}),
            ('message_stop', {'type': 'message_stop'}))
        second = sse(
            ('content_block_delta', {'type': 'content_block_delta',
                                     'index': 0, 'delta': {
                                         'type': 'text_delta',
                                         'text': 'It uses math.'}}),
            ('message_delta', {'type': 'message_delta',
                               'delta': {'stop_reason': 'end_turn'}}),
            ('message_stop', {'type': 'message_stop'}))
        claude = self.provider(providers.Anthropic)
        with self.replies(first, second):
            text = ''.join(claude.stream_chat(
                [{'role': 'user', 'content': 'What is /rig?'}], 'sys',
                model='claude-x', tools=self.box))
        self.assertEqual('Looking.\n\nIt uses math.', text)
        self.assertIn('get_node',
                      [t['name'] for t in self.bodies[0]['tools']])
        said, results = self.bodies[1]['messages'][-2:]
        self.assertEqual({'type': 'tool_use', 'id': 'tu_1',
                          'name': 'get_node', 'input': {'path': '/rig'}},
                         said['content'][1])
        self.assertEqual('tu_1', results['content'][0]['tool_use_id'])
        self.assertIn('math.pi', results['content'][0]['content'])
        self.assertFalse(results['content'][0]['is_error'])

    def test_openai(self):
        call = {'type': 'function_call', 'id': 'fc_1', 'call_id': 'call_1',
                'name': 'find_nodes', 'arguments': '{"text": "ctrl"}',
                'status': 'completed'}
        first = sse(('response.output_item.done',
                     {'type': 'response.output_item.done',
                      'item': {'type': 'reasoning', 'id': 'rs_1'}}),
                    ('response.output_item.done',
                     {'type': 'response.output_item.done', 'item': call}),
                    ('response.completed', {'type': 'response.completed'}))
        second = sse(('response.output_text.delta',
                      {'type': 'response.output_text.delta',
                       'delta': 'Two controls.'}),
                     ('response.completed', {'type': 'response.completed'}))
        openai = self.provider(providers.OpenAI)
        with self.replies(first, second):
            text = ''.join(openai.stream_chat(
                [{'role': 'user', 'content': 'Controls?'}], 'sys',
                model='gpt', tools=self.box))
        self.assertEqual('Two controls.', text)
        tool = self.bodies[0]['tools'][0]
        self.assertEqual('function', tool['type'])
        self.assertIn('parameters', tool)
        sent = self.bodies[1]['input']
        self.assertFalse(self.bodies[1]['store'])
        self.assertEqual({'type': 'function_call', 'call_id': 'call_1',
                          'name': 'find_nodes',
                          'arguments': '{"text": "ctrl"}'}, sent[1])
        self.assertEqual('function_call_output', sent[2]['type'])
        self.assertEqual('call_1', sent[2]['call_id'])
        self.assertIn('/rig/arm_ctrl', sent[2]['output'])
        self.assertNotIn('reasoning', [i.get('type') for i in sent])

    def test_grok_and_local_models(self):
        first = sse((None, {'choices': [{'delta': {'tool_calls': [
            {'index': 0, 'id': 'c1', 'function': {
                'name': 'change_graph', 'arguments': '{"changes": [{"act'}}
        ]}}]}),
            (None, {'choices': [{'delta': {'tool_calls': [
                {'index': 0, 'function': {
                    'arguments': 'ion": "add_node", "path": "/grok"}]}'}}
            ]}, 'finish_reason': 'tool_calls'}]}),
            (None, '[DONE]'))
        second = sse((None, {'choices': [{'delta': {'content': 'Made it.'}}]}),
                     (None, '[DONE]'))
        grok = self.provider(providers.XAI)
        with self.replies(first, second):
            text = ''.join(grok.stream_chat(
                [{'role': 'user', 'content': 'Make /grok'}], 'sys',
                model='grok', tools=self.box))
        self.box.finish()
        self.assertEqual('Made it.', text)
        self.assertIn('/grok', self.nodes())
        self.assertEqual('function', self.bodies[0]['tools'][0]['type'])
        sent = self.bodies[1]['messages']
        self.assertEqual('c1', sent[-2]['tool_calls'][0]['id'])
        self.assertEqual({'role': 'tool', 'tool_call_id': 'c1'},
                         {k: sent[-1][k] for k in ('role', 'tool_call_id')})
        self.assertIn('Made /grok', sent[-1]['content'])

    def test_a_model_without_tools_says_so(self):
        refused = web.WebError('registry.ollama.ai/library/tiny does not '
                               'support tools', status=400)
        local = providers.Local(store=self.store, prefs=self.prefs)
        local.base_url = 'http://localhost:11434'
        with mock.patch.object(web, 'request', side_effect=refused):
            with self.assertRaises(providers.ToolsUnsupported):
                list(local.stream_chat([{'role': 'user', 'content': 'hi'}],
                                       'sys', model='tiny', tools=self.box))

    def test_other_errors_are_not_mistaken_for_it(self):
        refused = web.WebError('Bad key', status=401)
        grok = self.provider(providers.XAI)
        with mock.patch.object(web, 'request', side_effect=refused):
            with self.assertRaises(web.WebError):
                list(grok.stream_chat([{'role': 'user', 'content': 'hi'}],
                                      'sys', model='g', tools=self.box))

    def test_no_tools_sends_none(self):
        reply = sse((None, {'choices': [{'delta': {'content': 'Hi'}}]}),
                    (None, '[DONE]'))
        grok = self.provider(providers.XAI)
        with self.replies(reply):
            ''.join(grok.stream_chat([{'role': 'user', 'content': 'hi'}],
                                     'sys', model='g'))
        self.assertNotIn('tools', self.bodies[0])


class ToolUser(FakeProvider):
    """Uses the tools the way a provider does, then answers."""
    script = ()

    def stream_chat(self, messages, system, model=None, auth=None,
                    tools=None):
        self.tools = tools
        for name, args in self.script:
            tools.call(name, args)
        yield 'All done.'


class PanelShowsTheTools(unittest.TestCase):

    def setUp(self):
        from nxt_editor.dockwidgets.ai_assistant import AiAssistant
        self.folder = tempfile.mkdtemp(prefix='nxt_tools_')
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        path = os.path.join(self.folder, 'top.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.model = stage_model.StageModel(Session().load_file(
            filepath=path))
        self.store = memory_store()
        self.prefs = {PREF.AI_ENABLED: True}
        self.fake = ToolUser(store=self.store, prefs=self.prefs)
        self.fake.save_api_key('k')
        patcher = mock.patch.object(providers, 'get_provider',
                                    side_effect=lambda *a, **k: self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        providers._models.clear()
        self.panel = AiAssistant(store=self.store, prefs=self.prefs)
        wait_for(lambda: self.panel.model_combo.count())
        self.panel.set_stage_model(self.model)

    def tearDown(self):
        self.panel.stop()
        if self.panel.thread:
            self.panel.thread.wait(5000)
        self.panel.deleteLater()
        app.processEvents()

    def ask(self, text):
        self.panel.send(text)
        wait_for(lambda: not self.panel.busy and self.panel.messages and
                 self.panel.messages[-1]['role'] == 'assistant')

    def nodes(self):
        return sorted(self.model.comp_layer.descendants('/'))

    def test_the_steps_are_shown_and_kept(self):
        self.fake.script = [
            ('get_node', {'path': '/rig'}),
            ('change_graph', {'changes': [{'action': 'add_node',
                                           'path': '/made'}]}),
            ('get_node', {'path': '/missing'})]
        self.ask('Look and make')
        reply = self.panel.messages[-1]
        self.assertEqual(['Read /rig', 'Changed the graph (1 change)',
                          'Read /missing'],
                         [s['label'] for s in reply['tools']])
        self.assertEqual(['done', 'done', 'failed'],
                         [s['state'] for s in reply['tools']])
        self.assertEqual(['Made /made'], reply['done'])
        shown = self.panel.transcript.toPlainText()
        for text in ('Read /rig', 'Changed the graph (1 change)',
                     'There is no node /missing', 'Made /made',
                     'All done.'):
            self.assertIn(text, shown)
        saved = self.panel.chat_store.load(self.panel.chat_id)
        self.assertEqual(reply['tools'], saved['messages'][-1]['tools'])

    def test_a_whole_reply_is_one_undo_step(self):
        before = self.nodes()
        self.fake.script = [
            ('change_graph', {'changes': [{'action': 'add_node',
                                           'path': '/one'}]}),
            ('change_graph', {'changes': [{'action': 'add_node',
                                           'path': '/two'}]})]
        self.ask('Make two')
        self.assertIn('/two', self.nodes())
        self.model.undo_stack.undo()
        self.assertEqual(before, self.nodes())

    def test_the_toggles_decide_what_it_may_do(self):
        self.panel.edit_check.setChecked(False)
        self.panel.run_check.setChecked(True)
        self.assertTrue(self.prefs[PREF.AI_ALLOW_RUNS])
        self.ask('Hi')
        names = [t.name for t in self.fake.tools.available()]
        self.assertNotIn('change_graph', names)
        self.assertIn('run_nodes', names)
        self.panel.run_check.setChecked(False)
        self.ask('Again')
        names = [t.name for t in self.fake.tools.available()]
        self.assertNotIn('run_nodes', names)

    def test_running_code_is_off_until_turned_on(self):
        self.assertFalse(self.panel.run_check.isChecked())


if __name__ == '__main__':
    unittest.main()
