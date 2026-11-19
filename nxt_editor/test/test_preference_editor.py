"""Options > Preferences lists every preference a user can set.

Each is set straight away, through its menu toggle when it has one, so
the menu agrees and the editor does what the toggle does.
"""
# Builtin
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

# External
from Qt import QtWidgets

# Internal
from nxt_editor import preference_editor, stage_model, user_dir
from nxt_editor.preference_editor import (PREFERENCES, PreferenceEditor,
                                          find_action)

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402


def pref(key):
    return next(p for p in PREFERENCES if p.key == key)


class Registry(unittest.TestCase):

    def test_every_key_is_a_known_preference(self):
        known = {value for name, value in vars(user_dir.USER_PREF).items()
                 if name.isupper()}
        for p in PREFERENCES:
            self.assertIn(p.key, known, p.label)

    def test_each_is_listed_once(self):
        keys = [p.key for p in PREFERENCES]
        self.assertEqual(len(keys), len(set(keys)))


class Editing(unittest.TestCase):

    def setUp(self):
        folder = tempfile.mkdtemp(prefix='nxt_prefs_')
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        prefs = user_dir.JsonPref(os.path.join(folder, 'prefs.json'))
        patch = mock.patch.object(user_dir, 'user_prefs', prefs)
        patch.start()
        self.addCleanup(patch.stop)
        self.prefs = prefs
        self.win = MainWindow()
        self.dialog = PreferenceEditor(main_window=self.win)

    def tearDown(self):
        self.dialog.deleteLater()
        with mock.patch.object(stage_model.StageModel,
                               'get_unsaved_changes', return_value=[]):
            self.win.close()
            app.processEvents()

    def test_every_menu_toggle_named_is_there(self):
        for p in PREFERENCES:
            if p.action:
                self.assertIsNotNone(find_action(self.win, p), p.action)

    def test_menu_toggles_start_as_listed(self):
        # With nothing saved, the table and the menus show the same.
        for p in PREFERENCES:
            action = find_action(self.win, p)
            # Python Analysis shows off without jedi, keeping the choice.
            if p.key == user_dir.USER_PREF.CE_COMPLETE_JEDI:
                continue
            if action is not None and action.isCheckable():
                self.assertEqual(p.default, action.isChecked(), p.label)

    def test_a_toggle_goes_through_its_menu_action(self):
        snap = self.win.alignment_actions.snap_action
        self.assertFalse(snap.isChecked())
        self.dialog.editors[user_dir.USER_PREF.GRID_SNAP].setChecked(True)
        self.assertTrue(snap.isChecked())
        self.assertTrue(self.prefs[user_dir.USER_PREF.GRID_SNAP])

    def test_a_pref_action_is_found_by_its_key(self):
        grid = self.win.view_actions.grid_action
        self.assertIs(grid, find_action(self.win,
                                        pref(user_dir.USER_PREF.SHOW_GRID)))
        self.dialog.editors[user_dir.USER_PREF.SHOW_GRID].setChecked(False)
        self.assertFalse(grid.isChecked())
        self.assertFalse(self.prefs[user_dir.USER_PREF.SHOW_GRID])

    def test_a_value_without_a_menu_is_written(self):
        self.dialog.editors[user_dir.USER_PREF.ZOOM_MULT].setValue(2.5)
        self.assertEqual(2.5, self.prefs[user_dir.USER_PREF.ZOOM_MULT])
        box = self.dialog.editors[user_dir.USER_PREF.EXEC_FRAMING]
        box.setCurrentIndex(box.findText('Always'))
        self.assertEqual(stage_model.EXEC_FRAMING.ALWAYS,
                         self.prefs[user_dir.USER_PREF.EXEC_FRAMING])

    def test_reset_to_default(self):
        key = user_dir.USER_PREF.ZOOM_MULT
        self.dialog.editors[key].setValue(3)
        item = self.find_item(key)
        self.dialog.tree.setCurrentItem(item)
        self.dialog.reset_selected()
        self.assertEqual(1.0, self.prefs[key])
        self.assertEqual(1.0, self.dialog.editors[key].value())

    def test_filtering(self):
        self.dialog.apply_filter('zoom speed')
        tree = self.dialog.tree
        sections = [tree.topLevelItem(i)
                    for i in range(tree.topLevelItemCount())]
        shown = [section.child(r).text(0) for section in sections
                 for r in range(section.childCount())
                 if not section.child(r).isHidden()]
        self.assertEqual(['Drag Zoom Speed'], shown)

    def test_python_analysis_without_jedi_is_only_kept(self):
        from nxt_editor.dockwidgets import code_completion
        key = user_dir.USER_PREF.CE_COMPLETE_JEDI
        with mock.patch.object(code_completion.JEDI, 'installed',
                               return_value=False), \
                mock.patch.object(self.win, 'offer_jedi',
                                  create=True) as offer:
            self.dialog.editors[key].setChecked(False)
            self.dialog.editors[key].setChecked(True)
        offer.assert_not_called()
        self.assertTrue(self.prefs[key])

    def test_options_menu_opens_it(self):
        # A stand in, so the test does not build a second dialog: doing
        # that crashed Qt on the mac runner.
        with mock.patch.object(preference_editor,
                               'PreferenceEditor') as editor:
            self.win.app_actions.preferences_action.trigger()
        editor.assert_called_once_with(main_window=self.win)
        editor.return_value.exec_.assert_called_once()

    def find_item(self, key):
        tree = self.dialog.tree
        for s in range(tree.topLevelItemCount()):
            section = tree.topLevelItem(s)
            for r in range(section.childCount()):
                item = section.child(r)
                if item.data(0, preference_editor.KEY_ROLE) == key:
                    return item


if __name__ == '__main__':
    unittest.main()
