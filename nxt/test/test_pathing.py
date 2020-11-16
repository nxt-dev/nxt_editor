# Built-in
import unittest
import sys
import os

# Internal
from nxt import nxt_path
from nxt.nxt_node import INTERNAL_ATTRS
from nxt.session import Session


class TestExpansion(unittest.TestCase):
    def test_vars_only(self):
        platform_tests = {
            'linux': "$zoom/$all/$around",
            'win32': "%zoom%/%all%/%around%"
        }
        platform_tests['linux2'] = platform_tests['linux']
        platform_tests['darwin'] = platform_tests['linux']
        win_expected = os.path.join(os.getcwd(), "come\\back\\down")
        win_expected = win_expected.replace(os.path.sep, '/')
        platform_expected = {
            'linux': os.path.join(os.getcwd(), "come/back/down"),
            'win32': win_expected
        }
        platform_expected['linux2'] = platform_expected['linux']
        platform_expected['darwin'] = platform_expected['linux']
        env_vars = {
            'zoom': 'come',
            'all': 'back',
            'around': 'down'
        }
        os.environ.update(env_vars)
        result = nxt_path.full_file_expand(platform_tests[sys.platform])
        self.assertEqual(result, platform_expected[sys.platform])

    def test_cross_platform_expansion(self):
        tests = [
            '~/%FOO%/$BAR/%BAZ%',
            '~/$FOO/%BAR%/$BAZ'
        ]
        os.environ['FOO'] = 'FIRST'
        os.environ['BAR'] = 'SECOND'
        os.environ['BAZ'] = 'THIRD'
        expected = os.path.expanduser('~/FIRST/SECOND/THIRD').replace(os.sep,
                                                                      '/')
        for test_str in tests:
            result = nxt_path.full_file_expand(test_str)
            self.assertEqual(expected, result)



class TestNodePathing(unittest.TestCase):
    def test_path_partition(self):
        test_in_exp = {
            'stuff.thing': ('stuff', 'thing'),
            'all/other/stuff.another': ('all/other/stuff', 'another'),
            '/stuff/and/things': ('/stuff/and/things', None)
        }
        for inp, exp in test_in_exp.items():
            result = nxt_path.path_attr_partition(inp)
            self.assertEqual(exp, result)

    def test_namespace_build(self):
        test_in_exp = {
            'stuff.thing': ['stuff'],
            'all/other/stuff.another': ['all', 'other', 'stuff'],
            '/stuff/and/things': ['stuff', 'and', 'things']
        }
        for inp, exp in test_in_exp.items():
            result = nxt_path.str_path_to_node_namespace(inp)
            self.assertEqual(exp, result)

    def test_path_build(self):
        test_exp_in = {
            '/stuff': ['stuff'],
            '/all/other/stuff': ['all', 'other', 'stuff'],
            '/stuff/and/things': ['stuff', 'and', 'things']
        }
        for exp, inp in test_exp_in.items():
            result = nxt_path.node_namespace_to_str_path(inp)
            self.assertEqual(exp, result)

    def test_partition_helpers(self):
        test_in_exp = {
            'stuff.thing': 'stuff',
            'all/other/stuff.another': 'all/other/stuff',
            '/stuff/and/things': '/stuff/and/things'
        }
        for inp, exp in test_in_exp.items():
            result = nxt_path.node_path_from_attr_path(inp)
            self.assertEqual(exp, result)
        test_in_exp = {
            'stuff.thing': 'thing',
            'all/other/stuff.another': 'another',
            '/stuff/and/things': None
        }
        for inp, exp in test_in_exp.items():
            result = nxt_path.attr_name_from_attr_path(inp)
            self.assertEqual(exp, result)
        test_in_exp = {
            'all/other/stuff': 'stuff',
            '/stuff/and/things': 'things'
        }
        for inp, exp in test_in_exp.items():
            result = nxt_path.node_name_from_node_path(inp)
            self.assertEqual(exp, result)
        test_in_exp = {
            'all/other/stuff': 'all/other',
            '/stuff/and/things': '/stuff/and'
        }
        for inp, exp in test_in_exp.items():
            result = nxt_path.get_parent_path(inp)
            self.assertEqual(exp, result)
        test_in_exp = {
            '/all/other/stuff': '/all',
            '/stuff/and/things': '/stuff'
        }
        for inp, exp in test_in_exp.items():
            result = nxt_path.get_root_path(inp)
            self.assertEqual(exp, result)

    def test_make_attr_path(self):
        test_exp_in = {
            'stuff.thing': ('stuff', 'thing'),
            'all/other/stuff.another': ('all/other/stuff', 'another')
        }
        for exp, inp in test_exp_in.items():
            result = nxt_path.make_attr_path(inp[0], inp[1])
            self.assertEqual(exp, result)

    def test_relative_node_paths(self):
        os.chdir(os.path.dirname(__file__))
        test_stage = Session().load_file(filepath='RelPathRef.nxt')
        comp_layer = test_stage.build_stage()
        child_1_path = '/parent/child1'
        child_1 = test_stage.top_layer.lookup(child_1_path)

        test_in_exp = {
            'grandchild1': '/parent/child1/grandchild1',
            '..': '/parent',
            '../child2': '/parent/child2',
            'grandchild1/../../child2': '/parent/child2',
            './././././grandchild1/./././././.': '/parent/child1/grandchild1'
        }
        for inp, exp in test_in_exp.items():
            result = nxt_path.expand_relative_node_path(inp, child_1_path)
            self.assertEqual(exp, result)
        print("Test that a relative node path works as an instance path")
        inst_target = comp_layer.lookup('/parent/inst_target')
        inst_path = getattr(inst_target, INTERNAL_ATTRS.INSTANCE_PATH)
        inst_source_node = comp_layer.lookup(inst_path)
        self.assertIsNotNone(inst_source_node)

    def test_depth_trimming(self):
        inp = '/keep/it/stupid/simple'
        exp = '/'
        result = nxt_path.trim_to_depth(inp, 0)
        self.assertEqual(exp, result)
        exp = '/keep'
        result = nxt_path.trim_to_depth(inp, 1)
        self.assertEqual(exp, result)
        exp = '/keep/it/stupid'
        result = nxt_path.trim_to_depth(inp, 3)
        self.assertEqual(exp, result)
        exp = '/keep/it/stupid/simple'
        result = nxt_path.trim_to_depth(inp, 4)
        self.assertEqual(exp, result)
        exp = '/keep/it/stupid/simple'
        result = nxt_path.trim_to_depth(inp, 7)
        self.assertEqual(exp, result)
