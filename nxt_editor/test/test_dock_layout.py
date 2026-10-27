"""Double clicking a dock's tab floats it, and View > Reset Layout puts every
dock back where, and as big as, it started.
"""
# Builtin
import sys
import unittest

# External
from Qt import QtCore, QtGui, QtWidgets

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402


def pump(times=10):
    for _ in range(times):
        app.processEvents()


class DockLayout(unittest.TestCase):

    def setUp(self):
        self.win = MainWindow()
        self.win.show()
        pump()
        # Whatever layout the person running the tests last left is restored
        # on show; start from the factory one.
        self.win.reset_layout()
        pump()
        self.default_sizes = self.sizes()

    def tearDown(self):
        self.win.hide()
        pump()

    def sizes(self):
        return {'property': self.win.property_editor.height(),
                'code': self.win.code_editor.height()}

    def test_reset_layout_brings_a_floated_dock_back(self):
        code_editor = self.win.code_editor
        code_editor.setFloating(True)
        code_editor.move(50, 50)
        pump()
        self.win.reset_layout()
        pump()
        self.assertFalse(code_editor.isFloating())
        self.assertEqual(QtCore.Qt.RightDockWidgetArea,
                         self.win.dockWidgetArea(code_editor))

    def test_reset_layout_keeps_the_default_sizes(self):
        # Taken before the docks were sized, the default squashed the code
        # editor to a sliver.
        self.win.resizeDocks([self.win.code_editor], [60],
                             QtCore.Qt.Vertical)
        pump()
        self.win.reset_layout()
        pump()
        for name, height in self.sizes().items():
            self.assertAlmostEqual(self.default_sizes[name], height,
                                   delta=6, msg=name)
        self.assertGreater(self.win.code_editor.height(), 150)

    def test_double_clicking_a_tab_floats_its_dock(self):
        self.win.tabifyDockWidget(self.win.property_editor,
                                  self.win.code_editor)
        pump()
        self.win.scan_dock_tab_bars()
        title = self.win.code_editor.windowTitle()
        for tab_bar in self.win.findChildren(QtWidgets.QTabBar):
            if tab_bar.parent() is not self.win:
                continue
            for index in range(tab_bar.count()):
                if tab_bar.tabText(index) == title:
                    break
            else:
                continue
            point = tab_bar.tabRect(index).center()
            event = QtGui.QMouseEvent(
                QtCore.QEvent.MouseButtonDblClick, QtCore.QPointF(point),
                QtCore.QPointF(tab_bar.mapToGlobal(point)),
                QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
                QtCore.Qt.NoModifier)
            QtWidgets.QApplication.sendEvent(tab_bar, event)
            pump()
            break
        else:
            self.fail('no tab for the code editor once it was tabified')
        self.assertTrue(self.win.code_editor.isFloating())

    def test_reset_layout_is_in_the_view_menu(self):
        actions = [action.text() for action
                   in self.win.menu_bar.view_menu.actions()]
        self.assertIn('Reset Layout', actions)


if __name__ == '__main__':
    unittest.main()
