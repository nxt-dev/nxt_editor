# Builtin
import unittest
import logging
import os
import sys

# External
from Qt import QtWidgets

# Internal
from nxt import nxt_path
from nxt_editor import stage_model
from nxt.session import Session

path_logger = logging.getLogger(nxt_path.__name__)
path_logger.propagate = False

app = QtWidgets.QApplication(sys.argv)


class NodeLocalAndInheritAttributes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.chdir(os.path.dirname(__file__))
        cls.stage = Session().load_file(filepath="StageInheritTest.nxt")
        cls.model = stage_model.StageModel(cls.stage)
        cls.comp_layer = cls.model.comp_layer

    def test_local_node_attrs(self):
        expected_attrs = ['parent']
        node_path = '/parent_node'
        print("Testing that `{}` has a LOCAL attr".format(node_path))
        local_attrs = self.model.get_node_local_attr_names(node_path)
        self.assertEqual(expected_attrs, local_attrs)

    def test_inherit_node_attrs(self):
        expected_attrs = ['parent']
        node_path = '/parent_node/child_node'
        print("Testing that `{}` has a INHERITED attr".format(node_path))
        inherited_attr = self.model.get_node_inherited_attr_names(node_path)
        self.assertEqual(expected_attrs, inherited_attr)


class NodeInstanceAttributes(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.chdir(os.path.dirname(__file__))
        fp = "StageInstanceAcrossLayersTest.nxt"
        cls.stage = Session().load_file(filepath=fp)
        cls.model = stage_model.StageModel(cls.stage)
        cls.comp_layer = cls.model.comp_layer

    def test_instance_node_attrs(self):
        expected_attrs = ['attr0']
        node_path = '/inst_source2_middle'
        print("Testing that `{}` has an INSTANCED attr".format(node_path))
        inst_attrs = self.model.get_node_instanced_attr_names(node_path)
        self.assertEqual(expected_attrs, inst_attrs)
        inherited_attrs = self.model.get_node_inherited_attr_names(node_path)
        self.assertNotEqual(expected_attrs, inherited_attrs)
        local_attrs = self.model.get_node_local_attr_names(node_path)
        self.assertNotEqual(expected_attrs, local_attrs)
        child_expected_local = ['attr1_1']
        child_expected_inherit = ['attr1']
        child_expected_inst = ['attr0']
        child_path = '/inst_source2_middle/inst_source2_middle_child'
        print("Testing that `{}` has instance, inherited, and local "
              "attrs".format(child_path))
        child_locals = self.model.get_node_local_attr_names(child_path,
                                                            self.comp_layer)
        child_inherit = self.model.get_node_inherited_attr_names(child_path)
        child_inst = self.model.get_node_instanced_attr_names(child_path)
        self.assertEqual(child_expected_local, child_locals)
        self.assertEqual(child_expected_inherit, child_inherit)
        self.assertEqual(child_expected_inst, child_inst)


class ExecOrderCycle(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.chdir(os.path.dirname(__file__))
        cls.stage = Session().load_file(filepath="StageInstanceTest.nxt")
        cls.model = stage_model.StageModel(cls.stage)
        cls.comp_layer = cls.model.comp_layer

    def test_local_node_attrs(self):
        node_path1 = '/inst_source4'
        node_path2 = '/inst_target4'
        print("Testing that {} has no exec in set".format(node_path1))
        node1_exec_in = self.model.get_node_exec_in(node_path1)
        self.assertIsNone(node1_exec_in)
        print("Testing that {} can't have its exec in set to {}".format(node_path1, node_path2))
        self.model.set_node_exec_in(node_path1, node_path2)
        node1_exec_in = self.model.get_node_exec_in(node_path1)
        self.assertIsNone(node1_exec_in)
