"""Right clicking a toolbar lists the panels and toolbars to show or hide.
Every row needs a name, so each toolbar has a title of its own."""
# Builtin
import sys
import unittest
from unittest import mock

# External
from Qt import QtWidgets

# Internal
from nxt_editor import stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402


class ToolbarMenu(unittest.TestCase):

    def setUp(self):
        self.win = MainWindow()
        self.win.show()
        app.processEvents()
        self.toolbars = self.win.findChildren(QtWidgets.QToolBar)

    def tearDown(self):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def test_every_row_has_a_name(self):
        menu = self.win.createPopupMenu()
        self.addCleanup(menu.deleteLater)
        rows = [a for a in menu.actions() if not a.isSeparator()]
        self.assertTrue(rows)
        blank = [a for a in rows if not a.text().strip()]
        self.assertEqual([], blank)

    def test_each_toolbar_is_listed_and_toggled(self):
        self.assertEqual(4, len(self.toolbars))
        menu = self.win.createPopupMenu()
        self.addCleanup(menu.deleteLater)
        rows = menu.actions()
        names = set()
        for toolbar in self.toolbars:
            # saveState and restoreState find a toolbar by its object name
            self.assertTrue(toolbar.objectName())
            toggle = toolbar.toggleViewAction()
            self.assertIn(toggle, rows)
            self.assertTrue(toggle.text())
            self.assertEqual(toolbar.windowTitle(), toggle.text())
            names.add(toggle.text())
            self.assertTrue(toolbar.isVisible())
            toggle.trigger()
            app.processEvents()
            self.assertFalse(toolbar.isVisible())
            toggle.trigger()
            app.processEvents()
            self.assertTrue(toolbar.isVisible())
        self.assertEqual(len(self.toolbars), len(names))

    def test_saved_layout_names_are_kept(self):
        names = {t.objectName() for t in self.toolbars}
        self.assertEqual({'Node Authoring', 'Execute Tools', 'Display Tools',
                          'Alignment Tools'}, names)


if __name__ == '__main__':
    unittest.main()
