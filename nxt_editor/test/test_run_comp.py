"""A run copies the graph shown while that is exact, and composites the
graph for itself when it is not.

Compositing the graph for each run took as long as opening it, before the
first node started. The comp the editor shows is the same as a fresh one
right after it is built, but many edits change it in place, and some of
those leave a node that inherits from the edited one as it was. So a run
copies it only while nothing has changed it in place since it was built.
"""
# Builtin
import json
import os
import random
import shutil
import sys
import tempfile
import unittest
from unittest import mock

# External
from Qt import QtWidgets

# Internal
from nxt import nxt_layer
from nxt.session import Session
from nxt.stage import Stage
from nxt_editor import stage_model
from nxt_editor.dialogs import NxtConfirmDialog

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

HAS_COPY = hasattr(nxt_layer.CompLayer, 'copy')


def write_graph(folder, nodes):
    path = os.path.join(folder, 'graph.nxt')
    with open(path, 'w') as fp:
        json.dump({'version': '1.17', 'alias': 'graph', 'nodes': nodes}, fp)
    return path


class Models(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='nxt_run_comp_')
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.models = []

    def tearDown(self):
        for model in self.models:
            model.deleteLater()
        app.processEvents()

    def model_for(self, nodes):
        stage = Session().load_file(write_graph(self.folder, nodes))
        model = stage_model.StageModel(stage)
        self.models.append(model)
        model.comp_layer
        return model

    def run_nodes(self, model, node_paths):
        model.execute_nodes(node_paths)
        while model.is_build_setup():
            app.processEvents()
        return model.current_rt_layer

    def count_comps(self):
        real = Stage.build_stage
        calls = []

        def counted(stage, *args, **kwargs):
            calls.append(1)
            return real(stage, *args, **kwargs)
        patch = mock.patch.object(Stage, 'build_stage', counted)
        patch.start()
        self.addCleanup(patch.stop)
        return calls


@unittest.skipUnless(HAS_COPY, 'nxt core without CompLayer.copy')
class Runs(Models):

    NODES = {'/src': {'attrs': {'ran': {'value': 'no'}},
                      'code': ['self.ran = "old"']},
             '/inst': {'instance': '/src'}}

    def test_a_run_after_opening_copies_the_graph_shown(self):
        model = self.model_for(self.NODES)
        self.assertTrue(model.comp_is_exact)
        calls = self.count_comps()
        runtime = self.run_nodes(model, ['/src', '/inst'])
        self.assertEqual([], calls)
        self.assertEqual('old', runtime.lookup('/inst').ran)
        # What the editor shows is left as it was.
        self.assertEqual('no', model.comp_layer.lookup('/src').ran)
        self.assertFalse(model.comp_layer.runtime)

    def test_after_a_code_edit_the_run_has_the_new_code_everywhere(self):
        model = self.model_for(self.NODES)
        model.set_node_code_lines('/src', ['self.ran = "new"'])
        model.stale_comp_timer.stop()
        self.assertFalse(model.comp_is_exact)
        calls = self.count_comps()
        runtime = self.run_nodes(model, ['/src', '/inst'])
        self.assertEqual(1, len(calls))
        self.assertEqual('new', runtime.lookup('/src').ran)
        # The instance runs the new code too, which the comp shown, changed
        # in place, does not have.
        self.assertEqual('new', runtime.lookup('/inst').ran)

    def test_after_a_run_the_graph_shown_is_the_fresh_comp(self):
        model = self.model_for(self.NODES)
        model.set_node_code_lines('/src', ['self.ran = "new"'])
        model.stale_comp_timer.stop()
        self.run_nodes(model, ['/src'])
        app.processEvents()
        self.assertTrue(model.comp_is_exact)
        self.assertEqual(['self.ran = "new"'],
                         model.comp_layer.lookup('/inst')._code)
        # So the next run copies it.
        calls = self.count_comps()
        runtime = self.run_nodes(model, ['/inst'])
        self.assertEqual([], calls)
        self.assertEqual('new', runtime.lookup('/inst').ran)

    def test_an_edit_while_it_ran_keeps_it_from_being_shown(self):
        model = self.model_for(self.NODES)
        model.set_node_code_lines('/src', ['self.ran = "new"'])
        model.stale_comp_timer.stop()
        model.setup_build(['/src'])
        fresh = model._fresh_comp[0]
        model.set_node_code_lines('/src', ['self.ran = "newer"'])
        model.stale_comp_timer.stop()
        model.finish_build(verbose=False)
        app.processEvents()
        self.assertIsNot(fresh, model.comp_layer)
        self.assertFalse(model.comp_is_exact)

    def test_a_quick_graph_is_built_again_soon_after_an_edit(self):
        model = self.model_for(self.NODES)
        model.set_node_code_lines('/src', ['self.ran = "new"'])
        self.assertTrue(model.stale_comp_timer.isActive())
        model.stale_comp_timer.timeout.emit()
        self.assertTrue(model.comp_is_exact)
        self.assertEqual(['self.ran = "new"'],
                         model.comp_layer.lookup('/inst')._code)

    def test_moving_nodes_keeps_it_exact(self):
        model = self.model_for(self.NODES)
        model.set_nodes_pos({'/src': (100.0, 50.0)})
        self.assertTrue(model.comp_is_exact)

    def test_checking_runs_in_a_fresh_comp_where_they_differ(self):
        model = self.model_for(self.NODES)
        # A comp said to be exact that is not, as a mistake would leave it.
        model.comp_layer.lookup('/inst')._code = ['self.ran = "stale"']
        with mock.patch.dict(os.environ,
                             {stage_model.CHECK_COMP_ENV_VAR: '1'}):
            runtime = self.run_nodes(model, ['/inst'])
        self.assertEqual('old', runtime.lookup('/inst').ran)


