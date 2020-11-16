import os
import unittest

from nxt.session import Session


class SubGraphs(unittest.TestCase):
    def setUp(self):
        os.chdir(os.path.dirname(__file__))
        self.stage = Session().load_file(filepath="test_sub_graph.nxt")

    def test_basic_run(self):
        """Test that a sub graph is run. The node that is run calls a sub-graph
        that creates a file. If that file is there, we can assert the garph has
        run.
        """
        expected_file = os.path.join(os.path.dirname(__file__),
                                     'sub_graph_file.txt')
        # The file must not exist if we are going to believe the graph made it.
        if os.path.isfile(expected_file):
            os.remove(expected_file)
        self.assertFalse(os.path.isfile(expected_file))
        self.stage.execute(start='/basic_file')
        self.assertTrue(os.path.isfile(expected_file))
        # Clean up after the test
        os.remove(expected_file)

    def test_parameters(self):
        """Test that local attributes of a node that calls a sub graph are
        pushed to the sub graph world node, and that resulting attributes of
        the sub graph world node are pulled back into the calling node.
        """
        target_path = '/specific_file'
        comp_layer = self.stage.build_stage()
        specific_node = comp_layer.lookup(target_path)
        expected_file = self.stage.get_node_attr_value(specific_node,
                                                       'location', comp_layer)
        # The file must not exist if we are going to believe the graph made it.
        if os.path.isfile(expected_file):
            os.remove(expected_file)
        self.assertFalse(os.path.isfile(expected_file))
        self.stage.execute(start=target_path)
        self.assertTrue(os.path.isfile(expected_file))
        # Clean up after the test
        os.remove(expected_file)
