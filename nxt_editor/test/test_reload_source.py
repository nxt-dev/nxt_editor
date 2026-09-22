"""Reloading a layer, and what it is built from, from disk.

A layer is rarely one file, so asking for the latest of one means asking
which of the files behind it to go and get. The dialog offers the whole
chain with everything checked, because that is usually what is meant, and
the toggle is there for the times it is not.

What comes back is a different set of nodes, and sometimes a different
set of layers: a file that has come to reference something else brings
that with it, so layers can arrive, go, or change the order they stack
in. The graph is composited and redrawn whole and the layer tree is told
to start over, because it hands out indices that point straight at layer
objects.

It goes on the undo stack like any other edit: unsaved work on a
reloaded layer is gone, but the reload itself can be taken back.
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
from nxt_editor.dialogs import ReloadSourceDialog
from nxt_editor.main_window import MainWindow

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

CHECKED = QtCore.Qt.Checked
UNCHECKED = QtCore.Qt.Unchecked


def write_graph(path, name, references=(), node_names=()):
    data = {"version": "1.17", "alias": name, "mute": False, "solo": False,
            "references": list(references), "meta_data": {},
            "nodes": {"/" + n: {} for n in node_names}}
    with open(path, 'w') as file_object:
        json.dump(data, file_object, indent=4)
    return path


class ReloadingSource(unittest.TestCase):

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix='nxt_reload_src_')
        self.write('deep', node_names=['from_deep'])
        self.write('a', references=['deep.nxt'], node_names=['from_a'])
        self.top_path = self.write('top', references=['a.nxt'],
                                   node_names=['from_top'])
        self.win = MainWindow(filepath=self.top_path)
        self.win.show()
        app.processEvents()
        self.model = self.win.model

    def tearDown(self):
        # Reloading marks nothing unsaved, but a test that edits does, and
        # closing a window with unsaved layers asks a question nothing
        # here can answer.
        self.model.effected_layers.clear()
        # close() only hides it; the widget tree is finished with here
        # rather than left for whatever collects next.
        self.win.close()
        app.processEvents()
        self.win.deleteLater()
        app.processEvents()
        self.win = None
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, references=(), node_names=()):
        return write_graph(os.path.join(self.tmp, '%s.nxt' % name), name,
                           references=references, node_names=node_names)

    def layer(self, alias):
        for layer in self.model.stage._sub_layers:
            if layer.get_alias() == alias:
                return layer
        return None

    def dialog(self, alias='top'):
        return ReloadSourceDialog(self.model, self.layer(alias),
                                  parent=self.win)

    def comped(self):
        return sorted(self.model.comp_layer._nodes_path_as_key)

    def reload(self, aliases):
        paths = [self.layer(a).real_path for a in aliases]
        result = self.model.reload_layers(paths)
        app.processEvents()
        return result

    # -- what the dialog offers -----------------------------------------

    def test_it_lists_the_layer_and_everything_it_references(self):
        dialog = self.dialog()
        self.assertEqual(['top', 'a', 'deep'],
                         [l.get_alias() for _, l in dialog.rows])

    def test_the_rows_are_indented_by_how_deep_the_reference_is(self):
        rows = self.dialog().rows
        indents = [len(i.text()) - len(i.text().lstrip()) for i, _ in rows]
        self.assertEqual([0, 4, 8], indents)

    def test_a_file_loaded_twice_gets_one_row(self):
        self.write('b', references=['deep.nxt'], node_names=['from_b'])
        self.write('top', references=['a.nxt', 'b.nxt'],
                   node_names=['from_top'])
        self.win.load_file(self.top_path)
        app.processEvents()
        self.model = self.win.model
        aliases = [l.get_alias() for _, l in self.dialog().rows]
        self.assertEqual(['top', 'a', 'deep', 'b'], aliases,
                         'one row decides one file, however many layers '
                         'that file was loaded into')

    def test_everything_starts_checked(self):
        rows = self.dialog().rows
        self.assertTrue(rows)
        for item, _ in rows:
            self.assertEqual(CHECKED, item.checkState())

    def test_a_layer_with_unsaved_changes_says_so(self):
        self.model.add_node(name='unsaved_edit', layer=self.model.top_layer)
        app.processEvents()
        item = self.dialog().rows[0][0]
        self.assertIn('unsaved', item.text())

    # -- the toggle -----------------------------------------------------

    def test_it_offers_to_clear_when_everything_is_checked(self):
        dialog = self.dialog()
        self.assertTrue(dialog.check_all_button.isChecked())
        self.assertEqual('Uncheck All', dialog.check_all_button.text())

    def test_pressing_it_clears_every_box(self):
        dialog = self.dialog()
        dialog.check_all_button.click()
        for item, _ in dialog.rows:
            self.assertEqual(UNCHECKED, item.checkState())
        self.assertEqual('Check All', dialog.check_all_button.text())

    def test_pressing_it_again_checks_every_box(self):
        dialog = self.dialog()
        dialog.check_all_button.click()
        dialog.check_all_button.click()
        for item, _ in dialog.rows:
            self.assertEqual(CHECKED, item.checkState())
        self.assertEqual('Uncheck All', dialog.check_all_button.text())

    def test_it_follows_a_box_unchecked_by_hand(self):
        dialog = self.dialog()
        dialog.rows[0][0].setCheckState(UNCHECKED)
        self.assertFalse(dialog.check_all_button.isChecked())
        self.assertEqual('Check All', dialog.check_all_button.text(),
                         'the button still claimed everything was checked')

    def test_there_is_nothing_to_reload_with_nothing_checked(self):
        dialog = self.dialog()
        dialog.check_all_button.click()
        self.assertFalse(dialog.reload_button.isEnabled())

    def test_the_checked_rows_are_what_comes_out(self):
        dialog = self.dialog()
        dialog.rows[0][0].setCheckState(UNCHECKED)
        self.assertEqual(['a', 'deep'],
                         [l.get_alias() for l in dialog.checked_layers()])

    # -- and what reloading does ----------------------------------------

    def test_it_reads_the_checked_layers_again(self):
        self.write('a', references=['deep.nxt'],
                   node_names=['from_a', 'a_added'])
        self.assertNotIn('/a_added', self.comped())
        self.reload(['a'])
        self.assertIn('/a_added', self.comped())

    def test_it_leaves_the_unchecked_ones_alone(self):
        self.write('deep', node_names=['from_deep', 'deep_added'])
        self.write('a', references=['deep.nxt'],
                   node_names=['from_a', 'a_added'])
        self.reload(['a'])
        self.assertIn('/a_added', self.comped())
        self.assertNotIn('/deep_added', self.comped())

    def test_the_graph_is_composited_again(self):
        comp_changes = []
        self.model.comp_layer_changed.connect(comp_changes.append)
        self.write('a', references=['deep.nxt'], node_names=['a_added'])
        self.reload(['a'])
        self.assertTrue(comp_changes,
                        'nothing said the comp had changed, so the graph, '
                        'the build view and the workflow tools are still '
                        'describing the layer as it was')

    def test_the_graph_is_drawn_again(self):
        self.write('a', references=['deep.nxt'], node_names=['a_added'])
        self.reload(['a'])
        drawn = self.win.view.get_node_graphic('/a_added')
        self.assertIsNotNone(drawn, 'the new node was never drawn')

    def test_it_is_one_undo(self):
        before = self.comped()
        self.write('deep', node_names=['deep_added'])
        self.write('a', references=['deep.nxt'], node_names=['a_added'])
        self.reload(['a', 'deep'])
        self.assertNotEqual(before, self.comped())
        self.assertEqual(1, self.model.undo_stack.count())
        self.model.undo()
        app.processEvents()
        self.assertEqual(before, self.comped())

    def test_undoing_it_does_not_read_the_file_again(self):
        # By the time somebody undoes, the file may have moved on again.
        # What undo owes them is what they had, not a third thing.
        self.write('a', references=['deep.nxt'], node_names=['first'])
        self.reload(['a'])
        self.write('a', references=['deep.nxt'], node_names=['second'])
        self.model.undo()
        app.processEvents()
        self.assertIn('/from_a', self.comped())
        self.assertNotIn('/second', self.comped())

    def test_a_reloaded_layer_is_not_unsaved_any_more(self):
        self.model.add_node(name='unsaved_edit', layer=self.layer('a'))
        app.processEvents()
        path = self.layer('a').real_path
        self.assertIn(path, self.model.effected_layers)
        self.reload(['a'])
        self.assertNotIn(path, self.model.effected_layers,
                         'what is in memory is what is on disk again, so '
                         'there is nothing left to save')

    def test_undoing_the_reload_marks_it_unsaved_again(self):
        self.model.add_node(name='unsaved_edit', layer=self.layer('a'))
        app.processEvents()
        path = self.layer('a').real_path
        self.reload(['a'])
        self.model.undo()
        app.processEvents()
        self.assertIn(path, self.model.effected_layers)

    def test_reloading_nothing_does_nothing(self):
        self.assertFalse(self.model.reload_layers([]))
        self.assertEqual(0, self.model.undo_stack.count())

    # -- and to the stack of layers -------------------------------------

    def stacked(self):
        return [l.get_alias() for l in self.model.stage._sub_layers]

    def test_a_reference_added_since_is_loaded(self):
        self.write('new', node_names=['from_new'])
        self.write('top', references=['a.nxt', 'new.nxt'],
                   node_names=['from_top'])
        self.reload(['top'])
        self.assertEqual(['top', 'a', 'deep', 'new'], self.stacked())
        self.assertIn('/from_new', self.comped())

    def test_a_reference_taken_out_since_is_let_go(self):
        self.write('top', references=[], node_names=['from_top'])
        self.reload(['top'])
        self.assertEqual(['top'], self.stacked())
        self.assertEqual(['/from_top'], self.comped())

    def test_references_put_in_a_different_order_restack(self):
        self.write('b', node_names=['from_b'])
        self.write('top', references=['a.nxt', 'b.nxt'],
                   node_names=['from_top'])
        self.win.load_file(self.top_path)
        app.processEvents()
        self.model = self.win.model
        self.assertEqual(['top', 'a', 'deep', 'b'], self.stacked())
        self.write('top', references=['b.nxt', 'a.nxt'],
                   node_names=['from_top'])
        self.reload(['top'])
        self.assertEqual(['top', 'b', 'a', 'deep'], self.stacked())

    def test_the_layer_tree_is_told_the_stack_changed(self):
        # It hands out indices that point straight at layer objects, so a
        # repaint against the old shape reaches for layers that are gone.
        resets = []
        self.win.layer_manager.layer_tree.model().modelReset.connect(
            lambda: resets.append(True))
        self.write('top', references=[], node_names=['from_top'])
        self.reload(['top'])
        self.assertTrue(resets, 'the layer tree was left holding indices '
                                'into layers that are not loaded')

    def test_the_layer_tree_is_told_about_a_reorder_too(self):
        self.write('b', node_names=['from_b'])
        self.write('top', references=['a.nxt', 'b.nxt'],
                   node_names=['from_top'])
        self.win.load_file(self.top_path)
        app.processEvents()
        self.model = self.win.model
        resets = []
        self.win.layer_manager.layer_tree.model().modelReset.connect(
            lambda: resets.append(True))
        self.write('top', references=['b.nxt', 'a.nxt'],
                   node_names=['from_top'])
        self.reload(['top'])
        self.assertTrue(resets, 'the same layers on different rows, and '
                                'the tree was not told to start over')

    def test_a_display_layer_that_went_falls_back_to_the_top(self):
        self.model.set_display_layer(self.layer('a'))
        app.processEvents()
        self.write('top', references=[], node_names=['from_top'])
        self.reload(['top'])
        self.assertIn(self.model.display_layer, self.model.stage._sub_layers)
        self.assertIs(self.model.top_layer, self.model.display_layer)

    def test_a_target_layer_that_went_falls_back_to_the_top(self):
        self.model.set_target_layer(self.layer('a').real_path)
        app.processEvents()
        self.write('top', references=[], node_names=['from_top'])
        self.reload(['top'])
        self.assertIn(self.model.target_layer, self.model.stage._sub_layers)

    def test_undoing_puts_the_stack_back(self):
        before = self.stacked()
        self.write('new', node_names=['from_new'])
        self.write('top', references=['new.nxt'], node_names=['from_top'])
        self.reload(['top'])
        self.assertEqual(['top', 'new'], self.stacked())
        self.model.undo()
        app.processEvents()
        self.assertEqual(before, self.stacked())
        self.assertIn('/from_deep', self.comped())


if __name__ == '__main__':
    unittest.main()
