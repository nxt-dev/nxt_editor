"""Shift clicking a layer's arrow in the Layer Manager opens or closes
every layer under it too."""
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

# Internal
from nxt.session import Session
from nxt_editor import stage_model
from nxt_editor.dockwidgets.layer_manager import LayerModel, LayerTreeView

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def write_graph(path, name, references=()):
    data = {'version': '1.17', 'alias': name, 'references': list(references),
            'meta_data': {}, 'nodes': {}}
    with open(path, 'w') as fp:
        json.dump(data, fp)
    return path


class ShiftClickArrow(unittest.TestCase):

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix='nxt_lay_expand_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(os.chdir, self.cwd)
        # top > mid > (low > deep, side)
        write_graph(os.path.join(self.tmp, 'deep.nxt'), 'deep')
        write_graph(os.path.join(self.tmp, 'side.nxt'), 'side')
        write_graph(os.path.join(self.tmp, 'low.nxt'), 'low', ['deep.nxt'])
        write_graph(os.path.join(self.tmp, 'mid.nxt'), 'mid',
                    ['low.nxt', 'side.nxt'])
        top = write_graph(os.path.join(self.tmp, 'top.nxt'), 'top',
                          ['mid.nxt'])
        self.stage = Session().load_file(filepath=top)
        self.model = stage_model.StageModel(self.stage)
        self.tree = LayerTreeView(mock.MagicMock())
        self.tree.setModel(LayerModel(self.model))
        self.tree.resize(400, 400)
        self.tree.show()
        app.processEvents()

    def tearDown(self):
        self.tree.hide()
        app.processEvents()

    def index(self, alias):
        model = self.tree.model()
        stack = [model.index(r, 0) for r in range(model.rowCount())]
        while stack:
            index = stack.pop()
            if index.internalPointer().get_alias() == alias:
                return index
            stack += [model.index(r, 0, index)
                      for r in range(model.rowCount(index))]
        raise LookupError(alias)

    def click_arrow(self, alias, modifiers, double=False):
        index = self.index(alias)
        rect = self.tree.visualRect(index)
        pos = QtCore.QPointF(rect.left() - self.tree.indentation() / 2.0,
                             rect.center().y())
        kind = (QtCore.QEvent.MouseButtonDblClick if double else
                QtCore.QEvent.MouseButtonPress)
        event = QtGui.QMouseEvent(kind, pos,
                                  self.tree.viewport().mapToGlobal(pos),
                                  QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
                                  modifiers)
        if double:
            self.tree.mouseDoubleClickEvent(event)
        else:
            self.tree.mousePressEvent(event)
        release = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonRelease, pos,
                                    self.tree.viewport().mapToGlobal(pos),
                                    QtCore.Qt.LeftButton,
                                    QtCore.Qt.NoButton, modifiers)
        self.tree.mouseReleaseEvent(release)
        app.processEvents()

    def expanded(self, *aliases):
        return [self.tree.isExpanded(self.index(a)) for a in aliases]

    def test_everything_starts_open(self):
        self.assertEqual([True, True, True], self.expanded('top', 'mid',
                                                           'low'))

    def test_shift_click_closes_everything_below(self):
        self.click_arrow('mid', QtCore.Qt.ShiftModifier)
        self.assertEqual([True, False, False], self.expanded('top', 'mid',
                                                             'low'))

    def test_shift_click_again_opens_everything_below(self):
        self.tree.collapse(self.index('low'))
        self.tree.collapse(self.index('mid'))
        self.click_arrow('mid', QtCore.Qt.ShiftModifier)
        self.assertEqual([True, True], self.expanded('mid', 'low'))

    def test_a_plain_click_only_closes_that_layer(self):
        self.click_arrow('mid', QtCore.Qt.NoModifier)
        self.assertEqual([False, True], self.expanded('mid', 'low'))

    def test_a_shift_double_click_does_it_once_more(self):
        self.click_arrow('mid', QtCore.Qt.ShiftModifier)
        self.click_arrow('mid', QtCore.Qt.ShiftModifier, double=True)
        self.assertEqual([True, True], self.expanded('mid', 'low'))


if __name__ == '__main__':
    unittest.main()
