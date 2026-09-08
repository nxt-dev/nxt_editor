"""What the graph is being looked at through, after layers come and go.

Applying references rebuilds every referenced layer, so a layer that is
still there is not the same object it was. The model holds layer objects,
and the display layer is one of them: left alone it points at a layer that
was thrown away.

That matters more than the target, because the comp is built from it.
Rebuilding through the comp's own index is worse still, since removing a
layer shifts every index below it, so the graph gets composited from the
wrong place in the stack and keeps showing nodes belonging to layers that
are no longer loaded. The build view and the workflow view read that comp,
so they go stale with it.
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
from nxt.session import Session
from nxt_editor import stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def write_graph(path, name, references=(), node_names=()):
    data = {"version": "1.17", "alias": name, "mute": False, "solo": False,
            "references": list(references), "meta_data": {},
            "nodes": {"/" + n: {} for n in node_names}}
    with open(path, 'w') as file_object:
        json.dump(data, file_object, indent=4)
    return path


class TheDisplayLayerSurvivesAReferenceChange(unittest.TestCase):

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix='nxt_disp_')
        for name in ('a', 'b', 'c'):
            write_graph(os.path.join(self.tmp, '%s.nxt' % name), name,
                        node_names=['from_%s' % name])
        self.top_path = write_graph(
            os.path.join(self.tmp, 'top.nxt'), 'top',
            references=['a.nxt', 'b.nxt', 'c.nxt'], node_names=['from_top'])
        self.stage = Session().load_file(filepath=self.top_path)
        self.model = stage_model.StageModel(self.stage)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def layer(self, alias):
        for layer in self.stage._sub_layers:
            if layer.get_alias() == alias:
                return layer
        return None

    def comped(self):
        return sorted(self.model.comp_layer._nodes_path_as_key)

    def display(self, alias):
        self.model.set_display_layer(self.layer(alias))

    def set_references(self, references):
        self.model.set_layer_references(self.model.top_layer.real_path,
                                        references)

    # -- the object -----------------------------------------------------

    def test_it_is_a_layer_that_is_actually_in_the_stage(self):
        self.display('c')
        self.set_references(['a.nxt', 'c.nxt'])
        display = self.model.display_layer
        self.assertIsNotNone(display)
        self.assertIn(display, self.stage._sub_layers,
                      'the graph is being looked at through a layer that was '
                      'thrown away')

    def test_it_is_still_the_same_layer_by_name(self):
        self.display('c')
        self.set_references(['a.nxt', 'c.nxt'])
        self.assertEqual('c', self.model.display_layer.get_alias(),
                         'the view moved to a different layer on its own')

    # -- and the comp is right ------------------------------------------

    def test_removing_a_layer_above_the_displayed_one(self):
        # The one that goes wrong quietly: every index below the removed
        # layer shifts, so a comp rebuilt from the old index composites
        # from somewhere else entirely.
        self.display('c')
        self.assertEqual(['/from_c'], self.comped())
        self.set_references(['a.nxt', 'c.nxt'])
        self.assertEqual('c', self.model.display_layer.get_alias())
        self.assertEqual(['/from_c'], self.comped(),
                         'the graph was composited from the wrong place in '
                         'the stack')

    def test_removing_the_displayed_layer_itself(self):
        self.display('b')
        self.set_references(['a.nxt', 'c.nxt'])
        display = self.model.display_layer
        self.assertIn(display, self.stage._sub_layers)
        self.assertEqual('top', display.get_alias(),
                         'the layer being looked through went, so it should '
                         'fall back to the top')
        self.assertEqual(['/from_a', '/from_c', '/from_top'], self.comped())

    def test_the_comp_holds_nothing_from_a_removed_layer(self):
        self.display('c')
        self.set_references(['c.nxt'])
        for node_path in self.comped():
            self.assertNotIn('from_a', node_path)
            self.assertNotIn('from_b', node_path)

    def test_displaying_the_top_layer_is_unaffected(self):
        self.set_references(['a.nxt', 'c.nxt'])
        self.assertEqual('top', self.model.display_layer.get_alias())
        self.assertEqual(['/from_a', '/from_c', '/from_top'], self.comped())

    def test_adding_a_layer_back_while_displaying_a_lower_one(self):
        self.display('c')
        self.set_references(['a.nxt', 'c.nxt'])
        self.set_references(['a.nxt', 'b.nxt', 'c.nxt'])
        self.assertEqual('c', self.model.display_layer.get_alias())
        self.assertIn(self.model.display_layer, self.stage._sub_layers)
        self.assertEqual(['/from_c'], self.comped())

    def test_undo_leaves_a_display_layer_that_is_in_the_stage(self):
        self.display('c')
        self.set_references(['a.nxt', 'c.nxt'])
        self.model.undo_stack.undo()
        self.assertIn(self.model.display_layer, self.stage._sub_layers)
        self.assertEqual('c', self.model.display_layer.get_alias())
        self.assertEqual(['/from_c'], self.comped())

    # -- what the other views read --------------------------------------

    def test_everything_comped_comes_from_a_loaded_layer(self):
        # The build view and the workflow view read the comp, so if it
        # holds nodes from layers that are gone, so do they.
        self.display('c')
        self.set_references(['a.nxt', 'c.nxt'])
        loaded = set()
        for layer in self.stage._sub_layers:
            loaded.update(layer._nodes_path_as_key)
        for node_path in self.comped():
            self.assertIn(node_path, loaded,
                          '%s is comped but no loaded layer has it'
                          % node_path)


if __name__ == '__main__':
    unittest.main()
