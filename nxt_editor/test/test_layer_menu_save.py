"""Ctrl+S saves the graph being looked at, never a layer right clicked
earlier in the Layer Manager.

Right clicking a layer hands it to the shared layer actions as their data.
A menu closed without picking anything left it there, and Ctrl+S in a new,
unsaved tab then saved over that layer's file instead of asking where to
save the new graph.
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
from Qt import QtWidgets

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor import main_window  # noqa: E402
from nxt_editor.main_window import MainWindow  # noqa: E402


def write_graph(path, alias):
    with open(path, 'w') as file_object:
        json.dump({'version': '1.17', 'alias': alias, 'references': [],
                   'nodes': {'/' + alias: {}}}, file_object)
    return path


class LayerMenuSave(unittest.TestCase):

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='nxt_menu_save_'))
        self.graph = write_graph(os.path.join(self.tmp, 'graph.nxt'), 'graph')
        self.new_path = os.path.join(self.tmp, 'new.nxt')
        self.win = MainWindow(filepath=self.graph)
        self.win.show()
        app.processEvents()
        self.tree = self.win.layer_manager.layer_tree
        self.graph_layer = self.win.model.top_layer

    def tearDown(self):
        self.win.hide()
        app.processEvents()
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def open_menu(self):
        """Right click the graph's layer and return the menu it shows."""
        index = self.tree.model().index(0, 0)
        self.assertIs(self.graph_layer, index.internalPointer())
        before = set(self.tree.findChildren(QtWidgets.QMenu))
        self.tree.custom_context_menu(self.tree.visualRect(index).center())
        menus = set(self.tree.findChildren(QtWidgets.QMenu)) - before
        menus = [m for m in menus if m.parent() is self.tree]
        self.assertEqual(1, len(menus))
        return menus[0]

    def test_ctrl_s_in_a_new_tab_after_a_dismissed_menu(self):
        menu = self.open_menu()
        menu.hide()
        app.processEvents()
        self.win.new_tab()
        app.processEvents()
        new_layer = self.win.model.top_layer
        self.assertIsNot(new_layer, self.graph_layer)
        save = self.win.layer_actions.save_layer_action
        with mock.patch.object(main_window.NxtFileDialog,
                               'system_file_dialog',
                               return_value=self.new_path) as dialog, \
                mock.patch.object(self.win.nxt, 'save_layer') as save_layer:
            save.trigger()
        # The new graph has no file, so it asks where to put it.
        dialog.assert_called_once()
        saved = [call.args[0] for call in save_layer.call_args_list]
        self.assertEqual([new_layer], saved)

    def test_no_layer_data_outlives_the_menu(self):
        menu = self.open_menu()
        menu.hide()
        app.processEvents()
        for action in self.win.layer_actions.actions():
            self.assertIsNone(action.data(), action.text())

    def test_picking_save_from_the_menu_saves_that_layer(self):
        menu = self.open_menu()
        save = self.win.layer_actions.save_layer_action
        with mock.patch.object(self.win, 'save_layer') as save_layer:
            # What a menu does with a pick: hide, then trigger, at once.
            menu.hide()
            save.trigger()
            app.processEvents()
        save_layer.assert_called_once_with(self.graph_layer)

    def test_a_layer_from_another_tab_is_not_saved(self):
        self.win.new_tab()
        app.processEvents()
        new_layer = self.win.model.top_layer
        with mock.patch.object(main_window.NxtFileDialog,
                               'system_file_dialog',
                               return_value=self.new_path), \
                mock.patch.object(self.win.nxt, 'save_layer') as save_layer:
            self.win.save_layer(self.graph_layer)
        saved = [call.args[0] for call in save_layer.call_args_list]
        self.assertEqual([new_layer], saved)


if __name__ == '__main__':
    unittest.main()
