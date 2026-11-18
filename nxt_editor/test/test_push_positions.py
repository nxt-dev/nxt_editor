"""Push Positions to Target Layer writes where the selected nodes are shown
onto the target layer, as one undo."""
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

# Internal
from nxt_editor import stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

BASE = {
    'version': '1.17', 'alias': 'base',
    'nodes': {'/a': {}, '/b': {}, '/a/kid': {}},
    'meta_data': {'positions': {'/a': [0.0, 0.0]}},
}
TOP = {
    'version': '1.17', 'alias': 'top', 'references': ['./base.nxt'],
    'nodes': {},
    'meta_data': {'positions': {'/a': [500.0, 200.0],
                                '/b': [100.0, 600.0]}},
}


class PushPositions(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_push_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        for name, data in (('base.nxt', BASE), ('top.nxt', TOP)):
            with open(os.path.join(self.tmp, name), 'w') as fp:
                json.dump(data, fp)
        self.win = MainWindow(filepath=os.path.join(self.tmp, 'top.nxt'))
        self.win.show()
        app.processEvents()
        self.view = self.win.view
        self.model = self.view.model
        self.view.ensure_drawn()
        self.base = self.model.stage._sub_layers[1]
        self.top = self.model.top_layer
        app.processEvents()

    def tearDown(self):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def target_base(self):
        self.model.set_target_layer(self.model.get_layer_path(self.base))
        app.processEvents()

    def push_action(self, menu):
        return [a for a in menu.actions()
                if a.text() == 'Push Positions to Target Layer'][0]

    def test_it_writes_the_shown_positions_to_the_target_in_one_undo(self):
        self.target_base()
        self.model.set_selection(['/a', '/b', '/a/kid'])
        before = self.model.undo_stack.count()
        self.push_action(self.view.node_menu('/a')).trigger()
        app.processEvents()
        self.assertEqual(before + 1, self.model.undo_stack.count())
        self.assertEqual([500.0, 200.0], self.base.positions['/a'])
        self.assertEqual([100.0, 600.0], self.base.positions['/b'])
        # Children are stacked under their root and have no place.
        self.assertNotIn('/a/kid', self.base.positions)
        self.assertIn(self.base.real_path, self.model.effected_layers)
        # Nothing moves.
        self.assertEqual([500.0, 200.0], self.model.get_node_pos('/a'))
        self.assertEqual([500.0, 200.0], self.top.positions['/a'])

    def test_undo_puts_back_what_the_target_had(self):
        self.target_base()
        self.model.set_selection(['/a', '/b'])
        self.model.push_node_positions()
        self.model.undo_stack.undo()
        app.processEvents()
        self.assertEqual([0.0, 0.0], self.base.positions['/a'])
        self.assertNotIn('/b', self.base.positions)
        self.assertEqual([500.0, 200.0], self.model.get_node_pos('/a'))
        self.model.undo_stack.redo()
        self.assertEqual([100.0, 600.0], self.base.positions['/b'])

    def test_it_is_greyed_out_with_the_top_layer_the_target(self):
        self.model.set_selection(['/a'])
        self.assertFalse(self.push_action(self.view.node_menu('/a'))
                         .isEnabled())
        self.target_base()
        self.assertTrue(self.push_action(self.view.node_menu('/a'))
                        .isEnabled())

    def test_it_survives_saving(self):
        self.target_base()
        self.model.set_selection(['/b'])
        self.model.push_node_positions()
        self.win.save_layer(self.base)
        with open(self.base.real_path) as fp:
            saved = json.load(fp)
        self.assertEqual([100.0, 600.0],
                         saved['meta_data']['positions']['/b'])


if __name__ == '__main__':
    unittest.main()
