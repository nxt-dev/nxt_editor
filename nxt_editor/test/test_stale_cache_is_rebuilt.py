"""A cache that does not know the graph any more is rebuilt, not run.

Running a node again in the same interpreter is what makes the workflow
buttons quick, so the runtime layer from the last run is kept and offered
to the next one. It is a snapshot of the graph as it was, though, and a
node moved, renamed or deleted since is not in it.

Running against it anyway got as far as the missing node and then stopped
with a dialog asking the person to clear the cache by hand -- after the
nodes before it had already run, and whatever they did was already done.
Nothing has run yet when the build is being set up, so that is where a
cache that cannot do the job is thrown away and built again.
"""
# Builtin
import os
import sys
import unittest

# External
from Qt import QtWidgets

# Internal
from nxt.session import Session
from nxt_editor import stage_model

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

MOVE_ME = '/inst_source1'
NEW_PARENT = '/inst_source2'


class ACachedRuntimeLayer(unittest.TestCase):

    def setUp(self):
        os.chdir(os.path.dirname(__file__))
        self.stage = Session().load_file(filepath="StageInstanceTest.nxt")
        self.model = stage_model.StageModel(self.stage)

    def cache_for(self, node_paths):
        """A runtime layer built from the graph as it is now."""
        self.model.setup_build(node_paths)
        cache = self.model.current_rt_layer
        self.model.finish_build(verbose=False)
        return cache

    def move(self, node_path, parent_path):
        """Move a node, the way dragging it onto another one does."""
        self.model.parent_nodes([node_path], parent_path)
        return '/'.join([parent_path,
                         node_path.rsplit('/', 1)[-1]])

    # -- what it can still run ------------------------------------------

    def test_a_cache_that_knows_the_nodes_can_run_them(self):
        cache = self.cache_for([MOVE_ME])
        self.assertTrue(self.model.runtime_layer_can_run(cache, [MOVE_ME]))

    def test_no_cache_at_all_cannot(self):
        self.assertFalse(self.model.runtime_layer_can_run(None, [MOVE_ME]))

    def test_a_node_that_moved_is_not_in_it(self):
        cache = self.cache_for([MOVE_ME])
        moved_to = self.move(MOVE_ME, NEW_PARENT)
        self.assertTrue(self.model.node_exists(moved_to), 'it did not move')
        self.assertFalse(self.model.runtime_layer_can_run(cache, [moved_to]),
                         'the cache was taken before the node moved, so it '
                         'has never heard of where the node is now')

    def test_a_node_that_was_renamed_is_not_in_it(self):
        cache = self.cache_for([MOVE_ME])
        self.model.set_node_name(MOVE_ME, 'renamed_since',
                                 layer=self.model.top_layer)
        renamed = '/renamed_since'
        self.assertTrue(self.model.node_exists(renamed), 'it did not rename')
        self.assertFalse(self.model.runtime_layer_can_run(cache, [renamed]))

    def test_a_node_the_graph_dropped_is_still_in_the_snapshot(self):
        # Worth being plain about: this check is about what the cache can
        # run, not about what the graph still has. A node deleted since
        # is still in the snapshot, and it is the build order coming from
        # the graph rather than from the cache that keeps it from running.
        cache = self.cache_for([MOVE_ME])
        self.model.delete_nodes([MOVE_ME])
        self.assertFalse(self.model.node_exists(MOVE_ME))
        self.assertTrue(self.model.runtime_layer_can_run(cache, [MOVE_ME]))

    # -- and what setting up a build does about it ----------------------

    def test_a_cache_it_can_use_is_kept(self):
        cache = self.cache_for([MOVE_ME])
        self.model.setup_build([MOVE_ME], rt_layer=cache)
        self.assertIs(cache, self.model.current_rt_layer,
                      'the cache was thrown away for no reason, so the '
                      'interpreter state somebody was relying on is gone')
        self.model.finish_build(verbose=False)

    def test_a_cache_it_cannot_use_is_built_again(self):
        cache = self.cache_for([MOVE_ME])
        moved_to = self.move(MOVE_ME, NEW_PARENT)
        self.model.setup_build([moved_to], rt_layer=cache)
        self.assertIsNot(cache, self.model.current_rt_layer)
        self.model.finish_build(verbose=False)

    def test_and_the_new_one_knows_the_node(self):
        cache = self.cache_for([MOVE_ME])
        moved_to = self.move(MOVE_ME, NEW_PARENT)
        self.model.setup_build([moved_to], rt_layer=cache)
        fresh = self.model.current_rt_layer
        self.model.finish_build(verbose=False)
        self.assertTrue(self.model.runtime_layer_can_run(fresh, [moved_to]),
                        'the build would still have stopped at the node '
                        'that moved')

    def test_it_says_what_it_did(self):
        # Clearing the cache drops whatever the last run left in the
        # interpreter, which is not nothing, so it is not done quietly.
        cache = self.cache_for([MOVE_ME])
        moved_to = self.move(MOVE_ME, NEW_PARENT)
        with self.assertLogs('nxt', level='INFO') as caught:
            self.model.setup_build([moved_to], rt_layer=cache)
        self.model.finish_build(verbose=False)
        self.assertTrue([m for m in caught.output if 'cache' in m.lower()],
                        caught.output)

    def test_it_can_be_turned_off(self):
        # Whoever passes safe_exec=False is saying they know what is in
        # the cache and want it used as it is.
        cache = self.cache_for([MOVE_ME])
        moved_to = self.move(MOVE_ME, NEW_PARENT)
        self.model.setup_build([moved_to], rt_layer=cache, safe_exec=False)
        self.assertIs(cache, self.model.current_rt_layer)
        self.model.finish_build(verbose=False)


if __name__ == '__main__':
    unittest.main()
