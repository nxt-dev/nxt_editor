"""The plus after the open graphs' tabs makes a new graph.

It runs File > New Graph, so it does what Ctrl+N does. It sits just after
the last tab and follows the tabs as they are opened, closed, moved and
renamed. When the tabs and the button no longer fit, the button keeps to
the end of the bar and the tabs scroll to its left. With no graph open,
the empty space offers New Graph and Open. Double clicking the bar after
the tabs makes a new graph too.
"""
# Builtin
import sys
import unittest

# External
from Qt import QtCore, QtGui, QtWidgets
from Qt.QtTest import QTest

# Internal
from nxt_editor import user_dir

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402


def settle():
    for _ in range(5):
        app.processEvents()


def find_button(tab_widget):
    """The new graph button, found by what it says it is."""
    for button in tab_widget.findChildren(QtWidgets.QToolButton):
        if button.accessibleName() == 'New Graph':
            return button
    return None


def find_link(tab_widget, text):
    """A link in the empty space, which is not the button."""
    for widget in tab_widget.findChildren(QtWidgets.QWidget):
        if isinstance(widget, QtWidgets.QAbstractButton):
            continue
        if widget.accessibleName() == text and widget.isVisible():
            return widget
    return None


class NewTabButton(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.win = MainWindow()
        cls.win.resize(1400, 800)
        cls.win.show()
        settle()
        cls.tabs = cls.win.open_files_tab_widget
        cls.action = cls.win.app_actions.new_graph_action

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None

    def setUp(self):
        self.set_count(1)
        self.win.resize(1400, 800)
        settle()
        self.button = find_button(self.tabs)
        self.assertIsNotNone(self.button, 'There is no new graph button.')

    def set_count(self, count):
        while self.tabs.count() > count:
            self.tabs.close_tab(self.tabs.count() - 1)
        while self.tabs.count() < count:
            self.win.new_tab()
        settle()

    def last_tab_right(self):
        """The right edge of the last tab, in the tab widget."""
        bar = self.tabs.tabBar()
        rect = bar.tabRect(bar.count() - 1)
        return bar.mapTo(self.tabs, rect.topRight()).x() + 1

    def assert_after_last_tab(self):
        expected = self.last_tab_right() + 4
        self.assertTrue(self.button.isVisible())
        self.assertLessEqual(abs(self.button.x() - expected), 2,
                             (self.button.x(), expected))

    def test_it_cannot_take_focus(self):
        self.assertEqual(self.button.focusPolicy(), QtCore.Qt.NoFocus)
        self.assertEqual(self.button.size(), QtCore.QSize(22, 22))

    def test_clicking_it_makes_a_current_tab(self):
        QTest.mouseClick(self.button, QtCore.Qt.LeftButton)
        settle()
        self.assertEqual(self.tabs.count(), 2)
        self.assertEqual(self.tabs.currentIndex(), 1)
        view = self.tabs.currentWidget()
        self.assertIs(view, self.win.view)
        self.win.activateWindow()
        settle()
        self.assertIs(app.focusWidget(), view)

    def test_a_middle_click_does_nothing(self):
        QTest.mouseClick(self.button, QtCore.Qt.MiddleButton)
        settle()
        self.assertEqual(self.tabs.count(), 1)
        QTest.mouseClick(self.button, QtCore.Qt.LeftButton)
        settle()
        self.assertEqual(self.tabs.count(), 2)

    def tooltip(self):
        event = QtGui.QHelpEvent(QtCore.QEvent.ToolTip,
                                 QtCore.QPoint(5, 5),
                                 self.button.mapToGlobal(QtCore.QPoint(5, 5)))
        app.sendEvent(self.button, event)
        QtWidgets.QToolTip.hideText()
        return self.button.toolTip()

    def test_the_tooltip_has_the_current_shortcut(self):
        original = self.action.shortcut()
        try:
            self.action.setShortcut('Ctrl+Alt+G')
            keys = QtGui.QKeySequence('Ctrl+Alt+G').toString(
                QtGui.QKeySequence.NativeText)
            self.assertEqual(self.tooltip(), 'New Graph ({})'.format(keys))
            self.action.setShortcut(QtGui.QKeySequence())
            self.assertEqual(self.tooltip(), 'New Graph')
        finally:
            self.action.setShortcut(original)

    def test_it_sits_after_the_last_tab(self):
        self.assert_after_last_tab()
        self.set_count(3)
        self.assert_after_last_tab()
        bar = self.tabs.tabBar()
        # Centered on the bar, a pixel low with the tabs that are not
        # current.
        middle = bar.mapTo(self.tabs, bar.rect().center()).y()
        center = self.button.geometry().center().y()
        self.assertLessEqual(abs(center - (middle + 1)), 1)

    def test_it_follows_closing_moving_and_renaming(self):
        self.set_count(3)
        bar = self.tabs.tabBar()
        bar.setTabText(0, 'a graph with a much longer name')
        settle()
        self.assert_after_last_tab()
        bar.moveTab(0, 2)
        settle()
        self.assert_after_last_tab()
        before = self.button.x()
        self.tabs.close_tab(2)
        settle()
        self.assertLess(self.button.x(), before - 50)
        self.assert_after_last_tab()

    def test_it_stays_in_the_bar_when_the_tabs_do_not_fit(self):
        self.set_count(14)
        tabs_rect = self.tabs.rect()
        self.assertTrue(self.button.isVisible())
        self.assertTrue(tabs_rect.contains(self.button.geometry()))
        bar = self.tabs.tabBar()
        bar_rect = bar.geometry()
        # Pinned to the end, with the bar and its arrows to the left.
        self.assertLessEqual(bar_rect.right(), self.button.x())
        past_button = self.tabs.width() - self.button.geometry().right()
        self.assertLessEqual(past_button, 8)
        for index in range(bar.count()):
            rect = bar.tabRect(index).intersected(bar.rect())
            if rect.isEmpty():
                continue
            rect = QtCore.QRect(bar.mapTo(self.tabs, rect.topLeft()),
                                rect.size())
            self.assertFalse(rect.intersects(self.button.geometry()))
        # Room again: back after the last tab.
        self.set_count(2)
        self.assert_after_last_tab()

    def test_it_follows_the_window_size(self):
        self.set_count(6)
        self.assert_after_last_tab()
        self.win.resize(500, 800)
        settle()
        self.assertTrue(self.tabs.rect().contains(self.button.geometry()))
        self.win.resize(1400, 800)
        settle()
        self.assert_after_last_tab()

    def test_double_clicking_after_the_tabs_makes_a_graph(self):
        bar = self.tabs.tabBar()
        on_tab = bar.tabRect(0).center()
        QTest.mouseDClick(bar, QtCore.Qt.LeftButton, pos=on_tab)
        settle()
        self.assertEqual(self.tabs.count(), 1)
        empty = QtCore.QPoint(self.button.geometry().right() + 40,
                              self.button.geometry().center().y())
        QTest.mouseDClick(self.tabs, QtCore.Qt.LeftButton, pos=empty)
        settle()
        self.assertEqual(self.tabs.count(), 2)
        self.assertEqual(self.tabs.currentIndex(), 1)

    def test_with_no_graphs_the_space_offers_new_and_open(self):
        self.set_count(0)
        self.assertTrue(self.button.isVisible())
        bar = self.tabs.tabBar()
        self.assertLessEqual(self.button.x() - bar.x(), 6)
        self.assertGreater(bar.height(), self.button.height())
        new_link = find_link(self.tabs, 'New Graph')
        open_link = find_link(self.tabs, 'Open...')
        self.assertIsNotNone(new_link)
        self.assertIsNotNone(open_link)
        # In the middle of the empty space.
        center = new_link.mapTo(self.tabs, new_link.rect().center())
        self.assertLessEqual(abs(center.x() - self.tabs.width() // 2), 2)
        open_action = self.win.app_actions.open_file_action
        opened = []
        open_action.triggered.disconnect(self.win.load_file)
        open_action.triggered.connect(lambda *_: opened.append(True))
        try:
            QTest.mouseClick(open_link, QtCore.Qt.LeftButton)
        finally:
            open_action.triggered.disconnect()
            open_action.triggered.connect(self.win.load_file)
        self.assertEqual(opened, [True])
        QTest.mouseClick(new_link, QtCore.Qt.LeftButton)
        settle()
        self.assertEqual(self.tabs.count(), 1)
        self.assertFalse(new_link.isVisible())


class HiddenWithTheGraph(unittest.TestCase):
    """A window of its own: with the graph hidden the docks take its room,
    and it comes back narrower."""

    def test_it_hides_with_the_graph(self):
        win = MainWindow()
        win.show()
        settle()
        button = find_button(win.open_files_tab_widget)
        key = user_dir.USER_PREF.SHOW_STAGE_VIEW
        saved = user_dir.user_prefs.get(key)
        try:
            self.assertTrue(button.isVisible())
            win.set_stage_view_visible(False)
            settle()
            self.assertFalse(button.isVisible())
            win.set_stage_view_visible(True)
            settle()
            self.assertTrue(button.isVisible())
        finally:
            if saved is None:
                try:
                    user_dir.user_prefs.pop(key)
                except KeyError:
                    pass
            else:
                user_dir.user_prefs[key] = saved
            win.close()


if __name__ == '__main__':
    unittest.main()
