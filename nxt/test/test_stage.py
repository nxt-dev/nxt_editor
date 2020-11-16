# Builtin
import json
import unittest
import logging
import os
from collections import OrderedDict

# Internal
from nxt import DATA_STATE, nxt_node, nxt_layer
from nxt import stage
from nxt import nxt_path
from nxt.constants import GRAPH_VERSION
from nxt.nxt_node import INTERNAL_ATTRS
from nxt.session import Session
from nxt.nxt_layer import SAVE_KEY, META_DATA_KEY

path_logger = logging.getLogger(nxt_path.__name__)
path_logger.propagate = False


class StageGeneral(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.chdir(os.path.dirname(__file__))
        cls.stage = Session().load_file(filepath="./StageLoadTest.nxt")
        cls.comp_layer = cls.stage.build_stage()
        cls.runtime_layer = cls.stage.setup_runtime_layer(cls.comp_layer)

    def test_load_data_against_save_data(self):
        """Orders predefined save data and tests against save data generated
        by the stage.
        :return: None
        """
        self.expected_data = r"""{
    "version": "1.17", 
    "alias": "StageLoadTest", 
    "color": "#22728f", 
    "mute": false, 
    "solo": false, 
    "meta_data": {
        "positions": {
            "/Types": [
                4, 
                20
            ]
        }
    }, 
    "nodes": {
        "/Types": {
            "enabled": true, 
            "attrs": {
                "_bool": {
                    "type": "bool", 
                    "value": "True"
                }, 
                "_dict": {
                    "type": "dict", 
                    "value": "{}"
                }, 
                "_float": {
                    "type": "float", 
                    "value": "0.5"
                }, 
                "_int": {
                    "type": "int", 
                    "value": "123"
                }, 
                "_list": {
                    "type": "list", 
                    "value": "[${_str1}, ${_str2}, '${_raw}_limb_pv', '${_raw}_limb_ik']"
                }, 
                "_none": {
                    "type": "NoneType"
                }, 
                "_raw": {
                    "type": "raw", 
                    "value": "l"
                }, 
                "_str1": {
                    "type": "str", 
                    "value": "'single'"
                }, 
                "_str2": {
                    "type": "str", 
                    "value": "\"double\""
                }, 
                "_tuple": {
                    "type": "tuple", 
                    "value": "(${_int}, ${_float})"
                }
            }, 
            "code": [
                "${_list}  # List", 
                "${_tuple}  # Tuple", 
                "${_str1}  # String with single quote", 
                "${_str2}  # String with double quote ", 
                "${_raw}  # Raw", 
                "${_int}  # Int", 
                "${_float}  # Float", 
                "${_dict}  # Dict", 
                "${_bool}  # Bool"
            ]
        }
    }
}"""
        print("Testing a save data dict against a "
              "literal dict of the loaded data")
        self.raw_save_data = self.stage.get_layer_save_data(0)
        self.save_data = json.dumps(self.raw_save_data, indent=4)
        self.assertEqual(self.expected_data, self.save_data)

    def test_lookup(self):
        print("testing lookup")
        print("Testing that `/Node` is a invalid namespace.")
        self.assertIsNone(self.comp_layer.lookup("/Node"))
        print("Testing that `/Types` is a valid namespace.")
        self.assertIsNotNone(self.comp_layer.lookup("/Types"))
        print("Testing that the node at `/Types` is named `Types`.")
        self.assertEqual('Types', getattr(self.comp_layer.lookup("/Types"),
                                          INTERNAL_ATTRS.NAME))

    def test_runtime_lookup(self):
        print("test runtime lookup")
        print("Testing that `/Node` is a invalid runtime namespace.")
        self.assertIsNone(self.runtime_layer.lookup("/Node"))
        print("Testing that `/Types` is a valid runtime namespace.")
        n = self.runtime_layer.lookup("/Types")
        self.assertIsNotNone(n)
        print("Testing that the runtime node at `/Types` is named `Types`.")
        self.assertEqual('Types', getattr(self.runtime_layer.lookup("/Types"),
                                          INTERNAL_ATTRS.NAME))


class StageParentPaths(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        print("SetUp StageInherit")
        os.chdir(os.path.dirname(__file__))
        cls.stage = Session().load_file(filepath="./StageInheritTest.nxt")
        cls.comp_layer = cls.stage.build_stage()
        cls.layer = cls.stage._sub_layers[0]
        cls.parent_path = '/parent_node'
        cls.parent_node = cls.comp_layer.lookup(cls.parent_path)
        cls.child_path = '/parent_node/child_node'
        cls.child_node = cls.comp_layer.lookup(cls.child_path)
        cls.node1 = cls.comp_layer.lookup('/node1')
        cls.node2 = cls.comp_layer.lookup('/node2')
        cls.node3 = cls.comp_layer.lookup('/node3')
        cls.node3_child = cls.comp_layer.lookup('/node3/child')
        cls.inst_tgt = cls.comp_layer.lookup('/inst_tgt_parent')
        cls.inst_tgt_child = cls.comp_layer.lookup('/inst_tgt_parent/child')

    def test_internal_attr_inherit(self):
        print("Test if internal attrs are inherited as expected.")
        print("Test if the child node has the attr "
              "`.{}`".format(INTERNAL_ATTRS.PARENT_PATH))
        self.assertIs(True, hasattr(self.child_node,
                                    INTERNAL_ATTRS.PARENT_PATH))
        print("Test if the child node `.{}` "
              "value is not None".format(INTERNAL_ATTRS.PARENT_PATH))
        self.assertIsNotNone(getattr(self.child_node,
                                     INTERNAL_ATTRS.PARENT_PATH))
        print("Test if the inherit node's name is really `parent_node`")
        parent_path = getattr(self.child_node, INTERNAL_ATTRS.PARENT_PATH)
        parent = self.layer.lookup(parent_path)
        name = getattr(parent, INTERNAL_ATTRS.NAME)
        self.assertEqual('parent_node', name)
        # COMPUTE INHERITANCE
        pn_expected_code = ['# Code']
        pn_actual_code = getattr(self.parent_node, INTERNAL_ATTRS.COMPUTE)
        self.assertEqual(pn_expected_code, pn_actual_code)
        cn_expected_code = []
        cn_actual_code = getattr(self.child_node, INTERNAL_ATTRS.COMPUTE)
        self.assertEqual(cn_expected_code, cn_actual_code)
        n1_expected_code = ['# BOTTOM']
        n1_actual_code = getattr(self.node1, INTERNAL_ATTRS.COMPUTE)
        self.assertEqual(n1_expected_code, n1_actual_code)
        n2_expected_code = ['']
        n2_actual_code = getattr(self.node2, INTERNAL_ATTRS.COMPUTE)
        self.assertEqual(n2_expected_code, n2_actual_code)
        inst_tgt_expected_code = ['# Parent code']
        inst_tgt_actual_code = getattr(self.inst_tgt, INTERNAL_ATTRS.COMPUTE)
        self.assertEqual(inst_tgt_expected_code, inst_tgt_actual_code)
        inst_tgt_expected_child_code = ['# Child code']
        inst_tgt_actual_child_code = getattr(self.inst_tgt_child,
                                                INTERNAL_ATTRS.COMPUTE)
        self.assertEqual(inst_tgt_expected_child_code,
                         inst_tgt_actual_child_code)
        # COMMENT INHERITANCE
        pn_expected_comment = 'Node - layer 1'
        pn_actual_comment = getattr(self.parent_node, INTERNAL_ATTRS.COMMENT)
        self.assertEqual(pn_expected_comment, pn_actual_comment)
        cn_expected_comment = None
        cn_actual_comment = getattr(self.child_node, INTERNAL_ATTRS.COMMENT)
        self.assertEqual(cn_expected_comment, cn_actual_comment)
        n1_expected_comment = 'Node1 - layer 0'
        n1_actual_comment = getattr(self.node1, INTERNAL_ATTRS.COMMENT)
        self.assertEqual(n1_expected_comment, n1_actual_comment)
        n2_expected_comment = 'Node2 - layer 0'
        n2_actual_comment = getattr(self.node2, INTERNAL_ATTRS.COMMENT)
        self.assertEqual(n2_expected_comment, n2_actual_comment)
        # START POINT INHERITANCE
        # TODO: When save files are flat test start points
        # INSTANCE INHERITANCE
        n2_expected_inst_path = '/Instance/Path'
        n2_actual_inst_path = getattr(self.node2, INTERNAL_ATTRS.INSTANCE_PATH)
        self.assertEqual(n2_expected_inst_path, n2_actual_inst_path)
        # EXEC INHERITANCE
        n2_expected_exec_in = '/node1'
        n2_actual_exec_in = getattr(self.node2, INTERNAL_ATTRS.EXECUTE_IN)
        self.assertEqual(n2_expected_exec_in, n2_actual_exec_in)
        # ENABLED INHERITANCE
        n2_expected_enabled = True
        n2_actual_enabled = getattr(self.node2, INTERNAL_ATTRS.ENABLED)
        self.assertEqual(n2_expected_enabled, n2_actual_enabled)
        parent_expected_enabled = False
        parent_actual_enabled = getattr(self.parent_node,
                                        INTERNAL_ATTRS.ENABLED)
        self.assertEqual(parent_expected_enabled, parent_actual_enabled)
        child_expected_enabled = True
        child_actual_enabled = getattr(self.child_node, INTERNAL_ATTRS.ENABLED)
        self.assertEqual(child_expected_enabled, child_actual_enabled)
        n3_expected_enabled = False
        n3_actual_enabled = getattr(self.node3, INTERNAL_ATTRS.ENABLED)
        self.assertEqual(n3_expected_enabled, n3_actual_enabled)
        n3_child_expected_enabled = None
        n3_child_actual_enabled = getattr(self.node3_child, INTERNAL_ATTRS.ENABLED)
        self.assertEqual(n3_child_expected_enabled, n3_child_actual_enabled)

    def test_inherit_attrs(self):
        print("Testing if child node inherits attrs from its parent...")
        print("Checking that the `.parent` attr from the parent node is NOT "
              "local to the child node.")
        child_locals = nxt_layer.get_node_local_attr_names(self.child_path,
                                                           [self.layer])
        self.assertNotIn('parent', child_locals)
        print("Checking that the `.parent` attr from the parent node IS "
              "local to the parent node.")
        parent_locals = nxt_layer.get_node_local_attr_names(self.parent_path,
                                                            [self.layer])
        self.assertIn('parent', parent_locals)
        # Test that code is inherited across layers
        print("Test that the code IS inherited from the LOWER LAYER.")
        self.assertEqual(["# BOTTOM"], getattr(self.node1,
                                               INTERNAL_ATTRS.COMPUTE))
        self.assertNotEqual(["# BOTTOM2"], getattr(self.node2,
                                                   INTERNAL_ATTRS.COMPUTE))
        # Test that session layer is created
        print("Generating session layer and runtime nodes...")
        self.runtime_layer = self.stage.execute('/parent_node')
        print("Confirm `runtime_layer` is not None.")
        self.assertIsNotNone(self.runtime_layer)
        # Test that node spec has the same name as the runtime node
        runtime_parent = self.runtime_layer.lookup('/parent_node')
        runtime_parent_children = self.runtime_layer.children('/parent_node',
                                                              ordered=True)
        rt_node1 = self.runtime_layer.lookup('/node1')
        rt_node2 = self.runtime_layer.lookup('/node2')
        print("Checking that runtime PARENT node name matches editor PARENT "
              "node name.")
        name = getattr(self.parent_node, INTERNAL_ATTRS.NAME)
        rt_name = getattr(runtime_parent, INTERNAL_ATTRS.NAME)
        self.assertEqual(name, rt_name)
        runtime_child = runtime_parent_children[0]
        print("Checking that runtime CHILD node name matches editor CHILD "
              "node name.")
        name = getattr(self.child_node, INTERNAL_ATTRS.NAME)
        rt_name = getattr(runtime_child, INTERNAL_ATTRS.NAME)
        self.assertEqual(name, rt_name)
        print("Test that the local attr from the parent node IS accessible"
              "from the RUNTIME child node via `self`.")
        self.assertIs(True, hasattr(runtime_child, 'parent'))
        print("Test that the local attr from the parent node is IS accessible"
              "from the EDITOR child node via `self`.")
        self.assertEquals(True, hasattr(self.child_node, 'parent'))
        # Test that code is not inherited
        print("Test that child code is NOT inherited FROM the PARENT.")
        self.assertEqual(["# Code"], getattr(runtime_parent,
                                             INTERNAL_ATTRS.COMPUTE))
        self.assertNotEqual(["# Code"], getattr(runtime_child,
                                                INTERNAL_ATTRS.COMPUTE))
        # Test that code is inherited across layers
        print("Test that the code IS inherited from the LOWER LAYER.")
        self.assertEqual(["# BOTTOM"], getattr(rt_node1,
                                               INTERNAL_ATTRS.COMPUTE))
        self.assertNotEqual(["# BOTTOM2"], getattr(rt_node2,
                                                   INTERNAL_ATTRS.COMPUTE))
        print("Test that attrs are overloaded top down.")
        expected = "top"
        actual = getattr(self.node2, 'attr')
        self.assertEqual(expected, actual)

    def test_parent_function(self):
        print("Test that paths are not broken when nodes with similar names "
              "are parented together.")
        target_layer = self.stage.top_layer
        node = target_layer.lookup('/parent_node')
        self.stage.parent_nodes(nodes=[node], parent_path='/node2',
                                layer=target_layer)
        self.comp_layer = self.stage.build_stage()
        expected_path = '/node2/parent_node/child_node'
        display_node = self.comp_layer.lookup('/node2/parent_node/child_node')
        self.assertIsNotNone(display_node)
        display_name = getattr(display_node, INTERNAL_ATTRS.NAME)
        display_parent_path = getattr(display_node, INTERNAL_ATTRS.PARENT_PATH)
        actual_path = nxt_path.join_node_paths(display_parent_path,
                                               display_name)
        self.assertEqual(expected_path, actual_path)


class StageInstance1(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        print("Class SetUp StageInstance")
        os.chdir(os.path.dirname(__file__))
        cls.stage = Session().load_file(filepath="./StageInstanceTest.nxt")
        cls.comp_layer = cls.stage.build_stage()
        cls.layer = cls.stage._sub_layers[0]
        # Lookup the nodes we are instancing from/to (source, target)
        #       Test1
        cls.inst_source1_path = '/inst_source1'
        cls.inst_source1 = cls.comp_layer.lookup(cls.inst_source1_path)
        cls.inst_target1_path = '/inst_target1'
        cls.inst_target1 = cls.comp_layer.lookup(cls.inst_target1_path)
        cls.inst_source1_child_path = '/inst_source1/inst_source1_child'
        cls.inst_source1_child = cls.comp_layer.lookup(cls.inst_source1_child_path)
        cls.inst_target1_child_path = '/inst_target1/inst_source1_child'
        cls.inst_target1_child = cls.comp_layer.lookup(cls.inst_target1_child_path)
        #       Test 2
        cls.inst_source2_path = '/inst_source2'
        cls.inst_source2 = cls.comp_layer.lookup(cls.inst_source2_path)
        cls.inst_source2_child_path = '/inst_source2/inst_source2_child'
        cls.inst_source2_child = cls.comp_layer.lookup(cls.inst_source2_child_path)
        cls.inst_source2_middle_path = '/inst_source2_middle'
        cls.inst_source2_middle = cls.comp_layer.lookup(cls.inst_source2_middle_path)
        cls.inst_source2_middle_child_path = '/inst_source2_middle/inst_source2_middle_child'
        cls.inst_source2_middle_child = cls.comp_layer.lookup(cls.inst_source2_middle_child_path)

        cls.inst_target2_path = '/inst_target2'
        cls.inst_target2 = cls.comp_layer.lookup(cls.inst_target2_path)
        cls.inst_target2_child_path = '/inst_source2_middle/inst_source2_child'
        cls.inst_target2_child = cls.comp_layer.lookup(cls.inst_target2_child_path)
        cls.inst_target2_middle_child_path = '/inst_source2_middle/inst_source2_middle_child'
        cls.inst_target2_middle_child = cls.comp_layer.lookup(cls.inst_target2_middle_child_path)

        # Edgecase test
        cls.top_node_path = '/top'
        cls.top_node = cls.comp_layer.lookup(cls.top_node_path)
        cls.inst_from_node_path = '/instFrom'
        cls.inst_from_node = cls.comp_layer.lookup(cls.inst_from_node_path)
        cls.inst_to_node_path = '/top/instTo'
        cls.inst_to_node = cls.comp_layer.lookup(cls.inst_to_node_path)

        # Setup the session layer which generates runtime nodes
        cls.runtime_layer = cls.stage.setup_runtime_layer(cls.comp_layer)
        # Lookup all the runtime nodes
        #       Test 1
        cls.rt_inst_source1 = cls.runtime_layer.lookup(cls.inst_source1_path)
        cls.rt_inst_target1 = cls.runtime_layer.lookup(cls.inst_target1_path)
        cls.rt_inst_source1_child = cls.runtime_layer.lookup(cls.inst_source1_child_path)
        cls.rt_inst_target1_child = cls.runtime_layer.lookup(cls.inst_target1_child_path)
        cls.rt_inst_target1_real_child_path = '/inst_target1/RealChild'
        cls.rt_inst_target1_real_child = cls.runtime_layer.lookup(cls.rt_inst_target1_real_child_path)
        #       Test 2
        cls.rt_inst_source2 = cls.runtime_layer.lookup(cls.inst_source2_path)
        cls.rt_inst_source2_child = cls.runtime_layer.lookup(cls.inst_source2_child_path)

        cls.rt_inst_source2_middle = cls.runtime_layer.lookup(cls.inst_source2_middle_path)
        cls.rt_inst_source2_middle_child = cls.runtime_layer.lookup(cls.inst_source2_middle_child_path)
        cls.rt_inst_source2_middle_inst_child_path = '/inst_source2_middle/inst_source2_child'
        cls.rt_inst_source2_middle_inst_child = cls.runtime_layer.lookup(cls.rt_inst_source2_middle_inst_child_path)

        cls.rt_inst_target2 = cls.runtime_layer.lookup(cls.inst_target2_path)
        cls.rt_inst_target2_middle_child = cls.runtime_layer.lookup(cls.inst_target2_middle_child_path)
        cls.rt_inst_target2_child = cls.runtime_layer.lookup(cls.inst_target2_child_path)

    def test_editor_time1(self):
        print("Testing instancing scenario 1 at EDITOR time...")
        print("Test the editor time instance source is set as the "
              "`._instance` for the target.")
        inst, _ = self.stage.safe_get_node_instance(self.inst_target1,
                                                    self.comp_layer)
        self.assertIs(self.inst_source1, inst)
        # And do the same for the child node.
        print("Same test for child node.")
        tgt_children = self.comp_layer.children(self.inst_target1_path,
                                                ordered=True)
        child_inst, _ = self.stage.safe_get_node_instance(tgt_children[1],
                                                          self.comp_layer)
        self.assertIs(self.inst_source1_child, child_inst)
        # The child node should be a proxy node
        print("Test that child node is a "
              "`.{}` node.".format(INTERNAL_ATTRS.PROXY))
        self.assertIs(True, getattr(tgt_children[1], INTERNAL_ATTRS.PROXY))
        # Test if nodes have all the expected children
        print("Test that the instance SOURCE have the expected number of "
              "children (1).")
        src_children = self.comp_layer.children(self.inst_source1_path)
        self.assertEqual(1, len(src_children))
        print("Test that the instance TARGET have the expected number of "
              "children (2).")
        self.assertEqual(2, len(tgt_children))

    def test_editor_time2(self):
        print("Testing instancing scenario 2 at EDITOR time...")
        # Test case 2 editor time has all the expected children
        print("Testing number of children for the three trees in this "
              "scenario.")
        children = self.comp_layer.children(self.inst_source2_path)
        self.assertEqual(1, len(children))
        children = self.comp_layer.children(self.inst_source2_middle_path)
        self.assertEqual(2, len(children))
        children = self.comp_layer.children(self.inst_target2_path)
        self.assertEqual(2, len(children))
        print("Testing that all resolved codes match expected literals.")
        c = self.stage.get_node_code_lines(self.inst_source2,
                                              self.comp_layer,
                                              data_state=DATA_STATE.RESOLVED)
        self.assertEqual(["# Instance Root Code"], c)
        c = self.stage.get_node_code_lines(self.inst_source2_child,
                                              self.comp_layer,
                                              data_state=DATA_STATE.RESOLVED)
        self.assertEqual(["# Instance Code"], c)
        c = self.stage.get_node_code_lines(self.inst_source2_middle,
                                              self.comp_layer,
                                              data_state=DATA_STATE.RESOLVED)
        self.assertEqual(["# Instance Root Code"], c)
        c = self.stage.get_node_code_lines(self.inst_source2_middle_child,
                                              self.comp_layer,
                                              data_state=DATA_STATE.RESOLVED)
        self.assertEqual(["# Instance Middle Code"], c)
        c = self.stage.get_node_code_lines(self.inst_target2,
                                              self.comp_layer,
                                              data_state=DATA_STATE.RESOLVED)
        self.assertEqual(["# Instance Root Code"], c)
        c = self.stage.get_node_code_lines(self.inst_target2_middle_child,
                                              self.comp_layer,
                                              data_state=DATA_STATE.RESOLVED)
        self.assertEqual(["# Instance Middle Code"], c)
        c = self.stage.get_node_code_lines(self.inst_target2_child,
                                              self.comp_layer,
                                              data_state=DATA_STATE.RESOLVED)
        self.assertEqual(["# Instance Code"], c)

    def test_runtime_setup1(self):
        func = self.stage.get_node_code_lines
        print("Testing instancing scenario 1 at RUNTIME...")
        print("Testing that expected attrs are on the runtime target node.")
        self.assertIs(True, hasattr(self.rt_inst_target1, "InstSourceAttr"))
        print("Testing the value is the expected one.")
        self.assertEqual('Hello', getattr(self.rt_inst_target1,
                                          "InstSourceAttr"))
        print("Testing the instance target code resolves as expected, "
              "uses a local and remote attr ref.")
        rt_real_child_resolved_code = func(self.rt_inst_target1_real_child,
                                              layer=self.runtime_layer,
                                              data_state=DATA_STATE.RESOLVED)
        self.assertEqual(["\"Hello World\""], rt_real_child_resolved_code)
        # Test if inst source code is the same as target code
        print("Test if inst source code IS the same as target code.")
        rt_inst_target_code = func(self.rt_inst_target1,
                                      layer=self.runtime_layer,
                                      data_state=DATA_STATE.RESOLVED)
        expected_code = getattr(self.rt_inst_source1, INTERNAL_ATTRS.COMPUTE)
        self.assertEqual(expected_code, rt_inst_target_code)
        print("Test if inst SOURCE CHILD code is the same as the TARGET "
              "inst CHILD code")
        rt_inst_target_child_code = func(self.rt_inst_target1_child,
                                            layer=self.runtime_layer,
                                            data_state=DATA_STATE.RESOLVED)
        expected_code = getattr(self.rt_inst_source1_child,
                                   INTERNAL_ATTRS.COMPUTE)
        self.assertEqual(expected_code, rt_inst_target_child_code)

    def test_runtime_setup2(self):
        func = self.stage.get_node_code_lines
        print("Testing instancing scenario 2 at RUNTIME...")
        # Test case 2 runtime has all the expected children
        print("Testing number of children for the three runtime trees in "
              "this scenario.")
        children = self.runtime_layer.children(self.inst_source2_path)
        self.assertEqual(1, len(children))
        children = self.runtime_layer.children(self.inst_source2_middle_path)
        self.assertEqual(2, len(children))
        children = self.runtime_layer.children(self.inst_target2_path)
        self.assertEqual(2, len(children))
        print("Testing that all runtime resolved codes match expected "
              "literals.")
        c = func(self.rt_inst_source2, layer=self.runtime_layer,
                 data_state=DATA_STATE.RESOLVED)
        self.assertEqual(["# Instance Root Code"], c)
        c = func(self.inst_source2_child, layer=self.runtime_layer,
                 data_state=DATA_STATE.RESOLVED)
        self.assertEqual(["# Instance Code"], c)
        c = func(self.rt_inst_source2_middle, layer=self.runtime_layer,
                 data_state=DATA_STATE.RESOLVED)
        self.assertEqual(["# Instance Root Code"], c)
        c = func(self.rt_inst_source2_middle_child, layer=self.runtime_layer,
                 data_state=DATA_STATE.RESOLVED)
        self.assertEqual(["# Instance Middle Code"], c)
        c = func(self.rt_inst_target2, layer=self.runtime_layer,
                 data_state=DATA_STATE.RESOLVED)
        self.assertEqual(["# Instance Root Code"], c)
        c = func(self.rt_inst_target2_middle_child, layer=self.runtime_layer,
                 data_state=DATA_STATE.RESOLVED)
        self.assertEqual(["# Instance Middle Code"], c)
        c = func(self.rt_inst_target2_child, layer=self.runtime_layer,
                 data_state=DATA_STATE.RESOLVED)
        self.assertEqual(["# Instance Code"], c)
        print("Test expected attrs are accessible via self.")
        # Test attrs are accessible via self
        self.assertIs(True, hasattr(self.rt_inst_source2_child, "attr0"))
        self.assertIs(True, hasattr(self.rt_inst_source2_child, "attr0_1"))
        # Middle real child
        self.assertIs(True, hasattr(self.rt_inst_source2_middle_child, "attr0"))
        self.assertIs(True, hasattr(self.rt_inst_source2_middle_child, "attr1"))
        self.assertIs(True, hasattr(self.rt_inst_source2_middle_child,
                                    "attr1_1"))
        # Middle inst child
        self.assertIs(True, hasattr(self.rt_inst_source2_middle_inst_child,
                                    "attr0"))
        self.assertIs(True, hasattr(self.rt_inst_source2_middle_inst_child,
                                    "attr1"))
        self.assertIs(True, hasattr(self.rt_inst_source2_middle_inst_child,
                                    "attr0_1"))
        # Target
        self.assertIs(True, hasattr(self.rt_inst_target2, "attr0"))
        self.assertIs(True, hasattr(self.rt_inst_target2, "attr1"))
        # Target inst source child (deepest instance child)
        self.assertIs(True, hasattr(self.rt_inst_target2_child, "attr0"))
        self.assertIs(True, hasattr(self.rt_inst_target2_child, "attr1"))
        self.assertIs(True, hasattr(self.rt_inst_target2_child, "attr0_1"))
        # Target middle inst child
        self.assertIs(True, hasattr(self.rt_inst_target2_middle_child,
                                    "attr1_1"))
        self.assertIs(True, hasattr(self.rt_inst_target2_middle_child,
                                    "attr1"))
        self.assertIs(True, hasattr(self.rt_inst_target2_middle_child,
                                    "attr0"))

    def test_name_edege_case1(self):
        print("Test that instance nodes parent to their parent and not their "
              "grandparent node.")
        top_children = self.comp_layer.children(self.top_node_path)
        top_child_names = [getattr(n, INTERNAL_ATTRS.NAME)
                           for n in top_children]
        self.assertEqual(['instTo'], top_child_names)
        source_children = self.comp_layer.children(self.inst_from_node_path,
                                                   ordered=True)
        source_child_names = [getattr(n, INTERNAL_ATTRS.NAME)
                              for n in source_children]
        target_children = self.comp_layer.children(self.inst_to_node_path,
                                                   ordered=True)
        target_child_names = [getattr(n, INTERNAL_ATTRS.NAME)
                              for n in target_children]
        self.assertEqual(source_child_names, target_child_names)

    def test_ns_depth_case1(self):
        print('Test that shallow namespaces correctly merge with deep.')
        node = self.comp_layer.lookup('/rig_workflow/file_io/importers/'
                                      'joint_importers/joints_layout/skeleton/'
                                      'connect_twist/joints')
        self.assertIsNone(node)
        node = self.comp_layer.lookup('/rig_workflow/file_io/importers/'
                                      'joint_importers/joints_layout/skeleton/'
                                      'connect_twist/joints/connect_twist')
        self.assertIsNone(node)
        node = self.comp_layer.lookup('/rig_workflow/file_io/importers/'
                                      'joint_importers/joints_layout/skeleton/'
                                      'connect_twist')
        self.assertIsNotNone(node)
        node = self.comp_layer.lookup('/rig_workflow/file_io/importers/'
                                      'joint_importers/joints_layout/skeleton/'
                                      'connect_twist/left/node')
        self.assertIsNotNone(node)


    def test_instance_child_attr_overload(self):
        '''Test that an instance source child can overload its parent attr
        value.'''
        print("Testing that an instance source child can overload its parent "
              "attr value.")
        proxy_node4 = self.comp_layer.lookup('/inst_target4/inst_source4_child')
        expected_code4 = "\"The base should be 1 is it? base == 1\""
        state = DATA_STATE.RESOLVED
        actual_code = self.stage.get_node_code_string(proxy_node4,
                                                            self.comp_layer,
                                                            state)
        self.assertEqual(expected_code4, actual_code)
        expected_attr = '1'
        actual_attr = self.stage.get_node_attr_value(proxy_node4, 'base',
                                                     self.comp_layer)
        self.assertEqual(expected_attr, actual_attr)
        print("Testing that the SOURCE CHILD overload is cached correctly.")
        rt_layer = self.stage.execute('/inst_source4')
        path = '/inst_target4/inst_source4_child'
        rt_proxy_node4 = rt_layer.cache_layer.lookup(path)
        rt_actual4 = getattr(rt_proxy_node4, INTERNAL_ATTRS.CACHED_CODE)
        self.assertEqual(expected_code4, rt_actual4)

    def test_instance_parent_attr_overload(self):
        print("Testing that an instance target can overload its "
              "child's attr value (1 level deep).")
        proxy5_path = '/inst_target5/inst_source5_child'
        proxy_node5 = self.comp_layer.lookup(proxy5_path)
        expected_attr = '5'
        actual_attr = self.stage.get_node_attr_value(proxy_node5, 'base',
                                                     self.comp_layer)
        self.assertEqual(expected_attr, actual_attr)
        print("Testing that an instance target can overload its "
              "child's attr value (2 levels deep).")
        proxy6_path = '/inst_target6/RealChild/inst_source6_child'
        proxy_node6 = self.comp_layer.lookup(proxy6_path)
        expected_attr = 'B'
        actual_attr = self.stage.get_node_attr_value(proxy_node6, 'base',
                                                     self.comp_layer)
        self.assertEqual(expected_attr, actual_attr)
        print("Testing that the TARGET PARENT overload is cached correctly "
              "(1 level deep).")
        rt_layer = self.stage.execute('/inst_source5')
        rt_proxy_node5 = rt_layer.cache_layer.lookup(proxy5_path)
        rt_actual5 = getattr(rt_proxy_node5, INTERNAL_ATTRS.CACHED_CODE)
        expected_code5 = "\"The base should be 5 is it? base == 5\""
        self.assertEqual(expected_code5, rt_actual5)
        print("Testing that the TARGET PARENT overload is cached correctly "
              "(2 levels deep).")
        rt_layer = self.stage.execute('/inst_source6')
        rt_proxy_node6 = rt_layer.cache_layer.lookup(proxy6_path)
        rt_actual6 = getattr(rt_proxy_node6, INTERNAL_ATTRS.CACHED_CODE)
        expected_code5 = "\"The base should be B is it? base == B\""
        self.assertEqual(expected_code5, rt_actual6)

    def test_instance_mid_to_top(self):
        print("Test that nodes can instance from a non-root to a root.")
        expected_children = ['c1', 'c2']
        rt = self.comp_layer.RETURNS.Path
        actual_children = self.comp_layer.children('/mid_tgt',
                                                   return_type=rt, ordered=True)
        actual_children = [nxt_path.node_name_from_node_path(p) for p in
                           actual_children]
        self.assertEqual(expected_children, actual_children)
        print("Test that instance path is correct.")
        expected_inst_path = '/top2/mid'
        node = self.comp_layer.lookup('/mid_tgt')
        ip = INTERNAL_ATTRS.INSTANCE_PATH
        actual_inst_path = self.stage.get_node_attr_value(node, ip,
                                                          self.comp_layer)
        self.assertEqual(expected_inst_path, actual_inst_path)


class StageInstance2(unittest.TestCase):

    @classmethod
    def setUp(cls):
        print("Class SetUp StageInstance")
        os.chdir(os.path.dirname(__file__))
        cls.stage = Session().load_file(filepath="./StageInstanceAcrossLayersTest.nxt")
        cls.comp_layer = cls.stage.build_stage()
        cls.layer = cls.stage._sub_layers[0]
        # Lookup the nodes we are instancing from/to (source, target)
        #       Test1
        cls.inst_source3_path = '/inst_source3'
        cls.inst_source3 = cls.comp_layer.lookup(cls.inst_source3_path)
        cls.inst_target3_path = '/inst_target3'
        cls.inst_target3 = cls.comp_layer.lookup(cls.inst_target3_path)
        cls.inst_target3_child_path = '/inst_target3/RealChild'
        cls.inst_target3_child = cls.comp_layer.lookup(cls.inst_target3_child_path)
        # Setup the session layer which generates runtime nodes
        cls.runtime_layer = cls.stage.setup_runtime_layer(cls.comp_layer)
        # Lookup all the runtime nodes
        #       Test 1
        cls.rt_inst_source3 = cls.runtime_layer.lookup('/inst_source3')
        cls.rt_inst_target3 = cls.runtime_layer.lookup('/inst_target3')
        cls.rt_inst_target3_child = cls.runtime_layer.lookup('/inst_target3/RealChild')

    def test_editor_time1(self):
        print("Testing instancing case 2 scenario 1 at EDITOR time...")
        print("Test that the expected number of children exist on the "
              "instance source.")
        children = self.comp_layer.children(self.inst_source3_path)
        self.assertEqual(2, len(children))
        print("Test that the expected number of children exist on the "
              "instance target")
        children = self.comp_layer.children(self.inst_target3_path)
        self.assertEqual(2, len(children))

    def test_runtime_time1(self):
        print("Testing instancing case 2 scenario 1 at RUNTIME time...")
        print("Test that the expected number of children exist on the "
              "instance source.")
        children = self.runtime_layer.children(self.inst_source3_path)
        self.assertEqual(2, len(children))
        print("Test that the expected number of children exist on the "
              "instance target")
        children = self.runtime_layer.children(self.inst_source3_path)
        self.assertEqual(2, len(children))

    def test_editor_add_node_hierarchy(self):
        print("Check that node is proxy")
        parent_path = '/inst_target3'
        new_node_path = '/inst_target3/RealChild'
        new_node = self.comp_layer.lookup(new_node_path)
        self.assertIs(True, getattr(new_node, INTERNAL_ATTRS.PROXY))
        print("Create node hierarchy")
        node_hierarchy = ['inst_target3', 'RealChild']
        top_layer = self.stage.top_layer
        comp_layer = self.comp_layer
        node_table, dirty = self.stage.add_node_hierarchy(node_hierarchy,
                                                          parent=None,
                                                          layer=top_layer)
        self.comp_layer = self.stage.build_stage()
        print("Check that node is NOT proxy")
        new_node = self.comp_layer.lookup('/inst_target3/RealChild')
        self.assertIs(False, getattr(new_node, INTERNAL_ATTRS.PROXY))
        print("Check dirty map")
        self.assertEqual([parent_path, new_node_path], dirty)

    def test_localizing_proxy_child(self):
        print("Check that proxy node dose not get its parent's compute when "
              "localized.")
        parent_path = '/inst_source3'
        node_name = 'inst_source1_child'
        node_path = nxt_path.join_node_paths(parent_path, node_name)
        parent_node = self.stage.top_layer.lookup('/inst_source3')
        self.stage.add_node(node_name, data={}, parent=parent_node,
                            layer=self.stage.top_layer,
                            comp_layer=self.comp_layer, fix_names=False)
        node = self.comp_layer.lookup(node_path)
        inst_src_path = '/inst_target1/inst_source1_child'
        inst_src = self.comp_layer.lookup(inst_src_path)
        expected = getattr(inst_src, INTERNAL_ATTRS.COMPUTE)
        actual = getattr(node, INTERNAL_ATTRS.COMPUTE)
        self.assertEqual(expected, actual)


class StageInstance3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stage = Session().load_file(filepath="./StageInstanceTest_Layer0.nxt")
        cls.comp_layer = cls.stage.build_stage()

    def test_name_clash(self):
        """Test that child nodes with the same name as their parent "
              "instance correctly."""
        print("Test that there are the expected number of descendants (2)")
        children = self.comp_layer.children('/node')
        self.assertEqual(2, len(children))
        children = self.comp_layer.children('/node1')
        self.assertEqual(2, len(children))
        node_descendants = self.comp_layer.descendants('/node')
        node1_descendants = self.comp_layer.descendants('/node1')
        self.assertEqual(2, len(node_descendants))
        self.assertEqual(2, len(node1_descendants))

    def test_2_deep_instances(self):
        """Test that instances of instances have the expected children."""
        d = self.comp_layer.descendants('/leg')
        print("Test that there are the expected number of descendants (7)")
        self.assertEqual(7, len(d))
        upper_node = self.comp_layer.lookup('/leg/create/fk/controls/upper')
        lower_node = self.comp_layer.lookup('/leg/create/fk/controls/lower')
        print("Testing the node `/leg/create/fk/controls/upper` exists.")
        self.assertIsNotNone(upper_node)
        print("Testing the node `/leg/create/fk/controls/lower` exists.")
        self.assertIsNotNone(lower_node)
        upper_create_node = self.comp_layer.lookup('/leg/create/fk/controls/upper/create')
        lower_create_node = self.comp_layer.lookup('/leg/create/fk/controls/lower/create')
        print("Testing the node `/leg/create/fk/controls/upper/create` "
              "exists.")
        self.assertIsNotNone(upper_create_node)
        print("Testing the node `/leg/create/fk/controls/lower/create` "
              "exists.")
        self.assertIsNotNone(lower_create_node)

    def test_3_deep_instances(self):
        """Test instances of instances as well as twin instancing."""
        d = self.comp_layer.descendants('/Character')
        print("Test that there are the expected number of descendants (18)")
        self.assertEqual(18, len(d))
        left_node = self.comp_layer.lookup('/Character/build/legs/left')
        right_node = self.comp_layer.lookup('/Character/build/legs/right')
        print("Testing the node `/Character/build/legs/left` exists.")
        self.assertIsNotNone(left_node)
        print("Testing the node `/Character/build/legs/right` (twin of "
              "`..left`) exists.")
        self.assertIsNotNone(right_node)
        left_control = self.comp_layer.lookup('/Character/build/legs/left/create/fk/controls/upper/create')
        right_control = self.comp_layer.lookup('/Character/build/legs/right/create/fk/controls/upper/create')
        print("Testing the node "
              "`/Character/build/legs/left/create/fk/controls/upper/create` "
              "(3 level deep instance) exists.")
        self.assertIsNotNone(left_control)
        print("Testing the node "
              "`/Character/build/legs/left/create/fk/controls/upper/create` "
              "(3 level deep instance of twin) exists.")
        self.assertIsNotNone(right_control)

    def test_4_deep_instances(self):
        """Test instancing an entire hierarchy that contains 3 level deep
        instances as well as twins."""
        d = self.comp_layer.descendants('/another')
        print("Test that there are the expected number of descendants (18)")
        self.assertEqual(18, len(d))
        left_node = self.comp_layer.lookup('/another/build/legs/left')
        right_node = self.comp_layer.lookup('/another/build/legs/right')
        print("Testing the node `/another./uild/legs/left` (4 level deep "
              "instance) exists.")
        self.assertIsNotNone(left_node)
        print("Testing the node `/another/build/legs/right` (4 level deep "
              "instance) exists.")
        self.assertIsNotNone(right_node)
        left_control = self.comp_layer.lookup('/another/build/legs/left/create/fk/controls/upper/create')
        right_control = self.comp_layer.lookup('/another/build/legs/right/create/fk/controls/upper/create')
        print("Testing the node "
              "`/another/build/legs/right/create/fk/controls/upper/create` ("
              "4 level deep instance) exists.")
        self.assertIsNotNone(left_control)
        print("Testing the node "
              "`/another/build/legs/right/create/fk/controls/upper/create` ("
              "4 level deep instance) exists.")
        self.assertIsNotNone(right_control)

    def test_instance_node_on_layer_above(self):
        """Test that the proper instance nodes are created for a node who's
        instance path can not be resolved on its or any layer below itself."""
        d = self.comp_layer.descendants('/dummy')
        print("Test that there are the expected number of descendants (18)")
        self.assertEqual(18, len(d))
        left_node = self.comp_layer.lookup('/dummy/build/legs/left')
        right_node = self.comp_layer.lookup('/dummy/build/legs/right')
        print("Testing the node `/dummy/build/legs/left` exists.")
        self.assertIsNotNone(left_node)
        print("Testing the node `/dummy/build/legs/right` exists.")
        self.assertIsNotNone(right_node)
        left_control = self.comp_layer.lookup('/dummy/build/legs/left/create/fk/controls/upper/create')
        right_control = self.comp_layer.lookup('/dummy/build/legs/right/create/fk/controls/upper/create')
        print("Testing the node "
              "`/dummy/build/legs/left/create/fk/controls/upper/create` "
              "exists.")
        self.assertIsNotNone(left_control)
        print("Testing the node "
              "`/dummy/build/legs/right/create/fk/controls/upper/create` "
              "exists.")
        self.assertIsNotNone(right_control)

    def test_instance_attr_names(self):
        sibling_inst = self.comp_layer.lookup('/Character/build/legs/right')
        inst_attrs = self.stage.get_node_instanced_attr_names(sibling_inst,
                                                              self.comp_layer)
        expected = ['LOCAL']
        self.assertEqual(expected, inst_attrs)


class StageRuntimeResolveScenarios(unittest.TestCase):

    def test_run_with_no_change(self):
        """Test Stage Runtime Resolve Scenario1"""
        print("Test SetUp StageRuntimeResolveScenario1")
        os.chdir(os.path.dirname(__file__))
        self.stage = Session().load_file(filepath="./StageRuntimeTest1.nxt")
        self.comp_layer = self.stage.build_stage()
        # Lookup all editor nodes
        self.NodeA = self.comp_layer.lookup('/NodeA')
        self.NodeB = self.comp_layer.lookup('/NodeB')
        # Setup the session layer which generates runtime nodes

        print("Testing runtime attr values...")
        print("Starting execute...")
        self.runtime_layer = self.stage.execute('/NodeA')
        # Lookup all the runtime nodes
        self.rt_NodeA = self.runtime_layer.cache_layer.lookup('/NodeA')
        self.rt_NodeB = self.runtime_layer.cache_layer.lookup('/NodeB')
        print("Test that `/NodeA.attr0` is NOT changed by execute.")
        self.assertEqual(self.NodeA.attr0, self.rt_NodeA.attr0)
        print("Test that `/NodeA.attr0` python type IS changed by execute.")
        self.assertNotEqual(self.NodeA.attr1, self.rt_NodeA.attr1)
        print("Test that `/NodeA.attr0` python type change is as expected.")
        self.assertEqual(int(self.NodeA.attr1), self.rt_NodeA.attr1)

    def test_run_with_change_in_code_a(self):
        """Will fail until runtime_patch is merged"""
        print("Test SetUp StageRuntimeResolveScenario2")
        os.chdir(os.path.dirname(__file__))
        self.stage = Session().load_file(filepath="./StageRuntimeTest2.nxt")
        self.comp_layer = self.stage.build_stage()
        # Lookup all editor nodes
        self.NodeA = self.comp_layer.lookup('/NodeA')
        self.NodeB = self.comp_layer.lookup('/NodeB')
        print("Testing runtime attr value mutation by single code block...")
        print("Starting execute...")
        self.runtime_layer = self.stage.execute('/NodeA')
        # Lookup all the runtime nodes again since execute build the session
        # layer again
        self.rt_NodeA = self.runtime_layer.cache_layer.lookup('/NodeA')
        self.rt_NodeB = self.runtime_layer.cache_layer.lookup('/NodeB')
        print("Testing NodeA resolved code code after execute.")
        expected_code = '# printing values before they are changed\n' \
                           'print("side")\n' \
                           'print(5)\n' \
                           'print(self.attr0)\n' \
                           'print(self.attr1)  # notice this value is ' \
                           'the input value!\n' \
                           '\n' \
                           '# changing value from 5 to 10\n' \
                           'self.attr1 = 10\n' \
                           '\n# printing after value change' \
                           '\nprint(self.attr1)  # notice this value change ' \
                           'is a result of runtime\n' \
                           '\n' \
                           '# caveat!  ' \
                           'This is expected behavior - DO NOT modify at ' \
                           'runtime!' \
                           '\n' \
                           'print(5)\n'
        self.assertEqual(expected_code, getattr(self.rt_NodeA, INTERNAL_ATTRS.CACHED_CODE))
        print("Testing NodeA local attributes after execute.")
        self.assertEqual("side", getattr(self.rt_NodeA, 'attr0'))
        self.assertEqual(10, getattr(self.rt_NodeA, 'attr1'))

        print("Testing NodeB resolved code code after execute.")
        expected_code = '# just printing values for now\n' \
                           'print(10)  # this is the correct answer ' \
                           'currently! NodeA hasn\'t run yet!\n' \
                           'print(self.attr2)\n' \
                           '\n' \
                           '# also printing remote attrs for fun!\n' \
                           'print("side")\n' \
                           'print(10)  # this is the correct answer too!'
        self.assertEqual(expected_code, getattr(self.rt_NodeB, INTERNAL_ATTRS.CACHED_CODE))
        print("Testing NodeB local attributes after execute.")
        self.assertEqual(10, getattr(self.rt_NodeB, 'attr2'))

    def test_runtime_prop(self):
        os.chdir(os.path.dirname(__file__))
        stage = Session().load_file(filepath="RuntimeProp.nxt")
        runtime_layer = stage.execute('/inst_src')
        # Check target node, who we expect to have inherited
        # changed values from source node.
        cached_tgt = runtime_layer.cache_layer.lookup('/inst_tgt')
        expected_refer = "\'new\'"
        cached_refer = cached_tgt.refer
        self.assertEqual(expected_refer, cached_refer)
        expected_list = ['old', 'me_first', 'again', 'again']
        cached_list = cached_tgt.list
        self.assertEqual(expected_list, cached_list)
        expected_deep = [[1, 2], ['old']]
        cached_deep = cached_tgt.deep
        self.assertEqual(expected_deep, cached_deep)
        expected_changer = 'me_second'
        cached_changer = cached_tgt.changer
        self.assertEqual(expected_changer, cached_changer)
        expected_changed = 'second'
        cached_changed = cached_tgt.changed
        self.assertEqual(expected_changed, cached_changed)

    def test_future_tokens(self):
        os.chdir(os.path.dirname(__file__))
        # This graph has asserts, if it errors this test fails.
        Session().execute_graph("future_tokens_test.nxt")


class StageChildOrder(unittest.TestCase):
    """Unit test relies on the following save files:
    ./StageChildOrderTest_TopLayer.nxt
    ./StageChildOrderTest.nxt"""

    def setUp(self):
        """Opens ./StageChildOrderTest_TopLayer.nxt which has the sub-layer
        ./StageChildOrderTest.nxt"""
        os.chdir(os.path.dirname(__file__))
        self.stage = Session().load_file(filepath="./StageChildOrderTest_TopLayer.nxt")
        self.tgt_layer = self.stage._sub_layers[0]
        self.lower_tgt_layer = self.stage._sub_layers[1]
        self.comp_layer = self.stage.build_stage()
        self.inst_tgt_path = '/InstanceTarget'
        self.parent_path = '/ParentNode'
        self.lower_parent_path = '/LowerParent'
        self.tgt_path = '/tgt'
        self.parent_node = self.comp_layer.lookup(self.parent_path)
        self.instance_target_node = self.comp_layer.lookup(self.inst_tgt_path)
        self.lower_parent_node = self.comp_layer.lookup(self.lower_parent_path)

    def test_get_child_order(self):
        """Test getting a node's child order via a get attr and the stages
        method"""
        expected_child_order = ['node0', 'node1', 'node2']
        print("Testing get child order on a real node with the same namespace "
              "as a lower layer node. "
              "Expected child order: {}".format(expected_child_order))
        actual_child_order = getattr(self.parent_node,
                                     INTERNAL_ATTRS.CHILD_ORDER)
        self.assertEqual(expected_child_order, actual_child_order)
        self.assertEqual(expected_child_order,
                         self.stage.get_node_child_order(self.parent_node))
        expected_child_order = ['Child0', 'Child1']
        print("Testing get child order on an instance source node. "
              "Expected child order: {}".format(expected_child_order))
        actual_child_order = getattr(self.lower_parent_node,
                                     INTERNAL_ATTRS.CHILD_ORDER)
        self.assertEqual(expected_child_order, actual_child_order)
        self.assertEqual(expected_child_order,
                         self.stage.get_node_child_order(
                             self.lower_parent_node))
        expected_child_order = ['Child2', 'Child0', 'Child1']
        print("Testing get child order on an instance target node. "
              "Expected child order: {}".format(expected_child_order))
        actual_child_order = getattr(self.instance_target_node,
                                     INTERNAL_ATTRS.CHILD_ORDER)
        self.assertEqual(expected_child_order, actual_child_order)
        self.assertEqual(expected_child_order,
                         self.stage.get_node_child_order(
                             self.instance_target_node))
        children = self.comp_layer.children(self.inst_tgt_path, ordered=True)
        children_names = [getattr(n, INTERNAL_ATTRS.NAME) for n in children]
        expected_children_names = ['Child2', 'Child0', 'Child1']
        print("Testing children names. "
              "Expected children: {}".format(expected_children_names))
        self.assertEqual(expected_children_names, children_names)

    def test_set_child_order_basic(self):
        """Test setting a node's child order via stage's method. Validated
        via a getattr and the stage's method"""
        expected_child_order = ['node1', 'node2', 'node0']
        print("Testing set child order on a real node with the same namespace "
              "as a lower layer node. "
              "Expected child order: {}".format(expected_child_order))
        parent_node = self.tgt_layer.lookup(self.parent_path)
        self.stage.set_node_child_order(parent_node,
                                        expected_child_order, self.tgt_layer)
        # Rebuild stage and look up nodes
        self.comp_layer = self.stage.build_stage()
        self.parent_node = self.comp_layer.lookup(self.parent_path)
        self.instance_target_node = self.comp_layer.lookup(self.inst_tgt_path)
        self.lower_parent_node = self.comp_layer.lookup(self.lower_parent_path)
        # Test child order
        actual_child_order = getattr(self.parent_node,
                                     INTERNAL_ATTRS.CHILD_ORDER)
        self.assertEqual(expected_child_order, actual_child_order)
        self.assertEqual(expected_child_order,
                         self.stage.get_node_child_order(self.parent_node))
        expected_child_order = ['Child1', 'Child0']
        print("Testing set child order on an instance source node. "
              "Expected child order: {}".format(expected_child_order))
        lower_parent_node = self.lower_tgt_layer.lookup(self.lower_parent_path)
        self.stage.set_node_child_order(lower_parent_node,
                                        expected_child_order,
                                        self.lower_tgt_layer)
        # Rebuild stage and look up nodes
        self.comp_layer = self.stage.build_stage()
        self.parent_node = self.comp_layer.lookup(self.parent_path)
        self.instance_target_node = self.comp_layer.lookup(self.inst_tgt_path)
        self.lower_parent_node = self.comp_layer.lookup(self.lower_parent_path)
        actual_child_order = getattr(self.lower_parent_node,
                                     INTERNAL_ATTRS.CHILD_ORDER)
        self.assertEqual(expected_child_order, actual_child_order)
        self.assertEqual(expected_child_order,
                         self.stage.get_node_child_order(self.lower_parent_node))

    def test_set_child_order_with_propagate(self):
        """Tests that child order is properly propagated through instances."""
        expected_child_order = ['Child1', 'Child0']
        lower_parent_node = self.lower_tgt_layer.lookup(self.lower_parent_path)
        self.stage.set_node_child_order(lower_parent_node,
                                        expected_child_order,
                                        self.lower_tgt_layer, self.comp_layer)
        # Rebuild stage and look up nodes
        self.comp_layer = self.stage.build_stage()
        self.parent_node = self.comp_layer.lookup(self.parent_path)
        self.instance_target_node = self.comp_layer.lookup(self.inst_tgt_path)
        self.lower_parent_node = self.comp_layer.lookup(self.lower_parent_path)
        # Test child order
        actual_child_order = getattr(self.lower_parent_node,
                                     INTERNAL_ATTRS.CHILD_ORDER)
        self.assertEqual(expected_child_order, actual_child_order)
        self.assertEqual(expected_child_order,
                         self.stage.get_node_child_order(
                             self.lower_parent_node))
        expected_child_order = ['Child2', 'Child1', 'Child0']
        print("Testing set child order propagation. "
              "Expected child order: {}".format(expected_child_order))
        actual_child_order = getattr(self.instance_target_node,
                                     INTERNAL_ATTRS.CHILD_ORDER)
        self.assertEqual(expected_child_order, actual_child_order)
        self.assertEqual(expected_child_order,
                         self.stage.get_node_child_order(
                             self.instance_target_node))

    def test_child_order_with_add_node(self):
        expected_child_order = ['Child1', 'Child2', 'Child3']
        print("Testing localizing a node does not break child order. "
              "Expected child order: {}".format(expected_child_order))
        tgt_node = self.comp_layer.lookup(self.tgt_path)
        tgt_node_spec = self.tgt_layer.lookup(self.tgt_path)
        self.assertEqual(expected_child_order,
                         getattr(tgt_node, INTERNAL_ATTRS.CHILD_ORDER))
        # Localize child 1
        self.stage.add_node(name='Child1', data=None, parent=tgt_node_spec,
                            layer=self.tgt_layer, fix_names=False,
                            comp_layer=self.comp_layer)
        self.assertEqual(expected_child_order,
                         getattr(tgt_node, INTERNAL_ATTRS.CHILD_ORDER))
        self.stage.delete_node(self.tgt_layer.lookup(self.tgt_path + '/Child1'),
                               self.tgt_layer, self.comp_layer)
        self.assertEqual(expected_child_order,
                         getattr(tgt_node, INTERNAL_ATTRS.CHILD_ORDER))
        # Localize child 2
        self.stage.add_node(name='Child2', data=None, parent=tgt_node_spec,
                            layer=self.tgt_layer, fix_names=False,
                            comp_layer=self.comp_layer)
        self.assertEqual(expected_child_order,
                         getattr(tgt_node, INTERNAL_ATTRS.CHILD_ORDER))
        self.stage.delete_node(self.tgt_layer.lookup(self.tgt_path+'/Child2'),
                               self.tgt_layer, self.comp_layer)
        self.assertEqual(expected_child_order,
                         getattr(tgt_node, INTERNAL_ATTRS.CHILD_ORDER))
        # Localize child 3
        self.stage.add_node(name='Child3', data=None, parent=tgt_node_spec,
                            layer=self.tgt_layer, fix_names=False,
                            comp_layer=self.comp_layer)
        self.assertEqual(expected_child_order,
                         getattr(tgt_node, INTERNAL_ATTRS.CHILD_ORDER))
        self.stage.delete_node(self.tgt_layer.lookup(self.tgt_path + '/Child3'),
                               self.tgt_layer, self.comp_layer)
        self.assertEqual(expected_child_order,
                         getattr(tgt_node, INTERNAL_ATTRS.CHILD_ORDER))
        # New node
        expected_child_order = expected_child_order + ['Bob']
        print("Testing a new node goes to the top. "
              "Expected child order: {}".format(expected_child_order))
        self.stage.add_node(name='Bob', data=None, parent=tgt_node_spec,
                            layer=self.tgt_layer, fix_names=False,
                            comp_layer=self.comp_layer)
        self.assertEqual(expected_child_order,
                         getattr(tgt_node, INTERNAL_ATTRS.CHILD_ORDER))
        self.stage.delete_node(self.tgt_layer.lookup(self.tgt_path + '/Bob'),
                               self.tgt_layer, self.comp_layer)

    def test_child_order_merger(self):
        print("Test that the child order merger works in edge cases.")
        src = ['node2', 'node']
        tgt = ['node1', 'node2']
        expected = ['node1', 'node2', 'node']
        print("Test that merging {} <-> {} becomes {}".format(src, tgt,
                                                              expected))
        result = nxt_node.list_merger(src, tgt)
        self.assertEqual(expected, result)


class StageAddNode(unittest.TestCase):
    def test_basic_name_collision(self):
        """Verify when adding nodes without specific names to a layer they
        will not collide."""
        test_stage = stage.Stage()
        node_count = 3
        for _ in range(node_count):
            test_stage.add_node()
        comp_layer = test_stage.build_stage()
        all_names = [getattr(c, INTERNAL_ATTRS.NAME) for c in
                     comp_layer.children()]
        all_names = set(all_names)
        self.assertEqual(node_count, len(all_names))

    def test_upper_respects_lower(self):
        """Verify that when an add node command is given targeting an upper layer,
        an override of a lower layer will not be created.
        NOTE: this test depends on the test graphs `UpperLowerRespect.nxt` and
        `LowerRespect.nxt`."""
        os.chdir(os.path.dirname(__file__))
        test_stage = Session().load_file(filepath='UpperLowerRespect.nxt')
        # "lower" is the name of a node present in "LowerRespect.nxt" which
        # is referenced into "UpperRespect.nxt".
        test_stage.add_node('lower', layer=0)
        comp_layer = test_stage.build_stage()
        # There is exactly 1 node in Lower, and 0 in upper. If the above add
        # worked as expected, we should have 2.
        self.assertEqual(2, len(comp_layer.children()))


class StageRuntimeScope(unittest.TestCase):
    def setUp(self):
        os.chdir(os.path.dirname(__file__))
        self.stage = Session().load_file(filepath='./StageRuntimeScope.nxt')

    def test_global_scope(self):
        """Test executes a node that sets "math" as a global and imports math.
        Next another node tries to access the global "math" by running
        math.floor(1.5)"""
        print("Testing that globals are accessible by down stream nodes.")
        comp = self.stage.build_stage()
        runtime_layer = self.stage.execute_nodes(['/setup', '/g'], comp)
        global_node = runtime_layer.lookup('/g')
        self.assertEqual(1.0, global_node.result)

    def test_lambda_scope(self):
        """Executes a node that tests a lambda that used to fail for Zach."""
        print("Testing lambda function that used to fail for Zach.")
        runtime_layer = self.stage.execute(start='/setup')
        lambda_node = runtime_layer.lookup('/lam')
        self.assertEqual('l', lambda_node.result)


class StageNamespaceMerger(unittest.TestCase):
    """Based on real world test cases we test the the namespace merger does
    what is expected."""
    def test_namespace_case01(self):
        source = ['Character', 'build', 'legs', 'left']
        target = ['dummy', 'build', 'legs']
        expected = ['dummy', 'build', 'legs', 'left']
        print("Source: {0}\nTarget: {1}\nExpected: {2}".format(source,
                                                                target,
                                                                expected))
        inst_ns = stage.Stage.namespace_merger(source, target)
        self.assertEqual(expected, inst_ns)

    def test_namespace_case02(self):
        source = ['Character']
        target = ['dummy']
        expected = ['dummy']
        print("Source: {0}\nTarget: {1}\nExpected: {2}".format(source,
                                                                target,
                                                                expected))
        inst_ns = stage.Stage.namespace_merger(source, target)
        self.assertEqual(expected, inst_ns)

    def test_namespace_case03(self):
        source = ['Character', 'build', 'legs', 'left']
        target = ['dummy', 'build', 'legs', 'jack']
        expected = ['dummy', 'build', 'legs', 'left']
        print("Source: {0}\nTarget: {1}\nExpected: {2}".format(source,
                                                                target,
                                                                expected))
        inst_ns = stage.Stage.namespace_merger(source, target)
        self.assertEqual(expected, inst_ns)

    def test_namespace_case04(self):
        source = ['Character', 'build', 'legs', 'left']
        target = ['Character', 'build', 'legs', 'right']
        expected = ['Character', 'build', 'legs', 'left']
        print("Source: {0}\nTarget: {1}\nExpected: {2}".format(source,
                                                                target,
                                                                expected))
        inst_ns = stage.Stage.namespace_merger(source, target)
        self.assertEqual(expected, inst_ns)

    def test_namespace_case05(self):
        source = ['Character', 'build']
        target = ['dummy']
        expected = ['dummy', 'build']
        print("Source: {0}\nTarget: {1}\nExpected: {2}".format(source,
                                                                target,
                                                                expected))
        inst_ns = stage.Stage.namespace_merger(source, target)
        self.assertEqual(expected, inst_ns)

    def test_namespace_case06(self):
        source = ['control', 'create']
        target = ['leg', 'create', 'fk', 'controls', 'upper']
        expected = ['leg', 'create', 'fk', 'controls', 'upper', 'create']
        print("Source: {0}\nTarget: {1}\nExpected: {2}".format(source,
                                                                target,
                                                                expected))
        inst_ns = stage.Stage.namespace_merger(source, target)
        self.assertEqual(expected, inst_ns)

    def test_namespace_case07(self):
        source = ['leg', 'create', 'fk', 'controls']
        target = ['Character', 'build', 'legs', 'left', 'create', 'create',
                  'fk']
        expected = ['Character', 'build', 'legs', 'left', 'create',
                          'create', 'fk', 'controls']
        print("Source: {0}\nTarget: {1}\nExpected: {2}".format(source,
                                                                target,
                                                                expected))
        inst_ns = stage.Stage.namespace_merger(source, target)
        self.assertEqual(expected, inst_ns)

    def test_namespace_case08(self):
        source = ['Character', 'build', 'legs']
        target = ['dummy', 'build']
        expected = ['dummy', 'build', 'legs']
        print("Source: {0}\nTarget: {1}\nExpected: {2}".format(source,
                                                                target,
                                                                expected))
        inst_ns = stage.Stage.namespace_merger(source, target)
        self.assertEqual(expected, inst_ns)

    def test_namespace_case09(self):
        source = ['Character', 'build', 'legs', 'left', 'create']
        target = ['Character', 'build', 'legs', 'right']
        expected = ['Character', 'build', 'legs', 'right', 'create']
        print("Source: {0}\nTarget: {1}\nExpected: {2}".format(source,
                                                                target,
                                                                expected))
        inst_ns = stage.Stage.namespace_merger(source, target)
        self.assertEqual(expected, inst_ns)

    def test_namespace_case10(self):
        source = ['limb', 'create', 'fk']
        target = ['arm', 'limb', 'create']
        expected = ['arm', 'limb', 'create', 'fk']
        print("Source: {0}\nTarget: {1}\nExpected: {2}".format(source,
                                                                target,
                                                                expected))
        inst_ns = stage.Stage.namespace_merger(source, target)
        self.assertEqual(expected, inst_ns)

    def test_namespace_case11(self):
        source = ['spline', 'controls', 'hips']
        target = ['center', 'spine', 'controls']
        expected = ['center', 'spine', 'controls', 'hips']
        print("Source: {0}\nTarget: {1}\nExpected: {2}".format(source,
                                                                target,
                                                                expected))
        inst_ns = stage.Stage.namespace_merger(source, target)
        self.assertEqual(expected, inst_ns)

    def test_namespace_case12(self):
        source = ['arm', 'limb']
        target = ['left', 'arm']
        expected = ['left', 'arm', 'limb']
        print("Source: {0}\nTarget: {1}\nExpected: {2}".format(source,
                                                                target,
                                                                expected))
        inst_ns = stage.Stage.namespace_merger(source, target)
        self.assertEqual(expected, inst_ns)

    def test_namespace_case13(self):
        source = ['arm', 'clavicle', 'control']
        target = ['leg', 'pelvis']
        expected = ['leg', 'pelvis', 'control']
        print("Source: {0}\nTarget: {1}\nExpected: {2}".format(source,
                                                                target,
                                                                expected))
        inst_ns = stage.Stage.namespace_merger(source, target)
        self.assertEqual(expected, inst_ns)

    def test_namespace_case14(self):
        source = ['spine', 'node1']
        target = ['center', 'spine']
        expected = ['center', 'spine', 'node1']
        print("Source: {0}\nTarget: {1}\nExpected: {2}".format(source,
                                                                target,
                                                                expected))
        inst_ns = stage.Stage.namespace_merger(source, target)
        self.assertEqual(expected, inst_ns)


class TestExecOrder(unittest.TestCase):
    def setUp(self):
        os.chdir(os.path.dirname(__file__))
        self.stage = Session().load_file(filepath='order.nxt')
        self.comp_layer = self.stage.build_stage()

    def test_roots_order(self):
        expected = ['/one', '/seven', '/twelve']
        found = self.comp_layer.get_root_exec_order('/one')
        self.assertEqual(expected, found)

        expected = ['/seven', '/twelve']
        found = self.comp_layer.get_root_exec_order('/seven')
        self.assertEqual(expected, found)

    def test_full_order(self):
        expected = ['/one', '/one/two', '/one/three', '/one/three/four',
                    '/one/three/five', '/one/six', '/seven', '/seven/eight',
                    '/seven/eight/nine', '/seven/eight/nine/ten',
                    '/seven/eight/eleven', '/twelve']
        found = self.comp_layer.get_exec_order('/one')
        self.assertEqual(expected, found)

        expected = ['/one/three/five', '/one/six', '/seven', '/seven/eight',
                    '/seven/eight/nine', '/seven/eight/nine/ten',
                    '/seven/eight/eleven', '/twelve']
        found = self.comp_layer.get_exec_order('/one/three/five')
        self.assertEqual(expected, found)

    def test_with_disabled(self):
        found = self.comp_layer.get_exec_order('/a')
        expected = ['/a', '/a/b', '/c']
        self.assertEqual(expected, found)


if __name__ == '__main__':
    unittest.main()
