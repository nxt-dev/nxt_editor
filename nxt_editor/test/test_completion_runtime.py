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
import time
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


class Sneaky(object):
    """Something whose own code would run if completion asked it things.

    Each way in is written down, so a test can say none of them ran.
    """

    def __init__(self):
        self.ran = []
        self.visible = 1

    def __dir__(self):
        self.ran.append('__dir__')
        return ['from_dir']

    def __getattr__(self, name):
        self.ran.append('__getattr__ ' + name)
        return Sneaky()

    @property
    def __class__(self):
        self.ran.append('__class__')
        return Sneaky


class Raiser(object):
    """Something that raises whenever it is asked anything."""
    visible = 1

    def __dir__(self):
        raise RuntimeError('dir')

    def __getattr__(self, name):
        raise RuntimeError('getattr')


class Slotted(object):
    __slots__ = ('inside', 'empty')

    def __init__(self):
        self.inside = Rig()


class Big(object):
    """A rig that keeps a great many things on itself."""

    def __init__(self, count):
        for i in range(count):
            setattr(self, 'attr_%05d' % i, i)


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
            "/writer": {"code": ["STAGE.later = 1"]},
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
        got = self.editor.module_completions('STAGE.rig.')
        self.assertIn('STAGE.rig.build_guides', got)
        self.assertIn('STAGE.rig.modules', got)
        self.assertEqual(['STAGE.rig.build_guides'],
                         self.editor.module_completions('STAGE.rig.bu'))

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

    # -- what a build left is never asked to run code ---------------------

    def stage(self):
        return self.build()._console.globals['STAGE']

    def complete_everywhere(self, prefix):
        """Every way the editor completes, as typing and Ctrl+Space do."""
        self.load(prefix)
        self.editor.module_completions(prefix)
        self.editor.jedi_completions(prefix)
        self.editor.jedi_completions(prefix, ask=True, fresh=True)
        self.editor.update_completions(force=True)

    def test_no_dunder_dir_or_getattr_is_called(self):
        sneaky = Sneaky()
        self.stage().sneaky = sneaky
        for prefix in ('STAGE.sneaky.', 'STAGE.sneaky.vi',
                       'STAGE.sneaky.missing.', 'STAGE.sneaky.ran.'):
            self.complete_everywhere(prefix)
        self.assertEqual([], sneaky.ran)
        got = self.editor.module_completions('STAGE.sneaky.')
        self.assertIn('STAGE.sneaky.visible', got)
        self.assertNotIn('STAGE.sneaky.from_dir', got)

    def test_one_that_raises_does_not_break_completion(self):
        self.stage().raiser = Raiser()
        for prefix in ('STAGE.raiser.', 'STAGE.raiser.nope.'):
            self.complete_everywhere(prefix)
        self.assertEqual(['STAGE.raiser.visible'],
                         self.editor.module_completions('STAGE.raiser.'))

    def test_jedi_is_never_given_what_the_build_left(self):
        stage = self.stage()
        given = []
        real = code_completion.JEDI.complete

        def complete(source, line, column, namespace, key, fresh=False):
            given.append(namespace)
            return []
        code_completion.JEDI.complete = complete
        try:
            for prefix in ('STAGE.', 'STAGE.rig.', 'self.', 'os.'):
                self.load(prefix)
                self.editor.jedi_completions(prefix, ask=True, fresh=True)
        finally:
            code_completion.JEDI.complete = real
        if not code_completion.Jedi.installed():
            self.assertEqual([], given)
            return
        self.assertEqual(4, len(given))
        for namespace in given:
            for name in code_completion.LIVE_GLOBALS:
                self.assertNotIn(name, namespace)
            for value in namespace.values():
                self.assertIsNot(stage, value)

    def test_a_huge_stage_completes_quickly(self):
        self.stage().big = Big(20000)
        self.editor.module_completions('STAGE.big.')
        start = time.perf_counter()
        got = self.editor.module_completions('STAGE.big.')
        took = time.perf_counter() - start
        self.assertEqual(code_completion.LIVE_NAME_LIMIT, len(got))
        self.assertLess(took, 0.05)
        # The limit is applied to what matches what is typed, so nothing is
        # out of reach.
        self.assertEqual(['STAGE.big.attr_19999'],
                         self.editor.module_completions(
                             'STAGE.big.attr_19999'))

    def test_a_build_that_moves_on_is_seen(self):
        runtime = self.build()
        self.load('STAGE.la')
        self.assertEqual([], self.editor.module_completions('STAGE.la'))
        self.assertEqual([], self.editor.jedi_completions('STAGE.la',
                                                          ask=True))
        # The next step of the same build, on the same runtime layer.
        self.model.stage.execute_nodes(['/writer'], runtime)
        self.assertEqual(['STAGE.later'],
                         self.editor.module_completions('STAGE.la'))
        if code_completion.Jedi.installed():
            self.assertIn('STAGE.later', self.editor.jedi_completions(
                'STAGE.la', ask=True))

    def test_nothing_is_read_while_a_node_runs(self):
        self.build()
        self.model._running_node = True
        try:
            self.assertEqual([], self.editor.module_completions('STAGE.r'))
        finally:
            self.model._running_node = False
        self.assertEqual(['STAGE.rig'],
                         self.editor.module_completions('STAGE.r'))


class StaticReads(unittest.TestCase):
    """Reading a live object without running any of its code."""

    def test_names_come_from_the_dicts_not_dir(self):
        sneaky = Sneaky()
        names = code_completion.static_names(sneaky)
        self.assertIn('visible', names)
        self.assertIn('ran', names)
        self.assertNotIn('from_dir', names)
        self.assertEqual([], sneaky.ran)

    def test_slots_are_listed_and_read(self):
        slotted = Slotted()
        self.assertEqual(['empty', 'inside'],
                         sorted(code_completion.static_names(slotted)))
        self.assertIs(slotted.inside,
                      code_completion.static_attr(slotted, 'inside'))
        self.assertIsNone(code_completion.static_attr(slotted, 'empty'))

    def test_a_property_stops_the_walk(self):
        rig = Rig()
        self.assertIsNone(code_completion.static_attr(rig, 'expensive'))
        self.assertEqual([], code_completion.live_completions(
            rig, 'expensive.'))
        self.assertFalse(rig.touched)

    def test_a_property_wins_over_the_own_value(self):
        rig = Rig()
        rig.__dict__['expensive'] = 'stale'
        self.assertIsNone(code_completion.static_attr(rig, 'expensive'))

    def test_a_dict_property_is_not_run(self):
        ran = []

        class Odd(object):
            @property
            def __dict__(self):
                ran.append(True)
                return {'made_up': 1}
        self.assertNotIn('made_up', code_completion.static_names(Odd()))
        self.assertEqual([], ran)

    def test_a_class_lists_its_own_attributes(self):
        frame = type('frame', (), {'local': 7})
        self.assertIn('local', code_completion.static_names(frame))
        self.assertEqual(7, code_completion.static_attr(frame, 'local'))

    def test_the_limit(self):
        names = code_completion.static_names(Big(50), limit=10)
        self.assertEqual(10, len(names))
        self.assertEqual(['attr_00049'], code_completion.static_names(
            Big(50), 'attr_00049', limit=10))

    def test_a_module_on_stage_is_walked_too(self):
        self.assertIn('os.path.join', code_completion.live_completions(
            types.SimpleNamespace(os=os), 'os.path.jo'))


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
