"""Copying the world node copies its attributes and code, and pasting it
merges them into the target layer's world node, as one undo."""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import unittest

# External
from Qt import QtWidgets

# Internal
from nxt import DATA_STATE, nxt_path
from nxt.session import Session
from nxt_editor import stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

SOURCE = {
    'version': '1.17', 'alias': 'source',
    'nodes': {
        '/': {'attrs': {'speed': {'type': 'raw', 'value': '5'},
                        'note': {'value': 'hello', 'comment': 'a note'}},
              'code': ['import os', 'w.ready = True']},
        '/node': {}},
}
DEST = {
    'version': '1.17', 'alias': 'dest',
    'nodes': {'/': {'attrs': {'speed': {'value': '1'},
                              'kept': {'value': 'mine'}}},
              '/other': {}},
}
EMPTY = {'version': '1.17', 'alias': 'empty', 'nodes': {'/other': {}}}


class WorldCopyPaste(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_world_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.source = self.load(SOURCE)

    def load(self, data):
        path = os.path.join(self.tmp, data['alias'] + '.nxt')
        with open(path, 'w') as fp:
            json.dump(data, fp)
        return stage_model.StageModel(Session().load_file(path))

    def raw(self, model, attr):
        return model.get_node_attr_value(nxt_path.WORLD, attr,
                                         model.comp_layer,
                                         data_state=DATA_STATE.RAW)

    def copy_world(self):
        self.source.set_selection([nxt_path.WORLD])
        self.source.copy_nodes()

    def test_pasting_merges_into_the_world_node_in_one_undo(self):
        self.copy_world()
        dest = self.load(DEST)
        before = dest.undo_stack.count()
        pasted = dest.paste_nodes(layer=dest.target_layer)
        self.assertEqual([nxt_path.WORLD], pasted)
        self.assertEqual(before + 1, dest.undo_stack.count())
        self.assertEqual('5', self.raw(dest, 'speed'))
        self.assertEqual('hello', self.raw(dest, 'note'))
        self.assertEqual('a note', dest.get_node_attr_comment(
            nxt_path.WORLD, 'note', dest.target_layer))
        # Its own attributes stay.
        self.assertEqual('mine', self.raw(dest, 'kept'))
        self.assertEqual('import os\nw.ready = True',
                         dest.get_node_code_string(nxt_path.WORLD))
        # No node called something like "_pasted" was made.
        self.assertEqual(['/other'], dest.get_descendants(nxt_path.WORLD))

    def test_undo_puts_the_world_node_back(self):
        self.copy_world()
        dest = self.load(DEST)
        dest.paste_nodes(layer=dest.target_layer)
        dest.undo_stack.undo()
        self.assertEqual('1', self.raw(dest, 'speed'))
        self.assertNotIn('note', dest.get_node_attr_names(
            nxt_path.WORLD, dest.target_layer))
        self.assertFalse(dest.get_node_code_string(nxt_path.WORLD))

    def test_a_layer_with_no_world_node_is_given_one(self):
        self.copy_world()
        dest = self.load(EMPTY)
        dest.paste_nodes(layer=dest.target_layer)
        self.assertEqual('5', self.raw(dest, 'speed'))
        self.assertIsNotNone(dest.target_layer.lookup(nxt_path.WORLD))

    def test_it_pastes_alongside_other_nodes(self):
        self.source.set_selection([nxt_path.WORLD, '/node'])
        self.source.copy_nodes()
        dest = self.load(DEST)
        before = dest.undo_stack.count()
        pasted = dest.paste_nodes(layer=dest.target_layer)
        self.assertEqual(before + 1, dest.undo_stack.count())
        self.assertEqual([nxt_path.WORLD, '/node_pasted'], pasted)
        self.assertEqual('5', self.raw(dest, 'speed'))

    def test_cutting_the_world_node_copies_it_and_leaves_it(self):
        self.source.set_selection([nxt_path.WORLD])
        self.source.cut_nodes()
        self.assertEqual('5', self.raw(self.source, 'speed'))
        self.assertIn('"speed"', self.source.clipboard.text())


if __name__ == '__main__':
    unittest.main()
