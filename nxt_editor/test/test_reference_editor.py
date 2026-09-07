"""The reference editor dialog.

Driving the dialog rather than the model, because the model is covered in
test_layer_references. What matters here is that what it shows is true,
that the resolved view is a way of looking and not a way of editing, and
that Cancel really does nothing.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import unittest

# External
from Qt import QtCore, QtWidgets

# Internal
from nxt import nxt_io
from nxt.session import Session
from nxt_editor import stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.dockwidgets.reference_editor import ReferenceEditor  # noqa

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
class ReferenceEditorDialog(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_refdlg_')
        write_graph(os.path.join(self.tmp, 'a.nxt'), 'a',
                    node_names=['from_a'])
        write_graph(os.path.join(self.tmp, 'b.nxt'), 'b',
                    node_names=['from_b'])
        self.top_path = os.path.join(self.tmp, 'top.nxt')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def dialog(self, references=()):
        write_graph(self.top_path, 'top', references=references,
                    node_names=['from_top'])
        stage = Session().load_file(filepath=self.top_path)
        model = stage_model.StageModel(stage)
        return model, ReferenceEditor(model)

    def rows(self, dialog):
        return [dialog.list.item(i).text()
                for i in range(dialog.list.count())]

    # -- what it shows --------------------------------------------------

    def test_it_lists_the_references_as_stored(self):
        _model, dialog = self.dialog(['a.nxt'])
        self.assertEqual(['a.nxt'], self.rows(dialog),
                         'the stored, partial path is what it should show')

    def test_the_toggle_shows_every_row_resolved(self):
        _model, dialog = self.dialog(['a.nxt'])
        dialog.resolved_button.setChecked(True)
        shown = self.rows(dialog)
        self.assertEqual(1, len(shown))
        self.assertTrue(os.path.samefile(os.path.join(self.tmp, 'a.nxt'),
                                         shown[0]),
                        'resolved should be where it actually lands')
        dialog.resolved_button.setChecked(False)
        self.assertEqual(['a.nxt'], self.rows(dialog), 'and back again')

    def test_the_toggle_moves_every_row_at_once(self):
        _model, dialog = self.dialog(['a.nxt', 'b.nxt'])
        dialog.resolved_button.setChecked(True)
        for shown in self.rows(dialog):
            self.assertTrue(os.path.isabs(shown),
                            'every row should be resolved, not just one')

    def test_resolved_rows_cannot_be_typed_into(self):
        # Editing the resolved view would store this machine's answer and
        # pin the graph to this machine.
        _model, dialog = self.dialog(['a.nxt'])
        dialog.resolved_button.setChecked(True)
        item = dialog.list.item(0)
        self.assertFalse(bool(item.flags() & QtCore.Qt.ItemIsEditable))
        dialog.resolved_button.setChecked(False)
        item = dialog.list.item(0)
        self.assertTrue(bool(item.flags() & QtCore.Qt.ItemIsEditable))

    def test_a_missing_reference_is_flagged_and_kept(self):
        _model, dialog = self.dialog(['a.nxt', 'not_here.nxt'])
        self.assertEqual(['a.nxt', 'not_here.nxt'], self.rows(dialog))
        self.assertIn('could not be found', dialog.status.text())
        self.assertIn('Looked at', dialog.list.item(1).toolTip())

    # -- which layers ---------------------------------------------------

    def test_only_open_layers_are_offered(self):
        model, dialog = self.dialog(['a.nxt'])
        offered = [dialog.layer_combo.itemData(i)
                   for i in range(dialog.layer_combo.count())]
        self.assertIn(model.top_layer.real_path, offered)
        self.assertEqual(len(model.stage._sub_layers), len(offered))

    def test_a_locked_layer_is_not_offered(self):
        model, _dialog = self.dialog(['a.nxt'])
        lower = [l for l in model.stage._sub_layers
                 if l is not model.top_layer][0]
        model.set_layer_locked(lower.real_path, True)
        dialog = ReferenceEditor(model)
        offered = [dialog.layer_combo.itemData(i)
                   for i in range(dialog.layer_combo.count())]
        self.assertNotIn(lower.real_path, offered)

    # -- editing --------------------------------------------------------

    def test_reordering(self):
        _model, dialog = self.dialog(['a.nxt', 'b.nxt'])
        dialog.list.setCurrentRow(1)
        dialog.move_reference(-1)
        self.assertEqual(['b.nxt', 'a.nxt'], self.rows(dialog))
        self.assertEqual(0, dialog.list.currentRow(),
                         'the moved row should still be the selected one')

    def test_removing(self):
        _model, dialog = self.dialog(['a.nxt', 'b.nxt'])
        dialog.list.setCurrentRow(0)
        dialog.remove_reference()
        self.assertEqual(['b.nxt'], self.rows(dialog))

    def test_a_chosen_file_beside_the_layer_is_stored_relative(self):
        # Storing the absolute path would pin the graph to this machine.
        _model, dialog = self.dialog([])
        stored = dialog.as_stored(os.path.join(self.tmp, 'a.nxt'))
        self.assertEqual('a.nxt', stored)

    def test_a_file_elsewhere_is_stored_whole(self):
        _model, dialog = self.dialog([])
        far = tempfile.mkdtemp(prefix='nxt_far_')
        try:
            stored = dialog.as_stored(os.path.join(far, 'a.nxt'))
            self.assertTrue(os.path.isabs(stored),
                            'a path outside the layer stays explicit')
        finally:
            shutil.rmtree(far, ignore_errors=True)

    # -- applying -------------------------------------------------------

    def test_accepting_a_change_applies_it(self):
        model, dialog = self.dialog([])
        dialog.references = ['a.nxt']
        dialog.accept()
        self.assertEqual(['a.nxt'],
                         model.get_layer_references(
                             model.top_layer.real_path))
        self.assertIn('/from_a', model.comp_layer._nodes_path_as_key,
                      'the referenced layer should have loaded')

    def test_cancelling_changes_nothing(self):
        model, dialog = self.dialog([])
        dialog.references = ['a.nxt']
        dialog.reject()
        self.assertEqual([], model.get_layer_references(
            model.top_layer.real_path))
        self.assertNotIn('/from_a', model.comp_layer._nodes_path_as_key)

    def test_accepting_without_a_change_does_not_recomposite(self):
        model, dialog = self.dialog(['a.nxt'])
        rebuilds = []
        real_build = model.stage.build_stage

        def counted(*args, **kwargs):
            rebuilds.append(1)
            return real_build(*args, **kwargs)

        model.stage.build_stage = counted
        try:
            dialog.accept()
        finally:
            model.stage.build_stage = real_build
        self.assertEqual([], rebuilds, 'nothing changed, so nothing to do')

    def test_empty_rows_are_not_stored(self):
        model, dialog = self.dialog([])
        dialog.references = ['a.nxt', '']
        dialog.accept()
        self.assertEqual(['a.nxt'],
                         model.get_layer_references(
                             model.top_layer.real_path))


if __name__ == '__main__':
    unittest.main()
