"""A big value left by a node does not stall the editor after a build.

At the end of a build the model says its data changed, and the Property
Editor shows the selected node again, cached values and all. Naming a
cached value's type wrote it out as text, resolved tokens in that and
parsed it back, and the whole text was laid out in its cell: a list of a
million numbers held up the editor, and the host it runs in, for ten
seconds.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest import mock

# External
from Qt import QtWidgets

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt import DATA_STATE  # noqa: E402
from nxt_editor import stage_model  # noqa: E402
from nxt_editor.dockwidgets import property_editor  # noqa: E402
from nxt_editor.main_window import MainWindow  # noqa: E402

BIG = 1000000


def write_graph(folder):
    code = ['self.big = list(range({}))'.format(BIG),
            'self.small = [1, 2]',
            'self.text = "hello"',
            'self.thing = object()']
    nodes = {'/node': {'start_point': True, 'code': code}}
    graph = os.path.join(folder, 'graph.nxt')
    with open(graph, 'w') as fp:
        json.dump({'version': '1.17', 'alias': 'big', 'nodes': nodes}, fp)
    return graph


class BigCachedValues(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_big_cache_')
        self.win = MainWindow(filepath=write_graph(self.tmp))
        self.win.show()
        app.processEvents()
        self.model = self.win.model
        # Run on this thread, the way a host runs nodes.
        self.model.is_standalone = False
        self.model.set_selection(['/node'])
        self.win.build_view.exec_build_pressed()
        app.processEvents()
        self.cache = self.model.current_rt_layer.cache_layer

    def tearDown(self):
        self.model.data_state = DATA_STATE.RESOLVED
        self.win.hide()
        app.processEvents()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def attr_type(self, name):
        return self.model.get_node_attr_type('/node', name, self.cache)

    def test_cached_types_are_named_from_the_value(self):
        with mock.patch.object(stage_model, 'determine_nxt_type',
                               wraps=stage_model.determine_nxt_type) as slow:
            self.assertEqual('list', self.attr_type('big'))
            self.assertEqual('list', self.attr_type('small'))
            self.assertEqual('raw', self.attr_type('thing'))
        slow.assert_not_called()

    def test_named_as_before(self):
        # The same names the text of the value gave.
        for value in (1, 2.5, True, None, [1], (1,), {'a': 1}, {1}):
            self.assertEqual(stage_model.determine_nxt_type(repr(value)),
                             stage_model.cached_type_name(value))
        self.assertEqual('raw', stage_model.cached_type_name(object()))

    def test_a_big_value_is_shown_cut_short(self):
        self.model.data_state = DATA_STATE.CACHED
        app.processEvents()
        table = self.win.property_editor.model
        names = table.node_attr_names
        shown = table.attr_data_cached[names.index('big')]
        limit = property_editor.CACHED_MAX_CHARS
        self.assertLess(len(shown), limit + 50)
        self.assertTrue(shown.startswith('[0, 1, 2'))
        self.assertIn('characters)', shown)
        # A short one is shown whole.
        self.assertEqual('[1, 2]', table.attr_data_cached[
            names.index('small')])

    def test_showing_the_cache_is_quick(self):
        self.model.data_state = DATA_STATE.CACHED
        app.processEvents()
        start = time.time()
        self.model.data_state_changed.emit(True)
        app.processEvents()
        # It took ten seconds. Generous, for a slow runner.
        self.assertLess(time.time() - start, 2.0)


if __name__ == '__main__':
    unittest.main()
