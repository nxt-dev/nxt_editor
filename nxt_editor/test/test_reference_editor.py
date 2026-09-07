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


class Fixture(object):
    """A graph on disk and a dialog on it.

    Split out so the classes below can share it without inheriting each
    other's tests and running them all again.
    """

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


@unittest.skipUnless(HAS_REF_EXPAND, NEEDS_CORE)
class ReferenceEditorDialog(Fixture, unittest.TestCase):

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


@unittest.skipUnless(HAS_REF_EXPAND, NEEDS_CORE)
class ReferenceEditorLayout(Fixture, unittest.TestCase):
    """The shape of it, which is what made it unpleasant to use.

    These are about arrangement rather than behaviour, but a control
    that moves out from under the pointer is a behaviour too.
    """

    def layer_row(self):
        return self.dialog(['a.nxt'])[1].layout().itemAt(0).layout()

    def test_the_toggle_sits_beside_the_layer_picker(self):
        row = self.layer_row()
        widgets = [row.itemAt(i).widget() for i in range(row.count())]
        widgets = [w for w in widgets if w is not None]
        combo = [w for w in widgets if isinstance(w, QtWidgets.QComboBox)][0]
        toggle = [w for w in widgets
                  if isinstance(w, QtWidgets.QToolButton)][0]
        self.assertEqual(widgets.index(combo) + 1, widgets.index(toggle),
                         'the toggle should be the next thing after the '
                         'layer picker')

    def test_the_picker_does_not_take_the_stretch(self):
        # With the stretch on the combo, the toggle slid left and right as
        # one layer name replaced another.
        row = self.layer_row()
        for index in range(row.count()):
            item = row.itemAt(index)
            if item.widget() is not None:
                self.assertEqual(0, item.widget().sizePolicy()
                                 .horizontalStretch(),
                                 'no widget in this row should stretch')

    def test_the_controls_are_icon_buttons(self):
        _model, dialog = self.dialog(['a.nxt'])
        for button in (dialog.add_button, dialog.remove_button,
                       dialog.up_button, dialog.down_button,
                       dialog.resolved_button):
            self.assertIsInstance(button, QtWidgets.QToolButton)
            self.assertTrue(button.toolTip(), 'an icon needs a tooltip')
            self.assertTrue(not button.icon().isNull() or button.text(),
                            'a button should show an icon or say something')

    def test_the_status_line_hides_when_it_has_nothing_to_say(self):
        _model, dialog = self.dialog(['a.nxt'])
        self.assertFalse(dialog.status.isVisible())
        self.assertEqual('', dialog.status.text())

    def test_the_status_line_appears_when_something_is_missing(self):
        _model, dialog = self.dialog(['not_here.nxt'])
        self.assertTrue(dialog.status.text())
        self.assertIn('could not be found', dialog.status.text())


@unittest.skipUnless(HAS_REF_EXPAND, NEEDS_CORE)
class ReferenceEditorDragging(Fixture, unittest.TestCase):
    """Dragging a row is the direct way to say what the order should be."""

    def move_row(self, dialog, source, destination):
        model = dialog.list.model()
        moved = model.moveRow(QtCore.QModelIndex(), source,
                              QtCore.QModelIndex(), destination)
        self.assertTrue(moved, 'the list would not move a row')

    def test_dragging_reorders_the_stored_list(self):
        _model, dialog = self.dialog(['a.nxt', 'b.nxt'])
        self.move_row(dialog, 0, 2)
        self.assertEqual(['b.nxt', 'a.nxt'], dialog.references)

    def test_dragging_while_resolved_still_stores_partial_paths(self):
        # The rows say the resolved path in this mode. Reading the order
        # back off the text would write this machine's answers into the
        # layer and pin the graph here.
        _model, dialog = self.dialog(['a.nxt', 'b.nxt'])
        dialog.resolved_button.setChecked(True)
        self.move_row(dialog, 0, 2)
        self.assertEqual(['b.nxt', 'a.nxt'], dialog.references,
                         'dragging in the resolved view stored resolved '
                         'paths')
        for reference in dialog.references:
            self.assertFalse(os.path.isabs(reference))

    def test_dragging_a_missing_reference_keeps_it(self):
        _model, dialog = self.dialog(['a.nxt', 'not_here.nxt'])
        self.move_row(dialog, 1, 0)
        self.assertEqual(['not_here.nxt', 'a.nxt'], dialog.references)


