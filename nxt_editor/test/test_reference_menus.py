"""The Reference Layer and Create Layer menus store a picked file the way the
Reference Editor does.

Relative to the layer that holds the reference when the file sits beside
it, whole otherwise. The menus used to store whatever the file picker
handed back, which is always absolute, so a graph built through them broke
as soon as its folder moved.
"""
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
from nxt.session import Session
from nxt_editor import stage_model
from nxt_editor.reference_paths import stored_reference_path

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def write_graph(path, alias):
    with open(path, 'w') as file_object:
        json.dump({'version': '1.17', 'alias': alias, 'references': [],
                   'nodes': {'/' + alias: {}}}, file_object)
    return path


class ReferenceMenus(unittest.TestCase):

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix='nxt_ref_menus_')
        self.graph_dir = os.path.join(self.tmp, 'graph')
        self.far_dir = os.path.join(self.tmp, 'far')
        os.makedirs(self.graph_dir)
        os.makedirs(self.far_dir)
        self.top = write_graph(os.path.join(self.graph_dir, 'top.nxt'), 'top')
        self.beside = write_graph(os.path.join(self.graph_dir, 'beside.nxt'),
                                  'beside')
        self.far = write_graph(os.path.join(self.far_dir, 'far.nxt'), 'far')
        self.model = stage_model.StageModel(Session().load_file(self.top))

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stored_references(self):
        return self.model.stage.top_layer.sub_layer_paths

    def test_a_file_beside_the_layer_is_stored_relative(self):
        self.model.reference_layer(self.beside, idx=1, chdir=self.graph_dir)
        self.assertIn('beside.nxt', self.stored_references())

    def test_a_file_elsewhere_is_stored_whole(self):
        self.model.reference_layer(self.far, idx=1, chdir=self.graph_dir)
        stored = self.stored_references()
        self.assertIn(self.far.replace(os.sep, '/'), stored)
        self.assertFalse(any(path.startswith('..') for path in stored))

    def test_the_saved_graph_still_finds_it_after_moving(self):
        self.model.reference_layer(self.beside, idx=1, chdir=self.graph_dir)
        self.model.stage.top_layer.save()
        moved = os.path.join(self.tmp, 'moved')
        shutil.move(self.graph_dir, moved)
        stage = Session().load_file(os.path.join(moved, 'top.nxt'))
        aliases = [layer.get_alias() for layer in stage._sub_layers]
        self.assertIn('beside', aliases)

    def test_undo_takes_the_reference_back_out(self):
        self.model.reference_layer(self.beside, idx=1, chdir=self.graph_dir)
        self.model.undo_stack.undo()
        aliases = [layer.get_alias() for layer in self.model.stage._sub_layers]
        self.assertNotIn('beside', aliases)

    def test_a_created_layer_beside_it_is_stored_relative(self):
        new = os.path.join(self.graph_dir, 'made.nxt')
        self.model.create_layer(new, 'made', idx=1, chdir=self.graph_dir)
        self.assertIn('made.nxt', self.stored_references())

    def test_an_unsaved_layer_keeps_the_whole_path(self):
        # With no folder of its own there is nothing to be relative to.
        self.assertEqual(self.beside.replace(os.sep, '/'),
                         stored_reference_path(self.beside, None))


if __name__ == '__main__':
    unittest.main()
