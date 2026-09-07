"""A reference whose own reference is missing on this machine.

Keeping references that do not resolve means they now reach places that
used to be spared them, because loading pruned them before anything else
saw them. Rebuilding a layer stack walks nested references and opens each
one, and it threw on the first it could not read.

That throw landed in the middle of applying a change: every referenced
layer taken out, and the wanted ones not yet back. The stage was left with
the layers gone and a comp still full of their nodes, so the graph on
screen was not the graph that was loaded. Removing one layer appeared to
empty the layer list and leave every node behind.
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
from nxt.session import Session
from nxt_editor import stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

HAS_REF_EXPAND = hasattr(nxt_io, 'expand_reference_path')
NEEDS_CORE = 'needs an nxt_core with expand_reference_path'

MISSING = '$NXT_NO_SUCH_ROOT/lib/muscles.nxt'


def write_graph(path, name, references=(), node_names=()):
    data = {"version": "1.17", "alias": name, "mute": False, "solo": False,
            "references": list(references), "meta_data": {},
            "nodes": {"/" + n: {} for n in node_names}}
    with open(path, 'w') as file_object:
        json.dump(data, file_object, indent=4)
    return path


@unittest.skipUnless(HAS_REF_EXPAND, NEEDS_CORE)
class ANestedReferenceThatIsMissing(unittest.TestCase):

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix='nxt_nested_')
        # rig references something that is not on this machine.
        write_graph(os.path.join(self.tmp, 'rig.nxt'), 'rig',
                    references=[MISSING], node_names=['from_rig'])
        write_graph(os.path.join(self.tmp, 'utils.nxt'), 'utils',
                    node_names=['from_utils'])
        self.top_path = write_graph(os.path.join(self.tmp, 'top.nxt'), 'top',
                                    references=['rig.nxt', 'utils.nxt'],
                                    node_names=['from_top'])
        self.stage = Session().load_file(filepath=self.top_path)
        self.model = stage_model.StageModel(self.stage)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def aliases(self):
        return [l.get_alias() for l in self.stage._sub_layers]

    def comped(self):
        return sorted(self.model.comp_layer._nodes_path_as_key)

    def set_references(self, references):
        return self.model.set_layer_references(self.model.top_layer.real_path,
                                               references)

    # -- opening -------------------------------------------------------

    def test_it_opens_with_the_layers_that_do_resolve(self):
        self.assertEqual(['top', 'rig', 'utils'], self.aliases())
        self.assertEqual(['/from_rig', '/from_top', '/from_utils'],
                         self.comped())

    def test_the_missing_nested_reference_is_still_on_its_layer(self):
        rig = [l for l in self.stage._sub_layers
               if l.get_alias() == 'rig'][0]
        self.assertEqual([MISSING], rig.get_references())

    # -- removing a layer ----------------------------------------------

    def test_removing_a_layer_does_not_throw(self):
        # One unreadable file nested under another reference used to take
        # the whole edit down.
        self.set_references(['rig.nxt'])

    def test_removing_a_layer_takes_its_nodes_with_it(self):
        self.set_references(['rig.nxt'])
        self.assertEqual(['top', 'rig'], self.aliases())
        self.assertNotIn('/from_utils', self.comped(),
                         'the layer went but the comp still holds its '
                         'nodes, so the graph is not what is loaded')
        self.assertIn('/from_rig', self.comped())
        self.assertIn('/from_top', self.comped())

    def test_the_layers_and_the_comp_agree(self):
        self.set_references(['rig.nxt'])
        loaded = set()
        for layer in self.stage._sub_layers:
            loaded.update(layer._nodes_path_as_key)
        for node_path in self.comped():
            self.assertIn(node_path, loaded,
                          '%s is comped but no loaded layer has it'
                          % node_path)

    # -- adding one back -----------------------------------------------

    def test_adding_a_layer_back_does_not_throw(self):
        self.set_references(['rig.nxt'])
        self.set_references(['rig.nxt', 'utils.nxt'])

    def test_adding_a_layer_back_brings_its_nodes(self):
        self.set_references(['rig.nxt'])
        self.set_references(['rig.nxt', 'utils.nxt'])
        self.assertEqual(['top', 'rig', 'utils'], self.aliases())
        self.assertIn('/from_utils', self.comped())

    def test_undo_after_removing(self):
        self.set_references(['rig.nxt'])
        self.model.undo_stack.undo()
        self.assertEqual(['top', 'rig', 'utils'], self.aliases())
        self.assertIn('/from_utils', self.comped())

    # -- what the unsaved dialog walks ---------------------------------

    def test_the_unsaved_layers_dialog_can_walk_the_stack(self):
        # It recurses through sub_layers reaching for each layer, and a
        # reference that did not resolve has none. That threw on close,
        # which is a bad moment to throw.
        from nxt_editor.dialogs import UnsavedLayersDialogue
        self.set_references(['rig.nxt'])
        model = UnsavedLayersDialogue.make_unsaved_model([self.model])
        self.assertIsNotNone(model)


@unittest.skipUnless(HAS_REF_EXPAND, NEEDS_CORE)
class WhenApplyingGoesWrong(unittest.TestCase):
    """The model has to end up agreeing with the stage regardless."""

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix='nxt_apply_')
        write_graph(os.path.join(self.tmp, 'a.nxt'), 'a',
                    node_names=['from_a'])
        self.top_path = write_graph(os.path.join(self.tmp, 'top.nxt'), 'top',
                                    references=['a.nxt'],
                                    node_names=['from_top'])
        self.stage = Session().load_file(filepath=self.top_path)
        self.model = stage_model.StageModel(self.stage)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_throw_partway_still_leaves_the_comp_matching(self):
        exploded = []
        real_new_sublayer = self.stage.new_sublayer

        def explode(*args, **kwargs):
            exploded.append(1)
            raise IOError('pretend this file went away mid-apply')

        self.stage.new_sublayer = explode
        try:
            self.model.set_layer_references(self.model.top_layer.real_path,
                                            ['a.nxt', 'b.nxt'])
        except IOError:
            pass
        finally:
            self.stage.new_sublayer = real_new_sublayer
        self.assertTrue(exploded, 'the test did not exercise a failure')
        # Nothing came back, so nothing should be comped from it either.
        comped = sorted(self.model.comp_layer._nodes_path_as_key)
        self.assertNotIn('/from_a', comped,
                         'the layer is out of the stage but the comp still '
                         'has its nodes')
        self.assertIn(self.model.target_layer, self.stage._sub_layers,
                      'the target was left pointing outside the stage')


@unittest.skipUnless(HAS_REF_EXPAND, NEEDS_CORE)
class TheLayerManagerWithAnUnresolvedReference(unittest.TestCase):
    """The layer tree shows layers, and one of these did not open.

    The model walked sub_layers assuming every entry had a layer behind
    it. A reference that did not resolve has none, so building the tree
    reached for sub_layers on nothing and threw while the window was
    opening. Every later signal into that model threw too, which cut
    applying a reference change off partway: the layers went, and the
    graph kept the nodes because the settle never finished.
    """

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix='nxt_lm_')
        write_graph(os.path.join(self.tmp, 'rig.nxt'), 'rig',
                    references=[MISSING], node_names=['from_rig'])
        write_graph(os.path.join(self.tmp, 'utils.nxt'), 'utils',
                    node_names=['from_utils'])
        self.top_path = write_graph(os.path.join(self.tmp, 'top.nxt'), 'top',
                                    references=['rig.nxt', 'utils.nxt'],
                                    node_names=['from_top'])
        from nxt_editor.main_window import MainWindow
        self.win = MainWindow(filepath=self.top_path)
        self.model = self.win.model
        app.processEvents()

    def tearDown(self):
        self.model.effected_layers.clear()
        self.win.close()
        self.win = None
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def layer_model(self):
        return self.win.layer_manager.layer_tree.model()

    def drawn(self):
        return sorted(self.win.view._node_graphics)

    def comped(self):
        return sorted(self.model.comp_layer._nodes_path_as_key)

    # -- the tree ------------------------------------------------------

    def test_the_window_opens_at_all(self):
        # Building the tree threw here, before anything was asked of it.
        self.assertIsNotNone(self.layer_model())

    def test_walking_every_index_does_not_throw(self):
        indices = self.layer_model().get_all_layer_indices()
        self.assertTrue(indices)
        for index in indices:
            self.assertIsNotNone(index.internalPointer(),
                                 'an index was made for something that is '
                                 'not a layer')

    def test_a_reference_that_did_not_open_gets_no_row(self):
        model = self.layer_model()
        rig = [l for l in self.model.stage._sub_layers
               if l.get_alias() == 'rig'][0]
        self.assertEqual([MISSING], rig.get_references(),
                         'the reference should still be on the layer')
        index = model.get_index_of_layer(rig)
        self.assertEqual(0, model.rowCount(index),
                         'rig has one reference and it did not open, so it '
                         'has no rows')

    # -- and the change goes through -----------------------------------

    def test_removing_a_layer_clears_its_nodes_from_the_view(self):
        self.assertIn('/from_utils', self.drawn())
        self.model.set_layer_references(self.model.top_layer.real_path,
                                        ['rig.nxt'])
        app.processEvents()
        self.assertEqual(['top', 'rig'],
                         [l.get_alias() for l in self.model.stage._sub_layers])
        self.assertNotIn('/from_utils', self.comped())
        self.assertNotIn('/from_utils', self.drawn(),
                         'the layer is gone but the stage view still draws '
                         'its node')

    def test_what_is_drawn_is_what_is_comped(self):
        self.model.set_layer_references(self.model.top_layer.real_path,
                                        ['rig.nxt'])
        app.processEvents()
        self.assertEqual(self.comped(), self.drawn())

    def test_putting_it_back(self):
        self.model.set_layer_references(self.model.top_layer.real_path,
                                        ['rig.nxt'])
        app.processEvents()
        self.model.set_layer_references(self.model.top_layer.real_path,
                                        ['rig.nxt', 'utils.nxt'])
        app.processEvents()
        self.assertIn('/from_utils', self.comped())
        self.assertIn('/from_utils', self.drawn())
        self.assertEqual(self.comped(), self.drawn())


if __name__ == '__main__':
    unittest.main()
