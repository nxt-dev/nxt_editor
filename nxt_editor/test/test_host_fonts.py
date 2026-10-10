"""The editor's fonts stay in the editor.

Inside a host such as Maya the editor shares the host's QApplication, so
anything set on the application lands on every widget the host has. The
editor's font and font size are set on its own widgets only (#284, #304).
"""
# Builtin
import sys
import unittest

# External
from Qt import QtGui, QtWidgets

# Internal
import nxt_editor
from nxt_editor import user_dir
from nxt_editor.constants import FONTS

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402


class HostFonts(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.saved_size = user_dir.user_prefs.get(user_dir.USER_PREF.FONT_SIZE)
        # Stands in for the host's own UI, there before the editor opens.
        cls.host = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(cls.host)
        cls.host_label = QtWidgets.QLabel('host', cls.host)
        cls.host_check = QtWidgets.QCheckBox('host', cls.host)
        layout.addWidget(cls.host_label)
        layout.addWidget(cls.host_check)
        cls.app_font = QtGui.QFont(app.font())
        cls.label_font = QtGui.QFont(cls.host_label.font())
        cls.win = MainWindow()
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None
        cls.host.deleteLater()
        cls.host = None
        key = user_dir.USER_PREF.FONT_SIZE
        if cls.saved_size is None:
            try:
                user_dir.user_prefs.pop(key)
            except KeyError:
                pass
        else:
            user_dir.user_prefs[key] = cls.saved_size

    def tearDown(self):
        self.win._change_font_size(10, absolute=True, save=False)

    def assert_host_untouched(self):
        self.assertEqual(self.app_font, app.font())
        self.assertEqual(self.label_font, self.host_label.font())
        new_label = QtWidgets.QLabel('opened later')
        self.assertEqual(self.app_font.family(), new_label.font().family())
        self.assertEqual('', self.host_check.styleSheet())

    def test_opening_the_editor_leaves_the_host_alone(self):
        self.assert_host_untouched()

    def test_changing_the_font_size_leaves_the_host_alone(self):
        self.win._change_font_size(4, save=False)
        app.processEvents()
        self.assert_host_untouched()

    def test_changing_the_font_size_changes_the_editor(self):
        before = self.win.font().pointSize()
        self.win._change_font_size(2, save=False)
        self.assertEqual(before + 2, self.win.font().pointSize())
        self.assertEqual(before + 2, self.win.menu_bar.font().pointSize())
        # A menu is a window of its own and does not inherit the editor's
        # font, so it is given it, and kept in step.
        view_menu = self.win.menu_bar.view_menu
        self.assertEqual(before + 2, view_menu.font().pointSize())
        self.win._change_font_size(1, save=False)
        self.assertEqual(before + 3, view_menu.font().pointSize())

    def test_a_widget_with_its_own_font_keeps_it(self):
        label = QtWidgets.QLabel('small', self.win)
        label.setFont(QtGui.QFont('Courier', 7))
        self.win._change_font_size(3, save=False)
        self.assertEqual(7, label.font().pointSize())
        label.deleteLater()


class OwnAppFonts(unittest.TestCase):
    """Standalone, the application is nxt's own and gets nxt's font."""

    def setUp(self):
        self.saved_font = QtGui.QFont(app.font())
        self.saved_size = user_dir.user_prefs.get(user_dir.USER_PREF.FONT_SIZE)
        app.setProperty(nxt_editor.OWN_APP_PROPERTY, True)
        self.win = MainWindow()

    def tearDown(self):
        self.win.close()
        self.win = None
        app.setProperty(nxt_editor.OWN_APP_PROPERTY, False)
        app.setFont(self.saved_font)
        key = user_dir.USER_PREF.FONT_SIZE
        if self.saved_size is None:
            try:
                user_dir.user_prefs.pop(key)
            except KeyError:
                pass
        else:
            user_dir.user_prefs[key] = self.saved_size

    def test_the_application_gets_nxts_font(self):
        self.win._change_font_size(12, absolute=True, save=False)
        self.assertEqual(FONTS.DEFAULT_FAMILY, app.font().family())
        self.assertEqual(12, app.font().pointSize())


if __name__ == '__main__':
    unittest.main()