class FailedEdits(Models):

    def test_instancing_a_node_to_its_own_child_is_not_a_crash(self):
        model = self.model_for({'/a': {}, '/a/b': {}})
        model.set_node_instance('/a', '/a/b')
        # A comp leaves the cycle out, and so does the comp shown.
        node = model.comp_layer.lookup('/a')
        self.assertNotIn(model.comp_layer.lookup('/a/b'), node.__mro__)

    def test_an_edit_that_fails_is_logged(self):
        model = self.model_for({'/a': {}})
        with mock.patch.object(model.stage, 'node_setattr_data',
                               side_effect=RuntimeError('boom')), \
                self.assertLogs('nxt', level='ERROR') as logs:
            model.set_node_code_lines('/a', ['x = 1'])
        self.assertIn('boom', '\n'.join(logs.output))


@unittest.skipUnless(hasattr(nxt_layer, 'comp_differences'),
                     'nxt core without comp_differences')
class SaidExact(Models):
    """Whenever the comp shown is said to be exact, it is."""
    GRAPHS = 12
    EDITS = 15
    NAMES = ['a', 'b', 'c', 'd']

    def random_nodes(self, rnd):
        paths = ['/' + '/'.join(rnd.choice(self.NAMES)
                                for _ in range(rnd.randint(1, 3)))
                 for _ in range(rnd.randint(3, 8))]
        nodes = {}
        for path in paths:
            data = {}
            if rnd.random() < 0.3:
                data['instance'] = rnd.choice(paths)
            if rnd.random() < 0.4:
                data['code'] = ['x = 1']
            nodes[path] = data
        return nodes

    def edit(self, model, rnd):
        paths = [p for p in model.comp_layer._nodes_path_as_key
                 if p != '/']
        node = rnd.choice(paths) if paths else None
        other = rnd.choice(paths) if paths else None
        edits = [
            lambda: model.add_node(name=rnd.choice(self.NAMES),
                                   parent_path=node),
            lambda: model.set_node_code_lines(node, ['y = 2']),
            lambda: model.set_node_attr_value(node, 'v', '3'),
            lambda: model.set_node_instance(node, other),
            lambda: model.revert_node_instance(node),
            lambda: model.set_node_enabled([node], False),
            lambda: model.parent_nodes([node], other),
            lambda: model.delete_nodes([node]),
            lambda: model.set_node_child_order(node, ['b', 'a']),
            lambda: model.set_nodes_pos({node: (1.0, 2.0)}),
            model.undo,
            model.redo,
        ]
        if node is None:
            edits = edits[:1]
        rnd.choice(edits)()

    def test_random_edits(self):
        rnd = random.Random(7)
        patch = mock.patch.object(NxtConfirmDialog, 'show_message',
                                  return_value=True)
        patch.start()
        self.addCleanup(patch.stop)
        for graph in range(self.GRAPHS):
            model = self.model_for(self.random_nodes(rnd))
            for _ in range(self.EDITS):
                try:
                    self.edit(model, rnd)
                except Exception:
                    continue
                if not model.comp_is_exact:
                    continue
                fresh = model.stage.build_stage(
                    model.comp_layer.layer_idx())
                self.assertEqual(
                    [], nxt_layer.comp_differences(model.comp_layer, fresh),
                    graph)


if __name__ == '__main__':
    unittest.main()
