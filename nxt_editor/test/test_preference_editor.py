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
        row = self.dialog.rows[key]
        self.assertTrue(row.reset_button.isHidden())
        self.dialog.editors[key].setValue(3)
        # Reset shows once the value is not the default.
        self.assertFalse(row.reset_button.isHidden())
        row.reset_button.click()
        self.assertEqual(1.0, self.prefs[key])
        self.assertEqual(1.0, self.dialog.editors[key].value())
        self.assertTrue(row.reset_button.isHidden())

    def shown_blocks(self):
        return [name for name, block in self.dialog.blocks.items()
                if not block.isHidden()]

    def shown_rows(self):
        return [row.pref.label for row in self.dialog.rows.values()
                if not row.isHidden()]

    def listed(self):
        items = self.dialog.section_list
        return [items.item(i).text() for i in range(items.count())
                if not items.item(i).isHidden()]

    def test_a_section_at_a_time(self):
        self.assertEqual(preference_editor.sections(), self.listed())
        self.assertEqual('Graph', self.dialog.current_section())
        self.assertEqual(['Graph'], self.shown_blocks())
        self.dialog.select_section('Code Editor')
        self.assertEqual(['Code Editor'], self.shown_blocks())
        editor = self.dialog.editors[user_dir.USER_PREF.CE_COMPLETE_JEDI]
        self.assertTrue(
            self.dialog.blocks['Code Editor'].isAncestorOf(editor))

    def test_search_looks_through_every_section(self):
        # Graph is chosen, and what is found is in other sections too.
        self.dialog.apply_filter('node')
        found = self.shown_blocks()
        self.assertGreater(len(found), 1)
        self.assertEqual(found, self.listed())
        self.assertIn('Code Editor', found)
        # The words found are marked.
        row = self.dialog.rows[user_dir.USER_PREF.ANIMATION]
        self.assertIn('<span', row.name.text() + row.about.text())

    def test_the_list_follows_the_results(self):
        self.dialog.select_section('Code Editor')
        self.dialog.resize(860, 400)
        self.dialog.show()
        self.dialog.apply_filter('node')
        app.processEvents()
        # The first section with results, at the top.
        self.assertEqual('Graph', self.dialog.current_section())
        self.dialog.follow_scroll(self.dialog.blocks['Running'].y())
        self.assertEqual('Running', self.dialog.current_section())
        # Choosing one moves to its results, still searching.
        self.dialog.select_section('Editing')
        bar = self.dialog.area.verticalScrollBar()
        # As far as it scrolls, near the end.
        self.assertEqual(min(self.dialog.blocks['Editing'].y(),
                             bar.maximum()), bar.value())
        self.assertEqual('Editing', self.dialog.current_section())
        self.assertTrue(self.dialog.words)
        # Cleared, the section chosen before the search is back.
        self.dialog.apply_filter('')
        self.assertEqual('Code Editor', self.dialog.current_section())
        self.assertEqual(['Code Editor'], self.shown_blocks())

    def test_search_finds_one(self):
        self.dialog.apply_filter('zoom speed')
        self.assertEqual(['Drag Zoom Speed'], self.shown_rows())
        section = pref(user_dir.USER_PREF.ZOOM_MULT).section
        self.assertEqual([section], self.listed())
        self.assertEqual([section], self.shown_blocks())
        self.assertEqual(section, self.dialog.current_section())

    def test_clearing_the_search_brings_the_section_back(self):
        self.dialog.select_section('Running')
        self.dialog.apply_filter('grid')
        self.dialog.apply_filter('')
        self.assertEqual(['Running'], self.shown_blocks())
        self.assertEqual(preference_editor.sections(), self.listed())
        self.assertFalse(any(row.isHidden()
                             for row in self.dialog.rows.values()))
        row = self.dialog.rows[user_dir.USER_PREF.SHOW_GRID]
        self.assertNotIn('<span', row.name.text())

    def test_nothing_found_says_so(self):
        self.dialog.apply_filter('no preference is called this')
        self.assertEqual([], self.shown_blocks())
        self.assertFalse(self.dialog.nothing_found.isHidden())
        self.dialog.apply_filter('')
        self.assertTrue(self.dialog.nothing_found.isHidden())

    def test_searches_once_typing_stops(self):
        self.dialog.filter.setText('zoom')
        # Not on every key.
        self.assertTrue(self.dialog.search_timer.isActive())
        self.assertEqual(['Graph'], self.shown_blocks())
        self.assertEqual(preference_editor.SEARCH_DELAY_MS,
                         self.dialog.search_timer.interval())
        self.dialog.search_timer.timeout.emit()
        self.assertIn('Drag Zoom Speed', self.shown_rows())

    def test_enter_searches_at_once(self):
        self.dialog.filter.setText('zoom speed')
        self.dialog.filter.returnPressed.emit()
        self.assertFalse(self.dialog.search_timer.isActive())
        self.assertEqual(['Drag Zoom Speed'], self.shown_rows())

    def test_clearing_does_not_wait(self):
        self.dialog.filter.setText('zoom')
        self.dialog.search_now()
        self.dialog.filter.clear()
        self.assertFalse(self.dialog.search_timer.isActive())
        self.assertEqual(['Graph'], self.shown_blocks())

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


if __name__ == '__main__':
    unittest.main()
