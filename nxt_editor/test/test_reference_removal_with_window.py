"""Removing a reference with a real editor window open.

The other reference tests drive StageModel on its own, and they all passed
while removing a reference took Maya down. What they could not see is that
the model has state pointing at layers: the target layer is one of them,
and taking its layer out of the stage leaves it pointing at an object that
is not in the graph any more. In a DCC that does not raise, it crashes.

So these build the real window and check the model is still coherent
afterwards, which is the thing the bare-model tests cannot assert.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import unittest

# External
from Qt import QtWidgets

# Internal
from nxt import nxt_io
from nxt_editor.main_window import MainWindow

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

HAS_REF_EXPAND = hasattr(nxt_io, 'expand_reference_path')
NEEDS_CORE = 'needs an nxt_core with expand_reference_path'


def write_graph(path, name, references=(), node_names=()):
    data = {"version": "1.17", "alias": name, "mute": False, "solo": False,
            "references": list(references), "meta_data": {},
            "nodes": {"/" + n: {} for n in node_names}}
    with open(path, 'w') as file_object:
        json.dump(data, file_object, indent=4)
    return path


@unittest.skipUnless(HAS_REF_EXPAND, NEEDS_CORE)
class RemovingAReferenceWithAWindowOpen(unittest.TestCase):

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix='nxt_refwin_')
        write_graph(os.path.join(self.tmp, 'a.nxt'), 'a',
                    node_names=['from_a', 'from_a/child'])
        write_graph(os.path.join(self.tmp, 'b.nxt'), 'b',
                    node_names=['from_b'])
        self.top_path = write_graph(os.path.join(self.tmp, 'top.nxt'), 'top',
                                    references=['a.nxt', 'b.nxt'],
                                    node_names=['from_top'])
        self.win = MainWindow(filepath=self.top_path)
        self.model = self.win.model
        app.processEvents()

    def tearDown(self):
        # Setting references marks the layer unsaved, and closing a window
        # with unsaved layers asks about it, which nothing here can answer.
        self.model.effected_layers.clear()
        self.win.close()
        self.win = None
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def layer_named(self, alias):
        for layer in self.model.stage._sub_layers:
            if layer.get_alias() == alias:
                return layer
        return None

    def aliases(self):
        return [l.get_alias() for l in self.model.stage._sub_layers]

    def comped(self):
        return sorted(self.model.comp_layer._nodes_path_as_key)

    def set_references(self, references):
        self.model.set_layer_references(self.model.top_layer.real_path,
                                        references)
        app.processEvents()

    # -- the crash -----------------------------------------------------

    def test_the_target_layer_does_not_outlive_its_layer(self):
        # Target the layer that is about to be removed, which is what
        # someone does right before deciding they do not want it.
        self.model.set_target_layer(self.layer_named('a').real_path)
        app.processEvents()
        self.assertEqual('a', self.model.target_layer.get_alias())

        self.set_references(['b.nxt'])

        target = self.model.target_layer
        self.assertIsNotNone(target, 'the model was left with no target')
        self.assertIn(target, self.model.stage._sub_layers,
                      'the target layer is not in the stage any more, so '
                      'everything reaching for it is working on a layer '
                      'that is not in the graph')

    def test_removing_a_layer_that_is_not_targeted_leaves_the_target_alone(self):
        self.model.set_target_layer(self.layer_named('b').real_path)
        app.processEvents()
        self.set_references(['b.nxt'])
        self.assertEqual('b', self.model.target_layer.get_alias(),
                         'a target that was still valid should have been '
                         'left where it was')

    def test_the_layer_manager_hears_about_what_left(self):
        # It rebuilds on layer_removed, so a layer that goes without one
        # stays on screen pointing at nothing.
        removed = []
        self.model.layer_removed.connect(removed.append)
        gone = self.layer_named('a').real_path
        self.set_references(['b.nxt'])
        self.assertIn(gone, removed,
                      'nothing announced that the layer was removed')

    # -- and it still does the job -------------------------------------

    def test_the_nodes_go_with_it(self):
        self.assertIn('/from_a', self.comped())
        self.set_references(['b.nxt'])
        self.assertEqual(['top', 'b'], self.aliases())
        comped = self.comped()
        self.assertNotIn('/from_a', comped)
        self.assertNotIn('/from_a/child', comped)
        self.assertIn('/from_b', comped)
        self.assertIn('/from_top', comped)

    def test_removing_every_reference(self):
        self.model.set_target_layer(self.layer_named('a').real_path)
        app.processEvents()
        self.set_references([])
        self.assertEqual(['top'], self.aliases())
        self.assertIn(self.model.target_layer, self.model.stage._sub_layers)
        self.assertEqual(['/from_top'], self.comped())

    def test_undo_puts_it_back_and_leaves_a_valid_target(self):
        self.model.set_target_layer(self.layer_named('a').real_path)
        app.processEvents()
        self.set_references(['b.nxt'])
        self.model.undo_stack.undo()
        app.processEvents()
        self.assertEqual(['top', 'a', 'b'], self.aliases())
        self.assertIn('/from_a', self.comped())
        self.assertIn(self.model.target_layer, self.model.stage._sub_layers,
                      'undo left the target pointing at nothing')

    def test_swapping_one_reference_for_another(self):
        self.model.set_target_layer(self.layer_named('a').real_path)
        app.processEvents()
        self.set_references(['b.nxt', 'a.nxt'])
        self.assertIn(self.model.target_layer, self.model.stage._sub_layers)
        comped = self.comped()
        self.assertIn('/from_a', comped)
        self.assertIn('/from_b', comped)


if __name__ == '__main__':
    unittest.main()
