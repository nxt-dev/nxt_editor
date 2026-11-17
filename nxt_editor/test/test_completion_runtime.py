"""STAGE. and self. complete on what a graph that ran left there.

nxt hands every compute STAGE and self, and a rig build stores its working
objects on STAGE so that later nodes can reach them. In the code editor both
were None, so after the dot the list was what None has: __bool__, __class__,
__delattr__ and the rest. Before a build there is nothing to say after the
dot, and nothing is now said. After one, the runtime layer holds the real
STAGE and the node as it ran, and those are what completes.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

# External
from Qt import QtGui, QtWidgets

# Internal
from nxt import DATA_STATE
from nxt_editor.dockwidgets import code_completion

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402


class Rig(object):
    """Something a graph would keep on STAGE."""

    def __init__(self):
        self.modules = []
        self.touched = False

    def build_guides(self):
        pass

    @property
    def expensive(self):
        # A property on a scene object can do anything. Completion must
        # not be what runs it.
        self.touched = True
        return types.SimpleNamespace(inside=1)


def write_graph(path):
    data = {
        "version": "1.17", "alias": "runtime", "mute": False,
        "solo": False, "meta_data": {},
        "nodes": {
            "/": {"code": [
                "from nxt_editor.test import test_completion_runtime",
                "STAGE.rig = test_completion_runtime.Rig()"]},
            "/reader": {"attrs": {"local": {"value": "7"}}, "code": [""]},
            "/other": {"attrs": {"elsewhere": {"value": "1"}}},
        },
    }
    with open(path, 'w') as file_object:
        json.dump(data, file_object, indent=4)


class CompletionOnARunGraph(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='nxt_completion_rt_')
        cls.graph = os.path.join(cls.tmp, 'runtime.nxt')
        write_graph(cls.graph)
        cls.win = MainWindow(filepath=cls.graph)
        cls.model = cls.win.model
        cls.editor = cls.win.code_editor.editor
        cls.model.data_state = DATA_STATE.RAW
        cls.model.set_selection(['/reader'])
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        for action, _pref, _default in \
                self.win.code_editor_actions.completion_source_actions:
            action.setChecked(True)
        self.model.current_rt_layer = None

    def tearDown(self):
        self.editor.hide_completions()
        self.model.current_rt_layer = None

    def load(self, text):
        self.editor.setReadOnly(False)
        self.win.code_editor.editing_active = True
        self.editor.setPlainText(text)
        cursor = self.editor.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.editor.setTextCursor(cursor)
        self.editor.invalidate_completion_words()

    def build(self):
        """Run the world node, the way the start of any build does."""
        runtime = self.model.stage.setup_runtime_layer(self.model.comp_layer)
        self.model.current_rt_layer = runtime
        return runtime

    # -- before a build ----------------------------------------------------

    def test_the_names_still_complete(self):
        self.editor.invalidate_completion_words()
        words = self.editor.build_completion_words()
        for name in ('STAGE', 'self', 'self.local'):
            self.assertIn(name, words)

    def test_nothing_is_made_up_after_the_dot(self):
        self.assertNotIn('STAGE', self.editor.completion_namespace())
        self.assertNotIn('self', self.editor.completion_namespace())
        self.assertEqual([], self.editor.module_completions('STAGE.'))

    @unittest.skipUnless(code_completion.Jedi.installed(), 'needs jedi')
    def test_jedi_does_not_offer_what_none_has(self):
        for prefix in ('STAGE.', 'self.'):
            self.load(prefix)
            got = self.editor.jedi_completions(prefix, ask=True, fresh=True)
            self.assertEqual([], got, prefix)

    # -- after a build -------------------------------------------------------

    def test_stage_holds_what_the_graph_stored(self):
        self.build()
        self.assertIn('STAGE.rig', self.editor.module_completions('STAGE.r'))

    def test_walks_into_what_is_on_stage(self):
        self.build()
        got = self.editor.module_completions('STAGE.rig.bu')
        self.assertIn('STAGE.rig.build_guides', got)
        self.assertIn('STAGE.rig.modules', got)

    def test_self_is_the_node_being_edited(self):
        # The console's own self is whichever node ran last.
        self.build()
        got = self.editor.module_completions('self.')
        self.assertIn('self.local', got)
        self.assertNotIn('self.elsewhere', got)

    def test_a_property_is_listed_but_never_run(self):
        runtime = self.build()
        rig = runtime._console.globals['STAGE'].rig
        self.assertIn('STAGE.rig.expensive',
                      self.editor.module_completions('STAGE.rig.ex'))
        self.assertEqual([],
                         self.editor.module_completions('STAGE.rig.expensive.'))
        self.assertFalse(rig.touched, 'completion ran a property')

    @unittest.skipUnless(code_completion.Jedi.installed(), 'needs jedi')
    def test_jedi_sees_the_built_stage(self):
        self.load('STAGE.rig.')
        self.assertEqual([], self.editor.jedi_completions(
            'STAGE.rig.', ask=True))
        runtime = self.build()
        # Not asked fresh: the build alone is why the old answer is not kept.
        got = self.editor.jedi_completions('STAGE.rig.', ask=True)
        self.assertIn('STAGE.rig.build_guides', got)
        self.assertFalse(runtime._console.globals['STAGE'].rig.touched)


class AttrForCompletion(unittest.TestCase):

    def test_a_module_is_read_as_usual(self):
        self.assertIs(os.path,
                      code_completion.attr_for_completion(os, 'path'))

    def test_what_is_missing_is_none(self):
        self.assertIsNone(code_completion.attr_for_completion(Rig(), 'nope'))

    def test_a_plain_attribute_is_read(self):
        rig = Rig()
        self.assertIs(rig.modules,
                      code_completion.attr_for_completion(rig, 'modules'))

    def test_a_method_can_be_looked_inside(self):
        self.assertIsNotNone(
            code_completion.attr_for_completion(Rig(), 'build_guides'))


if __name__ == '__main__':
    unittest.main()
