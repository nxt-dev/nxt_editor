# Builtin
import os
import unittest

# Internal
from nxt import stage, nxt_layer


class TestReferences(unittest.TestCase):
    def test_reference_by_path(self):
        test_dir = os.path.dirname(__file__)
        empty_path = os.path.join(test_dir, 'empty.nxt')
        pre_test = stage.Stage.load_from_filepath(empty_path).build_stage()
        # assert that empty is empty
        self.assertEqual(0, len(pre_test.descendants()))
        # Test adding reference
        empty_spec_layer = nxt_layer.SpecLayer.load_from_filepath(empty_path)
        empty_spec_layer.add_reference('ref_test.nxt')
        temporary_graph_path = os.path.join(test_dir, 'IWILLBEDELTED.nxt')
        empty_spec_layer.save(temporary_graph_path)
        # Rebuild stage and verify
        stage_with_ref = stage.Stage.load_from_filepath(temporary_graph_path)
        comp_layer_with_ref = stage_with_ref.build_stage()
        # Remove before asserting, to clean up even on failure.
        os.remove(temporary_graph_path)
        self.assertIsNotNone(comp_layer_with_ref.lookup('/i_am_here'))

    def test_reference_by_obj(self):
        test_dir = os.path.dirname(__file__)
        empty_path = os.path.join(test_dir, 'empty.nxt')
        pre_test = stage.Stage.load_from_filepath(empty_path).build_stage()
        # assert that empty is empty
        self.assertEqual(0, len(pre_test.descendants()))
        # Test adding reference
        empty_spec_layer = nxt_layer.SpecLayer.load_from_filepath(empty_path)
        ref_path = os.path.join(test_dir, 'ref_test.nxt')
        ref_test_spec_layer = nxt_layer.SpecLayer.load_from_filepath(ref_path)
        empty_spec_layer.add_reference(layer=ref_test_spec_layer)
        temporary_graph_path = os.path.join(test_dir, 'IWILLBEDELTED.nxt')
        empty_spec_layer.save(temporary_graph_path)
        # Rebuild stage and verify
        stage_with_ref = stage.Stage.load_from_filepath(temporary_graph_path)
        comp_layer_with_ref = stage_with_ref.build_stage()
        # Remove before asserting, to clean up even on failure.
        os.remove(temporary_graph_path)
        self.assertIsNotNone(comp_layer_with_ref.lookup('/i_am_here'))