@unittest.skipUnless(HAS_REF_EXPAND, NEEDS_CORE)
class AddingByTyping(Fixture, unittest.TestCase):
    """Typing a path in, which is the only way to write a partial one.

    A file picker can only offer files that exist on this machine, so
    without this there was no way to add $SHOW/lib/rig.nxt at all.
    """

    def test_typing_a_partial_path_and_pressing_enter(self):
        _model, dialog = self.dialog([])
        dialog.add_edit.setText('$SHOW/lib/rig.nxt')
        dialog.add_edit.returnPressed.emit()
        self.assertEqual(['$SHOW/lib/rig.nxt'], dialog.references)
        self.assertEqual(['$SHOW/lib/rig.nxt'], self.rows(dialog))

    def test_it_is_stored_exactly_as_written(self):
        # Not made relative to the layer, not resolved against this
        # machine. Rewriting it would undo the reason for typing it.
        _model, dialog = self.dialog([])
        for typed in ('$SHOW/lib/rig.nxt', 'sibling.nxt',
                      '../up_one/thing.nxt', 'a.nxt'):
            dialog.add_edit.setText(typed)
            dialog.add_edit.returnPressed.emit()
        self.assertEqual(['$SHOW/lib/rig.nxt', 'sibling.nxt',
                          '../up_one/thing.nxt', 'a.nxt'],
                         dialog.references)

    def test_enter_adds_rather_than_applying_the_dialog(self):
        # The default button would otherwise take the Return and apply,
        # throwing away what was just typed.
        results = []
        _model, dialog = self.dialog([])
        dialog.accepted.connect(lambda: results.append('accepted'))
        dialog.add_edit.setText('typed.nxt')
        dialog.add_edit.returnPressed.emit()
        self.assertEqual([], results, 'Enter applied the dialog')
        self.assertTrue(dialog.isVisible() or not dialog.result(),
                        'the dialog closed on Enter')
        self.assertEqual(['typed.nxt'], dialog.references)

    def test_the_field_clears_so_the_next_one_can_be_typed(self):
        _model, dialog = self.dialog([])
        dialog.add_edit.setText('one.nxt')
        dialog.add_edit.returnPressed.emit()
        self.assertEqual('', dialog.add_edit.text())

    def test_nothing_is_added_from_an_empty_field(self):
        _model, dialog = self.dialog(['a.nxt'])
        dialog.add_edit.setText('   ')
        dialog.add_edit.returnPressed.emit()
        self.assertEqual(['a.nxt'], dialog.references)

    def test_the_add_button_waits_for_something_to_add(self):
        _model, dialog = self.dialog([])
        self.assertFalse(dialog.add_button.isEnabled())
        dialog.add_edit.setText('something.nxt')
        self.assertTrue(dialog.add_button.isEnabled())
        dialog.add_button.click()
        self.assertEqual(['something.nxt'], dialog.references)
        self.assertFalse(dialog.add_button.isEnabled(),
                         'the field emptied, so there is nothing to add')

    def test_a_typed_path_that_resolves_is_not_flagged(self):
        _model, dialog = self.dialog([])
        dialog.add_edit.setText('a.nxt')
        dialog.add_edit.returnPressed.emit()
        self.assertNotIn('could not be found', dialog.status.text())

    def test_a_typed_path_that_does_not_resolve_is_flagged_but_kept(self):
        _model, dialog = self.dialog([])
        dialog.add_edit.setText('$SHOW/lib/rig.nxt')
        dialog.add_edit.returnPressed.emit()
        self.assertIn('could not be found', dialog.status.text())
        self.assertEqual(['$SHOW/lib/rig.nxt'], dialog.references)

    def test_a_typed_reference_applies(self):
        model, dialog = self.dialog([])
        dialog.add_edit.setText('a.nxt')
        dialog.add_edit.returnPressed.emit()
        dialog.accept()
        self.assertEqual(['a.nxt'], model.get_layer_references(
            model.top_layer.real_path))
        self.assertIn('/from_a', model.comp_layer._nodes_path_as_key)


if __name__ == '__main__':
    unittest.main()
