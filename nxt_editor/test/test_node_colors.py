"""A node is colored by every layer with an opinion on it.

A layer was found again from its path to color its stripe, but a new layer
has no file yet, so its path is None. That found the target layer instead,
which did not have the node, and drawing it failed with
'NoneType' object has no attribute '_source_layer'.
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
from nxt import nxt_layer
from nxt_editor import stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402


class NewLayers(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_node_colors_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.win = MainWindow()
        # A hidden graph is drawn when it is shown, not as it is edited.
        self.win.show()
        self.win.new_tab()
        app.processEvents()
        self.model = self.win.model

    def tearDown(self):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def new_layer(self, name, idx):
        path = os.path.join(self.tmp, name + '.nxt')
        self.model.create_layer(path, name, idx=idx, chdir=self.tmp)
        app.processEvents()

    def test_a_node_on_an_unsaved_layer_under_new_ones_is_drawn(self):
        untitled = self.model.top_layer
        self.assertIsNone(untitled.real_path)
        self.model.add_node(name='one', pos=(0, 0), layer=untitled)
        app.processEvents()
        self.new_layer('first', 0)
        below = self.model.target_layer.layer_idx() + \
            nxt_layer.AUTHORING.BELOW
        self.new_layer('second', below)
        for layer in list(self.model.stage._sub_layers):
            self.model.add_node(name='two', pos=(100, 100), layer=layer)
            app.processEvents()
        graphic = self.win.view.get_node_graphic('/one')
        self.assertIsNotNone(graphic)
        self.assertEqual(self.model.get_layer_color(untitled),
                         graphic.colors[-1].name())

    def test_layers_with_an_opinion_can_be_had_as_layers(self):
        layer = self.model.top_layer
        self.model.add_node(name='one', pos=(0, 0), layer=layer)
        self.assertEqual([layer], self.model.get_layers_with_opinion(
            '/one', as_layers=True))


if __name__ == '__main__':
    unittest.main()
