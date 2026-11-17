"""Camera bookmarks: named views of a graph, saved with it, to go back to
from the Bookmarks menu or with Ctrl+1 to Ctrl+4."""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

# External
from Qt import QtGui, QtWidgets

# Internal
from nxt.session import Session
from nxt_editor import bookmarks, stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

GRAPH = {
    'version': '1.17', 'alias': 'marks',
    'nodes': {'/a': {}, '/far': {}},
    'meta_data': {'positions': {'/a': [0.0, 0.0],
                                '/far': [3000.0, 2000.0]}},
}


class Records(unittest.TestCase):

    def test_names_count_up_past_ones_taken(self):
        records = [bookmarks.make('Bookmark 2', (0, 0, 1, 1))]
        self.assertEqual('Bookmark 3', bookmarks.unique_name(records))
        self.assertEqual('Bookmark 1', bookmarks.unique_name([]))

    def test_hand_edited_junk_is_left_out(self):
        layer = mock.Mock()
        layer._input_metadata = {bookmarks.META_KEY: [
            {'name': 'ok', 'rect': [0, 0, 10, 10]},
            {'name': 'no size', 'rect': [0, 0, 0, 10]},
            {'rect': 'nonsense'}, 'not a bookmark',
            {'rect': [1, 2, 3, 4]}]}
        found = bookmarks.layer_bookmarks(layer)
        self.assertEqual(['ok', 'Bookmark'], [r['name'] for r in found])
        self.assertEqual([1.0, 2.0, 3.0, 4.0], found[1]['rect'])


class InTheView(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_marks_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = os.path.join(self.tmp, 'marks.nxt')
        with open(self.path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.win = MainWindow(filepath=self.path)
        self.win.show()
        app.processEvents()
        self.view = self.win.view
        self.model = self.view.model
        self.view.ensure_drawn()
        app.processEvents()

    def tearDown(self):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def look_at(self, x, y, scale=1.0):
        self.view.resetTransform()
        self.view.scale(scale, scale)
        self.view.centerOn(x, y)
        app.processEvents()

    def center(self):
        return self.view.view_rect().center()

    def names(self):
        return [r['name'] for r in self.model.get_bookmarks()]

    def test_adding_one_saves_the_view_in_one_undo(self):
        self.look_at(3000, 2000, .5)
        rect = self.view.view_rect()
        before = self.model.undo_stack.count()
        self.assertEqual(0, self.view.add_bookmark('Far away'))
        self.assertEqual(before + 1, self.model.undo_stack.count())
        records = self.model.get_bookmarks()
        self.assertEqual('Far away', records[0]['name'])
        self.assertEqual([rect.x(), rect.y(), rect.width(), rect.height()],
                         records[0]['rect'])
        self.assertIn(self.model.top_layer.real_path,
                      self.model.effected_layers)
        self.model.undo_stack.undo()
        self.assertEqual([], self.model.get_bookmarks())

    def test_going_to_one_shows_that_view_again(self):
        self.look_at(3000, 2000, .5)
        self.view.add_bookmark('Far away')
        width = self.view.view_rect().width()
        self.look_at(0, 0, 1.5)
        self.assertTrue(self.view.go_to_bookmark(0))
        self.assertAlmostEqual(3000, self.center().x(), delta=5)
        self.assertAlmostEqual(2000, self.center().y(), delta=5)
        self.assertAlmostEqual(width, self.view.view_rect().width(),
                               delta=width * .02)
        self.assertFalse(self.view.go_to_bookmark(5))

    def test_ctrl_1_goes_to_the_first(self):
        actions = self.win.view_actions.go_to_bookmark_actions
        self.assertEqual(['Ctrl+1', 'Ctrl+2', 'Ctrl+3', 'Ctrl+4'],
                         [a.shortcut().toString() for a in actions])
        self.look_at(3000, 2000)
        self.view.add_bookmark('Far away')
        self.look_at(0, 0)
        actions[0].trigger()
        self.assertAlmostEqual(3000, self.center().x(), delta=5)

    def test_rename_and_delete_are_undoable(self):
        self.view.add_bookmark('One')
        self.view.add_bookmark('Two')
        self.model.rename_bookmark(0, 'First')
        self.assertEqual(['First', 'Two'], self.names())
        self.model.remove_bookmark(0)
        self.assertEqual(['Two'], self.names())
        self.model.undo_stack.undo()
        self.model.undo_stack.undo()
        self.assertEqual(['One', 'Two'], self.names())

    def test_they_are_saved_with_the_graph(self):
        self.look_at(3000, 2000)
        self.view.add_bookmark('Far away')
        self.win.save_layer(self.model.top_layer)
        with open(self.path) as fp:
            saved = json.load(fp)
        self.assertEqual('Far away',
                         saved['meta_data']['bookmarks'][0]['name'])
        reopened = stage_model.StageModel(Session().load_file(self.path))
        self.assertEqual(self.model.get_bookmarks(),
                         reopened.get_bookmarks())

    def test_add_asks_for_a_name(self):
        with mock.patch.object(QtWidgets.QInputDialog, 'getText',
                               return_value=('Rig build', True)) as ask:
            self.win.view_actions.add_bookmark_action.trigger()
        self.assertEqual('Bookmark 1', ask.call_args[0][4])
        self.assertEqual(['Rig build'], self.names())
        with mock.patch.object(QtWidgets.QInputDialog, 'getText',
                               return_value=('', False)):
            self.view.add_bookmark_named()
        self.assertEqual(1, len(self.model.get_bookmarks()))

    def test_rename_asks_for_the_new_name(self):
        self.view.add_bookmark('One')
        with mock.patch.object(QtWidgets.QInputDialog, 'getText',
                               return_value=('Better', True)) as ask:
            self.view.rename_bookmark_named(0)
        self.assertEqual('One', ask.call_args[0][4])
        self.assertEqual(['Better'], self.names())

    def menu_texts(self, menu):
        self.win.view_actions.fill_bookmarks_menu(menu)
        return [a.text() for a in menu.actions() if not a.isSeparator()]

    def test_the_menu_lists_them_to_go_to_rename_and_delete(self):
        menu = self.win.menu_bar.bookmarks_menu
        self.assertIn(menu.menuAction(),
                      self.win.menu_bar.view_menu.actions())
        self.assertEqual(['Add Bookmark...', 'No bookmarks yet'],
                         self.menu_texts(menu))
        self.look_at(3000, 2000)
        self.view.add_bookmark('Far away')
        texts = self.menu_texts(menu)
        # The menu shows the shortcut as the platform writes it, which on
        # macOS is the command key's symbol rather than Ctrl.
        native = QtGui.QKeySequence('Ctrl+1').toString(
            QtGui.QKeySequence.NativeText)
        self.assertEqual('Far away\t' + native, texts[1])
        self.assertEqual(['Rename Bookmark', 'Delete Bookmark'], texts[2:])
        self.look_at(0, 0)
        [a for a in menu.actions() if a.text() == texts[1]][0].trigger()
        self.assertAlmostEqual(3000, self.center().x(), delta=5)
        delete = [a for a in menu.actions()
                  if a.text() == 'Delete Bookmark'][0].menu()
        delete.actions()[0].trigger()
        self.assertEqual([], self.model.get_bookmarks())

    def test_the_toolbar_has_the_menu(self):
        toolbar = self.win.findChild(QtWidgets.QToolBar, 'Display Tools')
        self.assertIs(toolbar.bookmarks_menu,
                      toolbar.bookmarks_button.menu())


if __name__ == '__main__':
    unittest.main()
