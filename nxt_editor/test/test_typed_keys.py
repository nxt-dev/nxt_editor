"""Letters typed into a list go to the list, not to window shortcuts.

Q, W and E switch between the Raw, Resolved and Cached views from
anywhere in the window. Typing in the Property Editor's attribute table,
to jump to the attribute starting with what was typed, set them off
instead. The table, and the Hotkey Editor's, now keep the keys that type,
while keys with Ctrl or Alt, and shortcuts set on the panel itself, still
work there. Everywhere else Q, W and E are as they were.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

# External
from Qt import QtCore, QtGui, QtWidgets
from Qt.QtTest import QTest

# Internal
from nxt import DATA_STATE
from nxt_editor import stage_model, typed_keys
from nxt_editor.dockwidgets.property_editor import COLUMNS, PropertyEditor

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

GRAPH = {'version': '1.17', 'alias': 'typing', 'color': '#0052aa',
         'nodes': {'/node': {'attrs': {
             'alpha': {'value': '1'},
             'echo': {'value': '2'},
             'quiet': {'value': '3'},
             'weight': {'value': '4'}}}}}


def key_event(key, text, modifiers=QtCore.Qt.NoModifier):
    return QtGui.QKeyEvent(QtCore.QEvent.ShortcutOverride, key, modifiers,
                           text)


class IsTyping(unittest.TestCase):

    def test_letters_and_shifted_letters_type(self):
        self.assertTrue(typed_keys.is_typing(key_event(QtCore.Qt.Key_Q,
                                                       'q')))
        self.assertTrue(typed_keys.is_typing(key_event(
            QtCore.Qt.Key_Q, 'Q', QtCore.Qt.ShiftModifier)))

    def test_ctrl_and_alt_do_not(self):
        self.assertFalse(typed_keys.is_typing(key_event(
            QtCore.Qt.Key_C, 'c', QtCore.Qt.ControlModifier)))
        self.assertFalse(typed_keys.is_typing(key_event(
            QtCore.Qt.Key_C, 'c', QtCore.Qt.AltModifier)))

    def test_keys_without_text_do_not(self):
        self.assertFalse(typed_keys.is_typing(key_event(QtCore.Qt.Key_Delete,
                                                        '')))
        self.assertFalse(typed_keys.is_typing(key_event(QtCore.Qt.Key_F2,
                                                        '')))


class TypingInTables(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_typed_keys_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'typing.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.win = MainWindow(filepath=path)
        self.win.show()
        self.win.activateWindow()
        QtWidgets.QApplication.setActiveWindow(self.win)
        self.model = self.win.model
        self.model.set_selection(['/node'])
        self.model.data_state = DATA_STATE.RAW
        app.processEvents()
        self.editor = self.win.findChild(PropertyEditor)
        self.table = self.editor.table_view

    def tearDown(self):
        self.model.data_state = DATA_STATE.RAW
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def focus_table(self):
        self.table.setFocus()
        view_model = self.table.model()
        self.table.setCurrentIndex(view_model.index(0, COLUMNS.name))
        app.processEvents()

    def current_name(self):
        return self.table.currentIndex().siblingAtColumn(COLUMNS.name).data()

    def test_q_w_e_still_switch_views_from_the_graph(self):
        # The shortcuts have to work for the table test to mean anything.
        self.win.view.setFocus()
        app.processEvents()
        QTest.keyClick(self.win.view, QtCore.Qt.Key_E)
        app.processEvents()
        self.assertEqual(self.model.data_state, DATA_STATE.CACHED)
        QTest.keyClick(self.win.view, QtCore.Qt.Key_Q)
        app.processEvents()
        self.assertEqual(self.model.data_state, DATA_STATE.RAW)

    def test_typing_in_the_attr_table_finds_attrs(self):
        self.focus_table()
        for key, name in ((QtCore.Qt.Key_E, 'echo'),
                          (QtCore.Qt.Key_W, 'weight'),
                          (QtCore.Qt.Key_Q, 'quiet')):
            QTest.keyClick(self.table, key)
            app.processEvents()
            self.assertEqual(self.model.data_state, DATA_STATE.RAW,
                             'typing in the table switched the view')
            self.assertEqual(self.current_name(), name)
            # Typed one at a time, not as one word.
            QTest.qWait(QtWidgets.QApplication.keyboardInputInterval() + 50)

    def test_ctrl_keys_still_reach_the_panel(self):
        self.focus_table()
        self.table.selectRow(0)
        QTest.keyClick(self.table, QtCore.Qt.Key_C, QtCore.Qt.ControlModifier)
        app.processEvents()
        text = QtWidgets.QApplication.clipboard().text()
        self.assertIn(self.model.ATTRS_CLIPBOARD_KEY, json.loads(text))

    def test_a_letter_set_on_the_panel_still_wins(self):
        action = self.editor.remove_attr_action
        QtWidgets.QAction.setShortcut(action, QtGui.QKeySequence('X'))
        self.addCleanup(QtWidgets.QAction.setShortcut, action,
                        QtGui.QKeySequence())
        self.focus_table()
        self.table.selectRow(0)
        name = self.current_name()
        QTest.keyClick(self.table, QtCore.Qt.Key_X)
        app.processEvents()
        self.assertNotIn(name, self.model.get_node_local_attr_names(
            '/node', self.model.comp_layer))

    def test_typing_a_hotkey_does_not_switch_views(self):
        prefs = self.win.open_preferences('Hotkeys')
        self.addCleanup(prefs.hide)
        app.processEvents()
        hotkeys = prefs.hotkey_list
        entry = hotkeys.entries()[0]
        recorded = []
        with mock.patch.object(
                entry, 'set',
                side_effect=lambda text, parent=None: recorded.append(text)):
            field = hotkeys.start_recording(hotkeys.index_of(entry))
            app.processEvents()
            QTest.keyClick(field, QtCore.Qt.Key_W)
            app.processEvents()
        # The key was taken for the hotkey, not as the shortcut for raw.
        self.assertEqual(['W'], recorded)
        self.assertEqual(self.model.data_state, DATA_STATE.RAW)

if __name__ == '__main__':
    unittest.main()
