"""Completion knows what a compute can use without importing it.

The world node runs first, into the globals every compute runs with, so
what it imports every node can use. nxt hands every compute STAGE, self,
nxt_path and the rest. A host keeps its own modules loaded. Inside a
${ token a node path is being written, and after its dot an attribute.

jedi, when it is installed, is asked once typing pauses or on Ctrl+Space,
and what it says for one spot is kept while more of the name is typed.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

# External
from Qt import QtGui, QtWidgets

# Internal
from nxt import DATA_STATE
from nxt.constants import NXT_DCC_ENV_VAR
from nxt_editor import user_dir
from nxt_editor.dockwidgets import code_completion

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

SOURCE_PREFS = (
    user_dir.USER_PREF.CE_COMPLETE_PYTHON,
    user_dir.USER_PREF.CE_COMPLETE_MODULES,
    user_dir.USER_PREF.CE_COMPLETE_NODE,
    user_dir.USER_PREF.CE_COMPLETE_DOCUMENT,
    user_dir.USER_PREF.CE_COMPLETE_HOST,
    user_dir.USER_PREF.CE_COMPLETE_JEDI,
)


def write_graph(path):
    data = {
        "version": "1.17", "alias": "completion", "mute": False,
        "solo": False, "meta_data": {},
        "nodes": {
            "/": {"code": ["import json"]},
            "/source": {"attrs": {"value": {"value": "42"},
                                  "label": {"value": "'source'"}}},
            "/reader": {"attrs": {"local": {"value": "7"}}, "code": [""]},
        },
    }
    with open(path, 'w') as file_object:
        json.dump(data, file_object, indent=4)


class CompletionNamespace(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='nxt_completion_')
        cls.graph = os.path.join(cls.tmp, 'completion.nxt')
        write_graph(cls.graph)
        cls.win = MainWindow(filepath=cls.graph)
        cls.ce = cls.win.code_editor
        cls.editor = cls.ce.editor
        cls.actions = cls.win.code_editor_actions
        cls.win.model.data_state = DATA_STATE.RAW
        cls.win.model.set_selection(['/reader'])
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.saved = {key: user_dir.user_prefs.get(key) for key in SOURCE_PREFS}
        for action, _pref, _default in self.actions.completion_source_actions:
            action.setChecked(True)
        self.load('x = ')

    def tearDown(self):
        self.editor.hide_completions()
        for key, value in self.saved.items():
            if value is None:
                try:
                    user_dir.user_prefs.pop(key)
                except KeyError:
                    pass
                continue
            user_dir.user_prefs[key] = value

    def load(self, text):
        self.editor.setReadOnly(False)
        self.ce.editing_active = True
        self.editor.setPlainText(text)
        cursor = self.editor.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.editor.setTextCursor(cursor)
        self.editor.invalidate_completion_words()

    def words(self):
        self.editor.invalidate_completion_words()
        return self.editor.build_completion_words()

    # -- the world node's imports ----------------------------------------

    def test_the_world_nodes_imports_count(self):
        self.assertIn('json', self.editor.imported_modules())
        self.assertIn('json.dumps', self.editor.module_completions('json.du'))

    # -- what every compute is given -------------------------------------

    def test_runtime_globals_are_words(self):
        words = self.words()
        for name in ('STAGE', 'self', 'nxt_path', 'ExitNode', 'ExitGraph'):
            self.assertIn(name, words)

    def test_inside_a_runtime_module(self):
        self.assertIn('nxt_path.WORLD',
                      self.editor.module_completions('nxt_path.WO'))

    # -- host modules ------------------------------------------------------

    def fake_maya(self):
        cmds = types.ModuleType('maya.cmds')
        cmds.ls = lambda *a, **k: []
        maya = types.ModuleType('maya')
        maya.cmds = cmds
        return mock.patch.dict(sys.modules, {'maya': maya,
                                             'maya.cmds': cmds})

    def test_a_hosts_loaded_modules_complete_without_an_import(self):
        with self.fake_maya(), \
                mock.patch.dict(os.environ, {NXT_DCC_ENV_VAR: 'maya'}):
            self.assertIn('cmds', self.words())
            self.assertIn('cmds.ls', self.editor.module_completions('cmds.l'))

    def test_a_host_module_that_is_not_loaded_is_not_imported(self):
        with mock.patch.dict(os.environ, {NXT_DCC_ENV_VAR: 'maya'}):
            sys.modules.pop('maya.cmds', None)
            self.assertNotIn('cmds', code_completion.host_modules())
            self.assertNotIn('maya.cmds', sys.modules)

    def test_host_modules_can_be_switched_off(self):
        with self.fake_maya(), \
                mock.patch.dict(os.environ, {NXT_DCC_ENV_VAR: 'maya'}):
            self.actions.complete_host_action.setChecked(False)
            self.assertNotIn('cmds', self.words())
            self.assertEqual([], self.editor.module_completions('cmds.l'))

    # -- tokens --------------------------------------------------------

    def test_node_paths_inside_a_token(self):
        self.load('x = ${/')
        got = self.editor.token_completions(self.editor.completion_prefix())
        self.assertIn('${/source', got)
        self.assertIn('${/reader', got)

    def test_another_nodes_attributes_after_its_dot(self):
        self.load('x = ${/source.')
        got = self.editor.token_completions(self.editor.completion_prefix())
        self.assertIn('${/source.value}', got)
        self.assertIn('${/source.label}', got)

    def test_a_slash_outside_a_token_starts_a_new_word(self):
        self.load('x = total/cou')
        self.assertEqual('cou', self.editor.completion_prefix())

    def test_sanitizing_tokens_keeps_every_column(self):
        source = "a = ${/source.value} + ${local}\nb = 1"
        clean = code_completion.sanitize_tokens(source)
        self.assertEqual(len(source), len(clean))
        self.assertNotIn('${', clean)
        compile(clean, 'completion', 'exec')

    # -- jedi ----------------------------------------------------------

    def test_jedi_is_not_loaded_until_it_is_wanted(self):
        # Importing and warming jedi takes seconds, which nobody should pay
        # for at startup.
        jedi = code_completion.Jedi()
        self.assertFalse(jedi._tried)

    @unittest.skipUnless(code_completion.Jedi.installed(), 'needs jedi')
    def test_jedi_knows_what_a_variable_holds(self):
        # A string's methods, which reading import lines cannot know.
        self.load("label = 'text'\nlabel.up")
        got = self.editor.jedi_completions('label.up', ask=True)
        self.assertIn('label.upper', got)

    @unittest.skipUnless(code_completion.Jedi.installed(), 'needs jedi')
    def test_jedi_sees_the_world_nodes_imports(self):
        self.load("json.du")
        got = self.editor.jedi_completions('json.du', ask=True)
        self.assertIn('json.dumps', got)

    @unittest.skipUnless(code_completion.Jedi.installed(), 'needs jedi')
    def test_typing_more_of_a_name_does_not_ask_again(self):
        self.load("label = 'text'\nlabel.u")
        self.editor.jedi_completions('label.u', ask=True)
        cursor = self.editor.textCursor()
        cursor.insertText('p')
        self.editor.setTextCursor(cursor)
        with mock.patch.object(code_completion.JEDI._module, 'Interpreter',
                               side_effect=AssertionError('asked again')):
            got = self.editor.jedi_completions('label.up')
        self.assertIn('label.upper', got)

    @unittest.skipUnless(code_completion.Jedi.installed(), 'needs jedi')
    def test_jedi_can_be_switched_off(self):
        self.load("label = 'text'\nlabel.up")
        self.actions.complete_jedi_action.setChecked(False)
        self.assertEqual([], self.editor.jedi_completions('label.up',
                                                          ask=True))

    def test_without_jedi_the_menu_says_how_to_get_it(self):
        with mock.patch.object(code_completion.Jedi, 'installed',
                               staticmethod(lambda: False)):
            from nxt_editor.actions import CodeEditorActions
            actions = CodeEditorActions(self.win)
        self.assertFalse(actions.complete_jedi_action.isEnabled())
        self.assertIn('pip install', actions.complete_jedi_action.whatsThis())


if __name__ == '__main__':
    unittest.main()
