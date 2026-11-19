"""Edit > Preferences lists every setting a user can set.

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
        # Hotkeys set here are kept out of the real hotkeys file too.
        hotkeys = user_dir.JsonPref(os.path.join(folder, 'hotkeys.json'))
        patch = mock.patch.object(user_dir, 'hotkeys', hotkeys)
        patch.start()
        self.addCleanup(patch.stop)
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
        return [row.title for row in self.dialog.rows.values()
                if not row.isHidden()]

    def listed(self):
        items = self.dialog.section_list
        return [items.item(i).text() for i in range(items.count())
                if not items.item(i).isHidden()]

    def test_a_section_at_a_time(self):
        names = self.dialog.section_names()
        self.assertEqual(names, self.listed())
        self.assertEqual(preference_editor.sections(), names[:5])
        self.assertEqual(['Hotkeys', 'AI Assistant', 'Environment Variables',
                          'Optional Components'], names[5:])
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
        self.assertEqual(self.dialog.section_names(), self.listed())
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

    def test_the_edit_menu_opens_it(self):
        action = self.win.app_actions.preferences_action
        self.assertIn(action, self.win.menu_bar.edit_menu.actions())
        self.assertEqual('Ctrl+,', action.shortcut().toString())
        # A stand in, so the test does not build a second dialog: doing
        # that crashed Qt on the mac runner.
        with mock.patch.object(preference_editor,
                               'PreferenceEditor') as editor:
            action.trigger()
            action.trigger()
        # One window, kept and shown again.
        editor.assert_called_once_with(main_window=self.win)
        self.assertEqual(2, editor.return_value.show.call_count)

    def test_there_is_no_options_menu(self):
        titles = [action.text() for action in
                  self.win.menu_bar.actions()]
        self.assertNotIn('Options', titles)
        self.assertIn('Edit', titles)



class PagesAndHotkeys(Editing):
    """The pages that were windows of their own, and Hotkeys."""

    def hotkey_row(self, name):
        return next(row for row in self.dialog.rows.values()
                    if getattr(row, 'action', None) is not None and
                    row.title == name)

    def test_a_page_is_made_when_first_shown(self):
        from nxt_editor.optional_components import OptionalComponentsDialog
        self.assertNotIn('Optional Components', self.dialog.pages)
        self.dialog.select_section('Optional Components')
        page = self.dialog.pages['Optional Components']
        self.assertIsInstance(page, OptionalComponentsDialog)
        self.assertIs(page, self.win.optional_components_dialog)
        self.assertTrue(page.close_button.isHidden())
        shown = self.dialog.stack.currentWidget()
        self.assertTrue(shown is page or shown.isAncestorOf(page))

    def test_the_old_ways_in_open_their_page(self):
        with mock.patch.object(preference_editor, 'PreferenceEditor',
                               return_value=self.dialog):
            self.win.app_actions.optional_components_action.trigger()
            self.assertEqual('Optional Components',
                             self.dialog.current_section())
            self.win.app_actions.ai_settings_action.trigger()
            self.assertEqual('AI Assistant', self.dialog.current_section())
            self.win.app_actions.hotkey_editor_action.trigger()
            self.assertEqual('Hotkeys', self.dialog.current_section())
        self.dialog.hide()

    def test_every_action_with_a_hotkey_is_listed(self):
        listed = [row.action for row in self.dialog.rows.values()
                  if getattr(row, 'action', None) is not None]
        for rows in self.win.get_hotkey_map().values():
            for row in rows:
                self.assertIn(row[4], listed)

    def test_a_hotkey_is_set_saved_and_reset(self):
        row = self.hotkey_row('Frame Selection')
        before = row.shortcut()
        self.assertTrue(row.set('Ctrl+Alt+K'))
        self.assertEqual('Ctrl+Alt+K', row.action.shortcut().toString())
        self.assertEqual('Ctrl+Alt+K', user_dir.hotkeys['Frame Selection'])
        self.assertFalse(row.reset_button.isHidden())
        row.reset_button.click()
        self.assertEqual(before, row.shortcut())
        self.assertTrue(row.reset_button.isHidden())

    def test_a_hotkey_can_be_cleared(self):
        row = self.hotkey_row('Frame Selection')
        row.clear_button.click()
        self.assertEqual('', row.action.shortcut().toString())
        self.assertTrue(row.clear_button.isHidden())
        row.reset_button.click()

    def test_a_global_hotkey_can_not_be_taken(self):
        new_graph = self.hotkey_row('New Graph')
        self.assertEqual('Global', new_graph.tag.text())
        row = self.hotkey_row('Frame Selection')
        before = row.shortcut()
        with mock.patch.object(QtWidgets.QMessageBox, 'warning') as warn:
            self.assertFalse(row.set(new_graph.shortcut()))
        warn.assert_called_once()
        self.assertEqual(before, row.shortcut())

    def test_search_finds_hotkeys_by_their_keys(self):
        self.dialog.apply_filter('ctrl+n')
        self.assertIn('New Graph', self.shown_rows())
        self.assertIn('Hotkeys', self.listed())

    def test_search_finds_a_page_and_goes_there(self):
        self.dialog.apply_filter('jedi')
        link = self.dialog.links['Optional Components']
        self.assertFalse(link.isHidden())
        self.assertIn('Optional Components', self.listed())
        link.button.click()
        self.assertEqual('', self.dialog.filter.text())
        self.assertEqual('Optional Components',
                         self.dialog.current_section())

    def test_closing_asks_about_environment_edits(self):
        from nxt_editor import env_dialog
        if not env_dialog.available():
            self.skipTest('This nxt core has no env files.')
        self.dialog.select_section('Environment Variables')
        page = self.dialog.pages['Environment Variables']
        page.dirty.add('a file')
        box = QtWidgets.QMessageBox
        with mock.patch.object(box, 'question',
                               return_value=box.Cancel) as ask:
            self.dialog.show()
            self.dialog.close()
        ask.assert_called_once()
        self.assertTrue(self.dialog.isVisible())
        with mock.patch.object(box, 'question', return_value=box.Discard), \
                mock.patch.object(page, 'load_files') as discard:
            self.dialog.close()
        discard.assert_called_once()
        self.assertFalse(self.dialog.isVisible())


if __name__ == '__main__':
    unittest.main()
