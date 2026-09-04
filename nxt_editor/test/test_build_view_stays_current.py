"""An edit that changes what the graph will do must reach the build view.

The graph redraws when nodes change; the build view refreshes when the
comp layer says it changed. Edits that alter the execution order were
only announcing the first, so the build kept describing the old order and
had to be recomposited by hand before it was right again.

Disabling a node is the case that gets hit: the comp layer takes it out
of the execution order straight away, and the build view carried on
listing it.
"""
# Builtin
import os
import sys
import unittest

# External
from Qt import QtWidgets

# Internal
from nxt.session import Session
from nxt_editor import stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

START = '/inst_source1'


class BuildViewHearsAboutIt(unittest.TestCase):

    def setUp(self):
        os.chdir(os.path.dirname(__file__))
        self.stage = Session().load_file(filepath="StageInstanceTest.nxt")
        self.model = stage_model.StageModel(self.stage)
        self.comp_changes = []
        self.model.comp_layer_changed.connect(self.comp_changes.append)

    def exec_order(self, start=START):
        return list(self.model.comp_layer.get_exec_order(start))

    def test_disabling_takes_it_out_of_the_build(self):
        self.assertTrue(self.exec_order(), 'nothing to disable')
        self.model.set_node_enabled(START, False, layer=self.model.top_layer)
        self.assertEqual([], self.exec_order(),
                         'the comp layer should drop a disabled node')

    def test_disabling_tells_the_build_view(self):
        self.model.set_node_enabled(START, False, layer=self.model.top_layer)
        self.assertTrue(self.comp_changes,
                        'nothing emitted comp_layer_changed, so the build '
                        'view keeps the old execution order until someone '
                        'recomposites by hand')

    def test_re_enabling_tells_it_too(self):
        self.model.set_node_enabled(START, False, layer=self.model.top_layer)
        before = len(self.comp_changes)
        self.model.set_node_enabled(START, True, layer=self.model.top_layer)
        self.assertGreater(len(self.comp_changes), before)
        self.assertTrue(self.exec_order(), 'it should be back in the build')

    def test_undo_tells_it_as_well(self):
        self.model.set_node_enabled(START, False, layer=self.model.top_layer)
        before = len(self.comp_changes)
        self.model.undo_stack.undo()
        self.assertGreater(len(self.comp_changes), before,
                           'undo left the build view stale')
        self.assertTrue(self.exec_order())

    def test_the_in_place_result_matches_a_rebuild(self):
        # The point of not rebuilding is that we do not have to, so the
        # answer has to be the same either way.
        self.model.set_node_enabled(START, False, layer=self.model.top_layer)
        in_place = self.exec_order()
        rebuilt = list(self.stage.build_stage().get_exec_order(START))
        self.assertEqual(rebuilt, in_place)


if __name__ == '__main__':
    unittest.main()
