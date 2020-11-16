# Built-in
import unittest
import os
import logging

# Internal
from nxt.nxt_layer import LayerReturnTypes
from nxt import nxt, DATA_STATE
from nxt.nxt_node import INTERNAL_ATTRS
from nxt.session import Session

root_logger = logging.getLogger('nxt')
root_logger.propagate = False
root_logger.addHandler(logging.NullHandler())


def create_spec_graph_test_func(filename):
    def spec_test(self):
        stage = Session().load_file(filepath=filename)
        r = LayerReturnTypes.Node
        for input_node in stage.top_layer.descendants(return_type=r):
            # Only concerned with test input nodes
            name = getattr(input_node, INTERNAL_ATTRS.NAME)
            if not name.startswith('test'):
                continue
            if not name.endswith('input'):
                continue
            input_path = stage.top_layer.get_node_path(input_node)
            rt_layer = stage.execute(input_path)
            # Gather expectations
            expected_resolve_path = input_path.replace('input', 'resolved')
            expected_resolve_node = stage.top_layer.lookup(expected_resolve_path)
            expected_cache_path = input_path.replace('input', 'cached')
            expected_cache_node = stage.top_layer.lookup(expected_cache_path)
            cached_node = rt_layer.lookup(input_path)
            # Assert computes are equal
            resolved_code = stage.get_node_code_string(input_node,
                                                             layer=stage.top_layer,
                                                             data_state=DATA_STATE.RESOLVED)
            expected_resolve_code = stage.get_node_code_string(expected_resolve_node,
                                                                     layer=stage.top_layer.lookup,
                                                                     data_state=DATA_STATE.RAW)
            self.assertEqual(expected_resolve_code, resolved_code)
            cached_code = getattr(cached_node, INTERNAL_ATTRS.CACHED_CODE)
            expected_cached_code = stage.get_node_code_string(expected_cache_node,
                                                                    layer=rt_layer,
                                                                    data_state=DATA_STATE.RAW)
            self.assertEqual(expected_cached_code, cached_code)
            # Assert attrs are equal
            for attr_name in stage.get_node_attr_names(input_node):
                resolved_attr_val = stage.get_node_attr_value(input_node,
                                                              attr_name,
                                                              stage.top_layer,
                                                              resolved=True)
                excpected_resolve_attr_val = stage.get_node_attr_value(expected_resolve_node,
                                                                       attr_name,
                                                                       stage.top_layer,
                                                                       resolved=False)
                self.assertEqual(excpected_resolve_attr_val, resolved_attr_val)
                cached_attr_val = getattr(cached_node, attr_name)
                expected_cached_attr_val = stage.get_node_attr_value(expected_cache_node,
                                                                     attr_name,
                                                                     stage.top_layer)
                self.assertEqual(expected_cached_attr_val, cached_attr_val)
    return spec_test


class SpecGraphTest(unittest.TestCase):
    pass


test_dir = os.path.dirname(__file__)
SPEC_GRAPHS_DIR = os.path.join(test_dir, 'spec_graphs')

for filename in os.listdir(SPEC_GRAPHS_DIR):
    test_name = 'test_{}'.format(os.path.basename(filename))
    path = os.path.join(SPEC_GRAPHS_DIR, filename)
    func = create_spec_graph_test_func(path)
    func.__name__ = test_name
    setattr(SpecGraphTest, test_name, func)
