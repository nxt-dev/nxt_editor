"""The layer tree hands out indices that point straight at layer objects.

createIndex takes the object as a bare pointer and keeps nothing alive.
The view holds on to the indices it is given, so once a layer leaves the
stage and its last reference goes, those indices point at freed memory.
The next paint asks the model for the parent of each index, which reads
the layer, and Maya dies in C++ with an access violation rather than
raising anything Python can catch or report:

    QTreeView::paintEvent -> drawTree -> visualRect -> isIndexHidden
      -> LayerModel.parent -> layer.parent_layer -> ACCESS_VIOLATION

A dangling pointer is not falsy, so the `if not layer` guard in parent()
lets it through and the read happens anyway.

None of this can be caught by asking whether the model gives right
answers, which is why it survived tests that did. What is checked here is
the lifetime: while the model may still hand out an index for a layer,
that layer has to be alive.
"""
# Builtin
import gc
import json
import os
import shutil
import sys
import tempfile
import unittest
import weakref

# External
from Qt import QtWidgets

# Internal
from nxt.session import Session
from nxt_editor import stage_model
from nxt_editor.dockwidgets.layer_manager import LayerModel

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def write_graph(path, name, references=(), node_names=()):
    data = {"version": "1.17", "alias": name, "mute": False, "solo": False,
            "references": list(references), "meta_data": {},
            "nodes": {"/" + n: {} for n in node_names}}
    with open(path, 'w') as file_object:
        json.dump(data, file_object, indent=4)
    return path


class IndicesKeepTheirLayersAlive(unittest.TestCase):

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix='nxt_idx_')
        write_graph(os.path.join(self.tmp, 'a.nxt'), 'a',
                    node_names=['from_a'])
        write_graph(os.path.join(self.tmp, 'b.nxt'), 'b',
                    node_names=['from_b'])
        self.top_path = write_graph(os.path.join(self.tmp, 'top.nxt'), 'top',
                                    references=['a.nxt', 'b.nxt'],
                                    node_names=['from_top'])
        self.stage = Session().load_file(filepath=self.top_path)
        self.model = stage_model.StageModel(self.stage)
        self.layer_model = LayerModel(self.model)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sub_layer(self, alias):
        for layer in self.stage._sub_layers:
            if layer.get_alias() == alias:
                return layer
        return None

    def test_a_layer_survives_leaving_the_stage(self):
        layer = self.sub_layer('a')
        reference = weakref.ref(layer)
        index = self.layer_model.get_index_of_layer(layer)
        self.assertTrue(index.isValid())
        # Everything else lets go of it.
        self.stage.remove_sublayer(layer)
        del layer
        gc.collect()
        self.assertIsNotNone(
            reference(),
            'the layer was freed while the model can still hand out an '
            'index pointing at it, so painting the tree reads freed memory')

    def test_the_index_can_still_be_walked_afterwards(self):
        # This is the call that crashes: parent() reads the layer the
        # index points at.
        layer = self.sub_layer('a')
        index = self.layer_model.get_index_of_layer(layer)
        self.stage.remove_sublayer(layer)
        del layer
        gc.collect()
        parent = self.layer_model.parent(index)
        self.assertIsNotNone(parent)

    def test_asking_the_model_for_data_afterwards(self):
        layer = self.sub_layer('a')
        index = self.layer_model.get_index_of_layer(layer)
        self.stage.remove_sublayer(layer)
        del layer
        gc.collect()
        # Whatever it answers, it must not be reading freed memory.
        self.layer_model.data(index, role=0)

    def test_it_lets_go_once_the_view_starts_over(self):
        # Holding them forever would keep every layer ever removed, and
        # their node tables with them. A reset is the point at which the
        # view drops the indices, so it is safe to let go.
        layer = self.sub_layer('a')
        reference = weakref.ref(layer)
        self.layer_model.get_index_of_layer(layer)
        self.stage.remove_sublayer(layer)
        del layer
        self.layer_model.reset()
        gc.collect()
        self.assertIsNone(reference(),
                          'removed layers are being kept after the view was '
                          'told to start over')

    def test_a_layer_still_in_the_stage_is_not_kept_by_this(self):
        # The stage holds it; this should not be what is keeping it.
        layer = self.sub_layer('a')
        reference = weakref.ref(layer)
        self.layer_model.get_index_of_layer(layer)
        self.layer_model.reset()
        del layer
        gc.collect()
        self.assertIsNotNone(reference(), 'the stage should still hold it')


class RemovingALayerThroughTheCommand(unittest.TestCase):
    """The order the views are told about it in.

    Everything that recomposites or moves the target can make a view
    repaint, and a repaint against the old shape reaches for layers that
    are no longer there. So the tree is told the layer set changed first.
    """

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix='nxt_order_')
        write_graph(os.path.join(self.tmp, 'a.nxt'), 'a',
                    node_names=['from_a'])
        write_graph(os.path.join(self.tmp, 'b.nxt'), 'b',
                    node_names=['from_b'])
        self.top_path = write_graph(os.path.join(self.tmp, 'top.nxt'), 'top',
                                    references=['a.nxt', 'b.nxt'],
                                    node_names=['from_top'])
        self.stage = Session().load_file(filepath=self.top_path)
        self.model = stage_model.StageModel(self.stage)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_layer_tree_hears_before_the_comp_changes(self):
        order = []
        self.model.layer_removed.connect(lambda p: order.append('removed'))
        self.model.comp_layer_changed.connect(
            lambda *a: order.append('comped'))
        self.model.target_layer_changed.connect(
            lambda *a: order.append('targeted'))
        self.model.set_layer_references(self.model.top_layer.real_path,
                                        ['a.nxt'])
        self.assertIn('removed', order)
        self.assertIn('comped', order)
        self.assertLess(order.index('removed'), order.index('comped'),
                        'the comp changed, and could have repainted a view, '
                        'before the tree was told a layer had gone')
        if 'targeted' in order:
            self.assertLess(order.index('removed'), order.index('targeted'),
                            'the target moved before the tree was told')


if __name__ == '__main__':
    unittest.main()
