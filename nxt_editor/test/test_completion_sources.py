"""Completion is configurable, and knows what the compute imports.

Each source can be switched off on its own, because they are not equally
welcome: python's own names are noise to someone writing mostly tokens,
and the words already in a long compute are noise to everyone. The
choices are preferences, so they survive a restart.

Module names come from the compute's own import lines. Nothing else is
imported on its behalf.
"""
# Builtin
import os
import sys
import unittest

# External
from Qt import QtWidgets

# Internal
from nxt_editor import user_dir

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

IMPORTS = "\n".join([
    "import os",
    "import os.path",
    "from json import dumps",
    "import xml.etree.ElementTree as ET",
    "",
])

SOURCE_PREFS = (
    user_dir.USER_PREF.CE_COMPLETE_PYTHON,
    user_dir.USER_PREF.CE_COMPLETE_MODULES,
    user_dir.USER_PREF.CE_COMPLETE_NODE,
    user_dir.USER_PREF.CE_COMPLETE_DOCUMENT,
)


class CompletionSources(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.chdir(os.path.dirname(__file__))
        cls.win = MainWindow(filepath="StageInstanceTest.nxt")
        cls.ce = cls.win.code_editor
        cls.editor = cls.ce.editor
        cls.actions = cls.win.code_editor_actions
        cls.ce.stage_model.set_selection(['/inst_source1'])
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None

    def setUp(self):
        # These are real preferences on disk. Put back whatever the person
        # running the tests had rather than leaving our choices behind.
        self.saved = {key: user_dir.user_prefs.get(key) for key in SOURCE_PREFS}
        for action, _pref, _default in self.actions.completion_source_actions:
            action.setChecked(True)
        self.editor.setReadOnly(False)
        self.ce.editing_active = True
        self.editor.setPlainText(IMPORTS + "x = ")
        self.editor.invalidate_completion_words()
        app.processEvents()

    def tearDown(self):
        for key, value in self.saved.items():
            if value is None:
                continue
            user_dir.user_prefs[key] = value

    def words(self):
        self.editor.invalidate_completion_words()
        return self.editor.build_completion_words()

    # -- imports ------------------------------------------------------

    def test_plain_import(self):
        self.assertIn('os', self.editor.imported_modules())

    def test_aliased_import(self):
        # "import xml.etree.ElementTree as ET" binds ET, not xml.
        self.assertIn('ET', self.editor.imported_modules())

    def test_from_import_does_not_swallow_later_lines(self):
        # The names part matched newlines, so everything after a from
        # import was invisible, which is how the aliased import went
        # missing.
        modules = self.editor.imported_modules()
        self.assertIn('json', modules)
        self.assertIn('ET', modules)

    def test_dotted_prefix_looks_inside_the_module(self):
        got = self.editor.module_completions('os.pa')
        self.assertTrue(any(name == 'os.path' for name in got), got[:5])

    def test_walks_further_dots(self):
        got = self.editor.module_completions('os.path.jo')
        self.assertTrue(any(name == 'os.path.join' for name in got), got[:5])

    def test_a_module_that_will_not_import_is_quiet(self):
        # maya.cmds outside maya, for instance.
        self.editor.setPlainText("import definitely_not_a_module_xyz\nx = ")
        self.editor.invalidate_completion_words()
        self.assertEqual([],
                         self.editor.module_completions('definitely_not_a_module_xyz.'))

    def test_nothing_is_imported_that_the_compute_did_not_ask_for(self):
        self.editor.setPlainText("x = ")
        self.assertEqual({}, self.editor.imported_modules())

    # -- toggles ------------------------------------------------------

    def test_python_source_can_be_switched_off(self):
        self.assertIn('enumerate', self.words())
        self.actions.complete_python_action.setChecked(False)
        self.assertNotIn('enumerate', self.words())

    def test_module_source_can_be_switched_off(self):
        self.assertTrue(self.editor.module_completions('os.pa'))
        self.actions.complete_modules_action.setChecked(False)
        self.assertEqual([], self.editor.module_completions('os.pa'))

    def test_node_source_can_be_switched_off(self):
        attrs = self.ce.stage_model.get_node_attr_names(self.ce.node_path)
        if not attrs:
            self.skipTest('the represented node has no attributes')
        token = '${%s}' % attrs[0]
        self.assertIn(token, self.words())
        self.actions.complete_node_action.setChecked(False)
        self.assertNotIn(token, self.words())

    def test_document_source_can_be_switched_off(self):
        self.editor.setPlainText("my_own_variable_name = 1\nx = ")
        self.assertIn('my_own_variable_name', self.words())
        self.actions.complete_document_action.setChecked(False)
        self.assertNotIn('my_own_variable_name', self.words())

    # -- persistence --------------------------------------------------

    def test_a_choice_is_written_to_preferences(self):
        pref = user_dir.USER_PREF.CE_COMPLETE_MODULES
        self.actions.complete_modules_action.setChecked(False)
        self.assertFalse(user_dir.user_prefs.get(pref),
                         'the choice has to survive a restart')
        self.actions.complete_modules_action.setChecked(True)
        self.assertTrue(user_dir.user_prefs.get(pref))


if __name__ == '__main__':
    unittest.main()
