"""Submenus look like the menu they open from.

A menu made with no parent is not reached by the editor's style sheet,
so inside a host such as Maya Open Recent and Reference Builtin Graph
were drawn as the host's menus, beside a File menu drawn as the editor's.
Every menu in the menu bar belongs to the editor's window.
"""
# Builtin
import sys
import unittest
from unittest import mock

# External
from Qt import QtWidgets

# Internal
from nxt_editor import stage_model
from nxt_editor.dockwidgets.output_log import LogFilterButton

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402


class SubmenuStyle(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.win = MainWindow()
        cls.win.show()
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            cls.win.close()
            app.processEvents()

    def window_menu_titles(self):
        """The titles of the menus the style sheet reaches: those that
        are the window's, however deep."""
        return set(menu.title()
                   for menu in self.win.findChildren(QtWidgets.QMenu))

    def test_open_recent_and_builtins_belong_to_the_window(self):
        menu_bar = self.win.menuBar()
        titles = self.window_menu_titles()
        for menu in (menu_bar.load_recent_menu, menu_bar.builtins_menu):
            self.assertIsNotNone(menu.parentWidget(), menu.title())
            self.assertIn(menu.title(), titles)

    def test_the_log_filter_menu_belongs_to_its_button(self):
        button = self.win.findChild(LogFilterButton)
        self.assertIsNotNone(button)
        self.assertIsNotNone(button.menu.parentWidget())
        self.assertIn(button.menu, button.findChildren(QtWidgets.QMenu))


if __name__ == '__main__':
    unittest.main()
