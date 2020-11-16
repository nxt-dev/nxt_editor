# Built-in
import unittest
import os

# Internal
from nxt import stage, DATA_STATE, tokens
from nxt.session import Session


class TestPathTokens(unittest.TestCase):
    def test_no_change_full_path(self):
        """Give a full path and verify that it is not mangled by resolution.
        """
        test_attr = 'no_change'
        in_val = '${path::' + __file__ + '}'
        expected = __file__.replace(os.path.sep, '/')
        test_stage = stage.Stage()
        test_node, _ = test_stage.add_node(layer=0)
        test_node = test_node[0]
        test_stage.add_node_attr(test_node, test_attr, {'value': in_val},
                                 test_stage.top_layer)
        result = test_stage.get_node_attr_value(test_node, test_attr,
                                                test_stage.top_layer)
        self.assertEqual(expected, result)

    def test_sibling_path(self):
        """Test that resolution of a filename only returns a file next to it.

        NOTE: this test depends on the test folder structure. It is using a
        test graph `TokenSiblingTest.nxt` that must be a direct sibling
        to this test file. The contents of that file are also depended on.
        If you find one of these files without the other, something is wrong.
        """
        base_path = __file__.replace(os.path.sep, '/')
        if base_path.endswith('.pyc'):
            base_path = base_path[:-1]
        base_name = os.path.basename(base_path)
        in_val = '${file::' + base_name + '}'
        expected = base_path
        test_attr = 'my_file'
        my_dir = os.path.dirname(base_path)
        os.chdir(my_dir)
        test_stage = Session().load_file(filepath='TokenSiblingTest.nxt')
        comp_layer = test_stage.build_stage()
        test_node = test_stage.top_layer.lookup('/tester')
        test_stage.add_node_attr(test_node, test_attr, {'value': in_val},
                                 test_stage.top_layer)
        result = test_stage.get_node_attr_value(test_node, test_attr,
                                                comp_layer)
        self.assertEqual(expected, result)

    def test_file_token(self):
        base_path = __file__.replace(os.path.sep, '/')
        if base_path.endswith('.pyc'):
            base_path = base_path[:-1]
        my_dir = os.path.dirname(base_path)
        os.chdir(my_dir)
        test_stage = Session().load_file(filepath='FileTokenSub.nxt')
        comp_layer = test_stage.build_stage()
        fake_path = os.path.join(my_dir, 'notafile.txt')
        fake_path = fake_path.replace(os.path.sep, '/')
        real_path = os.path.join(my_dir, 'real_file.txt')
        real_path = real_path.replace(os.path.sep, '/')
        test_node = test_stage.top_layer.lookup('/tokens')
        file_fake = test_stage.get_node_attr_value(test_node, 'file_fake',
                                                   comp_layer,
                                                   resolved=True)
        self.assertEqual('', file_fake)
        file_real = test_stage.get_node_attr_value(test_node, 'file_real',
                                                   comp_layer,
                                                   resolved=True)
        self.assertEqual(real_path, file_real)
        path_fake = test_stage.get_node_attr_value(test_node, 'path_fake',
                                                   comp_layer,
                                                   resolved=True)
        self.assertEqual(fake_path, path_fake)
        path_real = test_stage.get_node_attr_value(test_node, 'path_real',
                                                   test_stage.top_layer,
                                                   resolved=True)
        self.assertEqual(real_path, path_real)

    def test_contents_token(self):
        base_path = __file__.replace(os.path.sep, '/')
        if base_path.endswith('.pyc'):
            base_path = base_path[:-1]
        my_dir = os.path.dirname(base_path)
        os.chdir(my_dir)
        test_stage = Session().load_file(filepath='FileTokenSub.nxt')
        with open('real_file.txt', 'r') as fp:
            expected_code = fp.read()
        top = test_stage.top_layer
        node = top.lookup('/tokens')
        resolved = DATA_STATE.RESOLVED
        found_code = test_stage.get_node_code_string(node=node,
                                                           layer=top,
                                                           data_state=resolved)
        self.assertEqual(expected_code, found_code)


class TestAttrRefTokens(unittest.TestCase):
    def test_attr_ref_building(self):
        test_in_exp = {
            'stuff.thing': '${stuff.thing}',
            'all/other/stuff.another': '${all/other/stuff.another}'
        }
        for inp, exp in test_in_exp.items():
            result = tokens.make_token_str(inp)
            self.assertEqual(exp, result)
