"""Ctrl+click a ${} token to go to its node, hover it to see its value.

Only tokens that read an attribute take part. A file::, contents:: or
plugin token is resolved by reading files or running plugin code, which
hovering must not set off, and none of them names a node to go to.
"""
# Builtin
import json
import logging
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

# External
from Qt import QtCore, QtGui, QtWidgets

# Internal
from nxt import DATA_STATE, nxt_path

logging.getLogger(nxt_path.__name__).propagate = False

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

CODE = [
    "a = ${/source.value}",
    "b = ${local}",
    "c = ${file::missing.txt}",
    "d = ${/nowhere.value}",
]


def write_graph(path):
    data = {
        "version": "1.17", "alias": "tokens", "mute": False, "solo": False,
        "meta_data": {"positions": {"/source": [0.0, 0.0],
                                    "/reader": [300.0, 0.0]}},
        "nodes": {
            "/source": {"attrs": {"value": {"value": "42"}}},
            "/reader": {"attrs": {"local": {"value": "7"}},
                        "code": CODE},
        },
    }
    with open(path, 'w') as file_object:
        json.dump(data, file_object, indent=4)


class TokenNavigation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='nxt_token_nav_')
        cls.graph = os.path.join(cls.tmp, 'tokens.nxt')
        write_graph(cls.graph)
        cls.win = MainWindow(filepath=cls.graph)
        cls.win.resize(1400, 900)
        cls.win.show()
        cls.model = cls.win.model
        cls.ce = cls.win.code_editor
        cls.editor = cls.ce.editor
        cls.model.data_state = DATA_STATE.RAW
        cls.model.set_selection(['/reader'])
        cls.win.resizeDocks([cls.ce], [420], QtCore.Qt.Vertical)
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.ce.editing_active = False
        self.model.set_selection(['/reader'])
        app.processEvents()
        self.assertIn('${/source.value}', self.editor.toPlainText(),
                      'the raw code should be on show')

    def point_at(self, text, offset):
        """Viewport position of a character of `text` in the editor."""
        start = self.editor.toPlainText().index(text) + offset
        cursor = self.editor.textCursor()
        cursor.setPosition(start)
        left = self.editor.cursorRect(cursor)
        cursor.setPosition(start + 1)
        right = self.editor.cursorRect(cursor)
        return QtCore.QPoint((left.left() + right.left()) // 2,
                             left.center().y())

    def hover(self, point):
        """The tooltip text a hover at `point` asks for, or ''.

        Read from the request rather than from QToolTip, which hides on a
        timer and so can still be showing the previous hover's text.
        """
        viewport = self.editor.viewport()
        event = QtGui.QHelpEvent(QtCore.QEvent.ToolTip, point,
                                 viewport.mapToGlobal(point))
        with mock.patch.object(QtWidgets.QToolTip, 'showText') as show:
            QtWidgets.QApplication.sendEvent(viewport, event)
            app.processEvents()
        if not show.called:
            return ''
        return show.call_args[0][1]

    def ctrl_click(self, point):
        viewport = self.editor.viewport()
        event = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress,
                                  QtCore.QPointF(point),
                                  QtCore.QPointF(viewport.mapToGlobal(point)),
                                  QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
                                  QtCore.Qt.ControlModifier)
        QtWidgets.QApplication.sendEvent(viewport, event)
        app.processEvents()

    def test_hovering_a_token_shows_its_value(self):
        tip = self.hover(self.point_at('${/source.value}', 3))
        self.assertIn('42', tip)

    def test_the_tooltip_starts_and_ends_with_the_token(self):
        # The gutter offsets the text, so a position read in the wrong
        # coordinates lands a few characters off.
        token = '${/source.value}'
        self.assertFalse(self.hover(self.point_at('= ' + token, 0)),
                         'the "=" before the token is not the token')
        self.assertIn('42', self.hover(self.point_at(token, 0)))
        self.assertIn('42', self.hover(self.point_at(token, len(token) - 1)))

    def test_a_local_token_shows_its_value(self):
        self.assertIn('7', self.hover(self.point_at('${local}', 3)))

    def test_a_missing_node_says_so_without_resolving(self):
        with mock.patch.object(self.model, 'resolve') as resolve:
            tip = self.hover(self.point_at('${/nowhere.value}', 3))
        self.assertIn('no node', tip)
        resolve.assert_not_called()

    def test_a_file_token_is_never_resolved_by_hovering(self):
        with mock.patch.object(self.model, 'resolve') as resolve:
            tip = self.hover(self.point_at('${file::missing.txt}', 3))
        self.assertFalse(tip)
        resolve.assert_not_called()

    def test_ctrl_click_goes_to_the_node(self):
        self.ctrl_click(self.point_at('${/source.value}', 3))
        self.assertEqual(['/source'], self.model.selection)

    def test_ctrl_click_on_a_local_token_stays(self):
        self.ctrl_click(self.point_at('${local}', 3))
        self.assertEqual(['/reader'], self.model.selection)

    def test_ctrl_click_while_editing_does_not_leave(self):
        # Going to another node would accept the edit on the way out.
        self.ce.editing_active = True
        try:
            self.ctrl_click(self.point_at('${/source.value}', 3))
            self.assertEqual(['/reader'], self.model.selection)
        finally:
            self.ce.editing_active = False


if __name__ == '__main__':
    unittest.main()
