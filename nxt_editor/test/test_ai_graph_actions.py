"""The AI assistant changing the graph: nodes, hierarchies, code, layers.

Replies carry a fenced nxt-actions block of JSON. These run the actions
against a real stage model, the way the panel does after a reply.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

# External
from Qt import QtWidgets

# Internal
from nxt.session import Session
from nxt_editor import stage_model, user_dir
from nxt_editor.ai import claude_code, graph_actions, providers, secret_store

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def block(*actions):
    return 'Done.\n```nxt-actions\n{}\n```'.format(json.dumps(list(actions)))


class GraphTestCase(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.top = os.path.join(self.folder, 'top.nxt')
        with open(self.top, 'w') as f:
            json.dump({'version': '1.17', 'alias': 'top',
                       'nodes': {'/existing': {}}}, f)
        with open(os.path.join(self.folder, 'other.nxt'), 'w') as f:
            json.dump({'version': '1.17', 'alias': 'other',
                       'nodes': {'/from_other': {}}}, f)
        self.model = stage_model.StageModel(
            Session().load_file(filepath=self.top))

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def apply(self, *actions):
        return graph_actions.Applier(self.model).apply(list(actions))

    def nodes(self):
        return sorted(self.model.comp_layer.descendants('/'))

    def code(self, path):
        return self.model.get_node_code_string(path,
                                               layer=self.model.comp_layer)

    def attr(self, path, name):
        return self.model.get_node_attr_value(path, name,
                                              layer=self.model.comp_layer)

    def aliases(self):
        return [l.get_alias() for l in self.model.stage._sub_layers]


class ReadingReplies(unittest.TestCase):

    def test_actions_are_found_in_a_reply(self):
        actions, problems = graph_actions.find_actions(
            block({'action': 'add_node', 'path': '/a'}))
        self.assertEqual([{'action': 'add_node', 'path': '/a'}], actions)
        self.assertEqual([], problems)

    def test_an_object_with_actions_is_read_too(self):
        text = '```nxt-actions\n{"actions": [{"action": "select"}]}\n```'
        actions, _ = graph_actions.find_actions(text)
        self.assertEqual('select', actions[0]['action'])

    def test_broken_json_is_reported_not_applied(self):
        actions, problems = graph_actions.find_actions(
            '```nxt-actions\n[{"action": \n```')
        self.assertEqual([], actions)
        self.assertEqual(1, len(problems))

    def test_a_plain_reply_has_no_actions(self):
        self.assertEqual(([], []), graph_actions.find_actions(
            'Here is code:\n```python\nprint(1)\n```'))

    def test_the_block_is_swapped_for_what_it_did(self):
        text = graph_actions.without_actions(
            block({'action': 'add_node', 'path': '/a'}), 'Made /a')
        self.assertEqual('Done.\nMade /a', text)

    def test_the_instructions_say_it_can_not_write_files(self):
        self.assertIn('Never say you wrote or saved a file',
                      graph_actions.instructions())


class MakingNodes(GraphTestCase):

    def test_one_path_makes_the_whole_hierarchy(self):
        done, failed = self.apply({'action': 'add_node',
                                   'path': '/rig/arm/shoulder'})
        self.assertEqual([], failed)
        for path in ('/rig', '/rig/arm', '/rig/arm/shoulder'):
            self.assertIn(path, self.nodes())

    def test_code_attrs_and_comment_go_on_the_node(self):
        self.apply({'action': 'add_node', 'path': '/a',
                    'code': 'print(self.side)\nprint(2)',
                    'attrs': {'side': 'L', 'count': 3, 'list': [1, 2]},
                    'comment': 'hello'})
        self.assertEqual('print(self.side)\nprint(2)', self.code('/a'))
        self.assertEqual('L', self.attr('/a', 'side'))
        self.assertEqual('3', str(self.attr('/a', 'count')))
        self.assertEqual('hello', self.model.get_node_comment('/a'))

    def test_a_node_that_is_there_is_updated(self):
        done, _ = self.apply({'action': 'add_node', 'path': '/existing',
                              'code': 'x = 1'})
        self.assertEqual(['Updated /existing'], done)
        self.assertEqual('x = 1', self.code('/existing'))
        self.assertEqual(1, self.nodes().count('/existing'))

    def test_instances_inherit_children(self):
        self.apply({'action': 'add_node', 'path': '/src/child'},
                   {'action': 'add_node', 'path': '/inst',
                    'instance': '/src'})
        self.assertEqual('/src', self.model.get_node_instance_path(
            '/inst', layer=self.model.comp_layer))
        self.assertIn('/inst/child', self.nodes())

    def test_run_order_and_start_points(self):
        self.apply({'action': 'add_node', 'path': '/setup',
                    'start_point': True},
                   {'action': 'add_node', 'path': '/build',
                    'exec_in': '/setup'})
        self.assertEqual('/setup', self.model.get_node_exec_in('/build'))
        self.assertTrue(self.model.get_is_node_start('/setup'))

    def test_new_top_level_nodes_do_not_pile_up(self):
        self.apply({'action': 'add_node', 'path': '/one'},
                   {'action': 'add_node', 'path': '/two'})
        self.assertNotEqual(self.model.get_node_pos('/one'),
                            self.model.get_node_pos('/two'))


class ChangingNodes(GraphTestCase):

    def setUp(self):
        super(ChangingNodes, self).setUp()
        self.apply({'action': 'add_node', 'path': '/a/b', 'code': 'old',
                    'attrs': {'n': '1'}},
                   {'action': 'add_node', 'path': '/a/c'})
        self.model.undo_stack.clear()

    def test_set_code_and_attr(self):
        _, failed = self.apply(
            {'action': 'set_code', 'path': '/a/b', 'code': 'new'},
            {'action': 'set_attr', 'path': '/a/b', 'name': 'n',
             'value': '2'},
            {'action': 'set_attr', 'path': '/a/b', 'name': 'fresh',
             'value': 'yes'})
        self.assertEqual([], failed)
        self.assertEqual('new', self.code('/a/b'))
        self.assertEqual('2', self.attr('/a/b', 'n'))
        self.assertEqual('yes', self.attr('/a/b', 'fresh'))

    def test_rename_then_use_the_new_name(self):
        _, failed = self.apply(
            {'action': 'rename_node', 'path': '/a/b', 'name': 'bee'},
            {'action': 'set_code', 'path': '/a/b', 'code': 'still found'})
        self.assertEqual([], failed)
        self.assertIn('/a/bee', self.nodes())
        self.assertEqual('still found', self.code('/a/bee'))

    def test_reparent_and_order(self):
        self.apply({'action': 'set_parent', 'path': '/a/c',
                    'parent': '/elsewhere'},
                   {'action': 'add_node', 'path': '/a/d'},
                   {'action': 'set_child_order', 'path': '/a',
                    'children': ['d', 'b']})
        self.assertIn('/elsewhere/c', self.nodes())
        self.assertEqual(['d', 'b'], self.model.get_node_child_order('/a'))

    def test_attrs_are_renamed_and_deleted(self):
        self.apply({'action': 'rename_attr', 'path': '/a/b', 'name': 'n',
                    'new_name': 'm'})
        self.assertEqual('1', self.attr('/a/b', 'm'))
        self.apply({'action': 'delete_attr', 'path': '/a/b', 'name': 'm'})
        self.assertFalse(self.model.node_attr_exists(
            '/a/b', 'm', layer=self.model.comp_layer))

    def test_enable_duplicate_and_delete(self):
        done, failed = self.apply(
            {'action': 'set_enabled', 'path': '/a/b', 'value': False},
            {'action': 'duplicate_node', 'path': '/a/c'},
            {'action': 'delete_node', 'path': '/existing'})
        self.assertEqual([], failed)
        self.assertFalse(self.model.get_node_enabled('/a/b'))
        self.assertNotIn('/existing', self.nodes())
        self.assertEqual(3, len([p for p in self.nodes()
                                 if p.startswith('/a/')]))

    def test_select_shows_nodes(self):
        self.apply({'action': 'select', 'paths': ['/a/b', '/nope']})
        self.assertEqual(['/a/b'], list(self.model.selection))

    def test_a_missing_node_is_reported(self):
        done, failed = self.apply(
            {'action': 'set_code', 'path': '/nope', 'code': 'x'},
            {'action': 'add_node', 'path': '/still_made'})
        self.assertEqual(['There is no node /nope'], failed)
        self.assertEqual(['Made /still_made'], done)

    def test_an_unknown_action_is_reported(self):
        _, failed = self.apply({'action': 'format_disk'})
        self.assertEqual(['Unknown change "format_disk"'], failed)

    def test_everything_is_one_undo(self):
        self.apply({'action': 'add_node', 'path': '/x/y/z'},
                   {'action': 'set_code', 'path': '/a/b', 'code': 'new'},
                   {'action': 'delete_node', 'path': '/existing'})
        self.assertEqual(1, self.model.undo_stack.count())
        self.model.undo_stack.undo()
        self.assertNotIn('/x', self.nodes())
        self.assertIn('/existing', self.nodes())
        self.assertEqual('old', self.code('/a/b'))


class ChangingLayers(GraphTestCase):

    def test_a_new_layer_is_made_and_targeted(self):
        done, failed = self.apply(
            {'action': 'add_layer', 'file': 'anim', 'alias': 'anim'},
            {'action': 'add_node', 'path': '/on_anim'})
        self.assertEqual([], failed)
        self.assertEqual(['top', 'anim'], self.aliases())
        self.assertEqual('anim', self.model.target_layer.get_alias())
        anim = self.model.stage._sub_layers[1]
        self.assertIsNotNone(anim.lookup('/on_anim'))
        self.assertIsNone(self.model.top_layer.lookup('/on_anim'))

    def test_a_new_layer_does_not_overwrite_a_file(self):
        _, failed = self.apply({'action': 'add_layer', 'file': 'other.nxt'})
        self.assertEqual(['other.nxt is already there'], failed)

    def test_a_new_layer_stays_next_to_the_graph(self):
        _, failed = self.apply({'action': 'add_layer',
                                'file': '../elsewhere.nxt'})
        self.assertIn('next to the top layer', failed[0])

    def test_reference_rename_target_and_remove(self):
        _, failed = self.apply(
            {'action': 'reference_layer', 'file': 'other.nxt'},
            {'action': 'set_layer_alias', 'layer': 'other',
             'alias': 'renamed'},
            {'action': 'set_target_layer', 'layer': 'renamed'},
            {'action': 'add_node', 'path': '/on_other'})
        self.assertEqual([], failed)
        self.assertIn('/from_other', self.nodes())
        self.assertEqual('renamed', self.model.target_layer.get_alias())
        self.apply({'action': 'set_target_layer', 'layer': 'top'},
                   {'action': 'remove_layer', 'layer': 'renamed'})
        self.assertEqual(['top'], self.aliases())

    def test_mute_and_solo(self):
        self.apply({'action': 'reference_layer', 'file': 'other.nxt'})
        self.apply({'action': 'mute_layer', 'layer': 'other',
                    'value': True})
        other = self.model.stage._sub_layers[1]
        self.assertTrue(other.get_muted())
        self.apply({'action': 'mute_layer', 'layer': 'other',
                    'value': False},
                   {'action': 'solo_layer', 'layer': 'other',
                    'value': True})
        self.assertFalse(other.get_muted())
        self.assertTrue(other.get_soloed())

    def test_a_change_on_a_named_layer(self):
        self.apply({'action': 'reference_layer', 'file': 'other.nxt'})
        self.apply({'action': 'add_node', 'path': '/there',
                    'layer': 'other'})
        other = self.model.stage._sub_layers[1]
        self.assertIsNotNone(other.lookup('/there'))
        self.assertIsNone(self.model.top_layer.lookup('/there'))

    def test_the_top_layer_stays(self):
        _, failed = self.apply({'action': 'remove_layer', 'layer': 'top'})
        self.assertEqual(['The top layer can not be removed'], failed)

    def test_the_graph_is_described(self):
        self.apply({'action': 'add_node', 'path': '/a/b'})
        text = graph_actions.describe_graph(self.model)
        self.assertIn('top', text)
        self.assertIn('(target)', text)
        self.assertIn('/a/b', text)


class ReplyingProvider(providers.Provider):
    id = 'anthropic'
    label = 'Claude'
    env_var = 'ANTHROPIC_API_KEY'
    reply = ''

    def list_models(self, auth=None):
        return ['test-model']

    def stream_chat(self, messages, system, model=None, auth=None,
                    tools=None):
        self.sent = messages
        self.system = system
        self.tools = tools
        yield self.reply


class ThePanelChangesTheGraph(GraphTestCase):

    def setUp(self):
        super(ThePanelChangesTheGraph, self).setUp()
        from nxt_editor.dockwidgets.ai_assistant import AiAssistant
        cli = mock.patch.object(claude_code, 'find_cli', return_value=None)
        cli.start()
        self.addCleanup(cli.stop)
        providers._models.clear()
        self.store = secret_store.SecretStore(None)
        self.prefs = {user_dir.USER_PREF.AI_ENABLED: True}
        self.fake = ReplyingProvider(store=self.store, prefs=self.prefs)
        patcher = mock.patch.object(providers, 'get_provider',
                                    return_value=self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        env = mock.patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'k'})
        env.start()
        self.addCleanup(env.stop)
        self.panel = AiAssistant(store=self.store, prefs=self.prefs)
        self.panel.set_stage_model(self.model)
        self.wait(lambda: self.panel.model_combo.count())

    def tearDown(self):
        if self.panel.thread:
            self.panel.thread.wait(2000)
        self.panel.deleteLater()
        super(ThePanelChangesTheGraph, self).tearDown()

    @staticmethod
    def wait(condition, timeout=5):
        end = time.time() + timeout
        while not condition() and time.time() < end:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()

    def ask(self, text, reply):
        self.fake.reply = reply
        self.panel.send(text)
        self.wait(lambda: not self.panel.busy and self.panel.messages and
                  self.panel.messages[-1]['role'] == 'assistant')

    def test_a_reply_builds_the_hierarchy_live(self):
        self.ask('Make a rig', block(
            {'action': 'add_node', 'path': '/rig/arm/hand'}))
        self.assertIn('/rig/arm/hand', self.nodes())
        shown = self.panel.transcript.toPlainText()
        self.assertIn('Changed the graph', shown)
        self.assertIn('Made /rig/arm/hand', shown)
        self.assertNotIn('nxt-actions', shown)

    def test_it_is_given_the_tools(self):
        self.ask('Make a rig', 'ok')
        self.assertIn('change_graph', self.fake.system)
        self.assertNotIn('nxt-actions', self.fake.system)
        self.assertIn('change_graph',
                      [t.name for t in self.fake.tools.available()])

    def test_without_tools_it_is_told_how_and_what_is_there(self):
        asked = []

        def no_tools(messages, system, model=None, auth=None, tools=None):
            asked.append((system, tools))
            if tools is not None:
                raise providers.ToolsUnsupported('model does not support '
                                                 'tools')
            yield 'ok'

        self.fake.stream_chat = no_tools
        self.ask('Make a rig', 'ok')
        self.assertEqual(2, len(asked))
        system, offered = asked[1]
        self.assertIsNone(offered)
        self.assertIn('nxt-actions', system)
        self.assertIn('/existing', system)
        self.assertIn('can not use tools',
                      self.panel.transcript.toPlainText())

    def test_with_changes_off_nothing_changes(self):
        self.panel.edit_check.setChecked(False)
        self.assertFalse(self.prefs[user_dir.USER_PREF.AI_ALLOW_EDITS])
        self.ask('Make a rig', block(
            {'action': 'add_node', 'path': '/rig'}))
        self.assertNotIn('/rig', self.nodes())
        self.assertNotIn('nxt-actions', self.fake.system)
        self.assertIn('Edit graph', self.panel.transcript.toPlainText())

    def test_what_could_not_be_done_is_shown(self):
        self.ask('Change it', block(
            {'action': 'set_code', 'path': '/nope', 'code': 'x'}))
        self.assertIn('There is no node /nope',
                      self.panel.transcript.toPlainText())
        self.assertIn('could not be made', self.panel.status_label.text())


if __name__ == '__main__':
    unittest.main()
