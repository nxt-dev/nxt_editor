"""Editing a layer's references.

The strong check here is not that the code runs, it is that applying
references in memory lands in the same place as opening a file that
declares those references. If those two ever disagree, the editor is
showing you something the loader would not produce.

References are stored as written. A partial path stays partial, because
that is what keeps resolving through the file roots on another machine.
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

# Resolving a reference the way loading does lives in nxt_core. Against an
# older released core these sit out rather than failing for something this
# repo cannot fix.
from nxt import nxt_io  # noqa: E402

HAS_REF_EXPAND = hasattr(nxt_io, 'expand_reference_path')
NEEDS_CORE = 'needs an nxt_core with expand_reference_path'

TEST_DIR = os.path.dirname(os.path.abspath(__file__))


def write_graph(path, name, references=(), node_names=()):
    """A minimal graph on disk, so a test can build its own stack."""
    data = {
        "version": "1.17",
        "alias": name,
        "mute": False,
        "solo": False,
        "references": list(references),
        "meta_data": {},
        "nodes": {"/" + n: {} for n in node_names},
    }
    with open(path, 'w') as file_object:
        json.dump(data, file_object, indent=4)
    return path


@unittest.skipUnless(HAS_REF_EXPAND, NEEDS_CORE)
class LayerReferences(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_refs_')
        self.a = write_graph(os.path.join(self.tmp, 'a.nxt'), 'a',
                             node_names=['from_a'])
        self.b = write_graph(os.path.join(self.tmp, 'b.nxt'), 'b',
                             node_names=['from_b'])
        self.top_path = os.path.join(self.tmp, 'top.nxt')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def open_graph(self, references=()):
        write_graph(self.top_path, 'top', references=references,
                    node_names=['from_top'])
        stage = Session().load_file(filepath=self.top_path)
        return stage, stage_model.StageModel(stage)

    def comped(self, model):
        return sorted(model.comp_layer._nodes_path_as_key)

    # -- the load-equivalence check ------------------------------------

    def test_adding_a_reference_matches_opening_it(self):
        stage, model = self.open_graph(references=[])
        self.assertNotIn('/from_a', self.comped(model))
        changed = model.set_layer_references(model.top_layer.real_path,
                                             ['a.nxt'])
        self.assertTrue(changed)
        edited = self.comped(model)
        self.assertIn('/from_a', edited, 'the referenced node should appear')
        # The same graph, opened fresh from a file that declares it.
        _fresh_stage, fresh = self.open_graph(references=['a.nxt'])
        self.assertEqual(self.comped(fresh), edited,
                         'editing references landed somewhere opening would '
                         'not')

    def test_removing_a_reference_matches(self):
        stage, model = self.open_graph(references=['a.nxt'])
        self.assertIn('/from_a', self.comped(model))
        model.set_layer_references(model.top_layer.real_path, [])
        self.assertNotIn('/from_a', self.comped(model))
        _fresh_stage, fresh = self.open_graph(references=[])
        self.assertEqual(self.comped(fresh), self.comped(model))

    def test_swapping_a_reference_matches(self):
        stage, model = self.open_graph(references=['a.nxt'])
        model.set_layer_references(model.top_layer.real_path, ['b.nxt'])
        edited = self.comped(model)
        self.assertIn('/from_b', edited)
        self.assertNotIn('/from_a', edited)
        _fresh_stage, fresh = self.open_graph(references=['b.nxt'])
        self.assertEqual(self.comped(fresh), edited)

    def test_order_is_kept(self):
        # References are a stack, so their order is part of the meaning.
        stage, model = self.open_graph(references=[])
        model.set_layer_references(model.top_layer.real_path,
                                   ['a.nxt', 'b.nxt'])
        self.assertEqual(['a.nxt', 'b.nxt'],
                         model.get_layer_references(
                             model.top_layer.real_path))

    def test_reordering_is_a_change(self):
        stage, model = self.open_graph(references=['a.nxt', 'b.nxt'])
        changed = model.set_layer_references(model.top_layer.real_path,
                                             ['b.nxt', 'a.nxt'])
        self.assertTrue(changed, 'moving a reference is a change')
        self.assertEqual(['b.nxt', 'a.nxt'],
                         model.get_layer_references(
                             model.top_layer.real_path))

    # -- doing nothing -------------------------------------------------

    def test_setting_the_same_references_does_nothing(self):
        stage, model = self.open_graph(references=['a.nxt'])
        rebuilds = []
        real_build = stage.build_stage

        def counted(*args, **kwargs):
            rebuilds.append(1)
            return real_build(*args, **kwargs)

        stage.build_stage = counted
        try:
            changed = model.set_layer_references(model.top_layer.real_path,
                                                 ['a.nxt'])
        finally:
            stage.build_stage = real_build
        self.assertFalse(changed, 'nothing changed, so nothing to do')
        self.assertEqual([], rebuilds, 'it recomposited for no reason')

    # -- undo and the unsaved marker -----------------------------------

    def test_it_is_undoable(self):
        stage, model = self.open_graph(references=[])
        model.set_layer_references(model.top_layer.real_path, ['a.nxt'])
        self.assertIn('/from_a', self.comped(model))
        model.undo_stack.undo()
        self.assertNotIn('/from_a', self.comped(model),
                         'undo did not put the references back')
        self.assertEqual([], model.get_layer_references(
            model.top_layer.real_path))

    def test_it_marks_the_layer_unsaved(self):
        stage, model = self.open_graph(references=[])
        model.set_layer_references(model.top_layer.real_path, ['a.nxt'])
        self.assertIn(model.top_layer.real_path, model.effected_layers,
                      'the layer has changed, so it should be saveable')

    def test_saving_writes_the_references(self):
        stage, model = self.open_graph(references=[])
        model.set_layer_references(model.top_layer.real_path, ['a.nxt'])
        model.top_layer.save()
        with open(self.top_path) as file_object:
            on_disk = json.load(file_object)
        self.assertEqual(['a.nxt'], on_disk['references'],
                         'the partial path should be stored as written')

    # -- missing references --------------------------------------------

    def test_a_missing_reference_is_kept_not_dropped(self):
        # Someone else's machine has it. Silently dropping it would lose
        # the graph's intent.
        stage, model = self.open_graph(references=[])
        model.set_layer_references(model.top_layer.real_path,
                                   ['a.nxt', 'not_here.nxt'])
        self.assertEqual(['a.nxt', 'not_here.nxt'],
                         model.get_layer_references(
                             model.top_layer.real_path))
        self.assertIn('/from_a', self.comped(model),
                      'the reference that does exist should still load')

    # -- which layers may be edited ------------------------------------

    def test_editable_layers_are_the_open_ones(self):
        stage, model = self.open_graph(references=['a.nxt'])
        editable = [l.real_path for l in
                    model.get_editable_reference_layers()]
        self.assertIn(model.top_layer.real_path, editable)
        self.assertEqual(len(stage._sub_layers), len(editable),
                         'every open, unlocked layer should be editable')

    def test_a_locked_layer_is_not_editable(self):
        stage, model = self.open_graph(references=['a.nxt'])
        lower = [l for l in stage._sub_layers
                 if l is not model.top_layer][0]
        model.set_layer_locked(lower.real_path, True)
        editable = [l.real_path for l in
                    model.get_editable_reference_layers()]
        self.assertNotIn(lower.real_path, editable)
        refused = model.set_layer_references(lower.real_path, ['b.nxt'])
        self.assertFalse(refused, 'a locked layer is not ours to change')


if __name__ == '__main__':
    unittest.main()
