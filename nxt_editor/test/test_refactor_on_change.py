"""What points at an attr or a node keeps pointing at it when it changes.

Renaming an attr renames the tokens that use it, and parenting a node
moves the instance paths that point at it, both undoably and both able to
be turned off in Options.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

# External
from Qt import QtWidgets

# Internal
from nxt.session import Session
from nxt import DATA_STATE
from nxt_editor import stage_model, user_dir

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def prefs_with(key, value):
    real = user_dir.user_prefs.get

    def get(name, default=None):
        if name == key:
            return value
        return real(name, default)
    return mock.patch.object(user_dir.user_prefs, 'get', side_effect=get)


class RefactorTestCase(unittest.TestCase):

    NODES = {}

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='nxt_refactor_')
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.top = os.path.join(self.folder, 'top.nxt')
        with open(self.top, 'w') as f:
            json.dump({'version': '1.17', 'alias': 'top',
                       'nodes': self.NODES}, f)
        self.model = stage_model.StageModel(
            Session().load_file(filepath=self.top))

    def attr(self, path, name):
        return self.model.get_node_attr_value(
            path, name, layer=self.model.target_layer,
            data_state=DATA_STATE.RAW)

    def code(self, path):
        return self.model.get_node_code_string(
            path, layer=self.model.target_layer)

    def undo(self):
        self.model.undo_stack.undo()

    def redo(self):
        self.model.undo_stack.redo()


class RenameUpdatesTokens(RefactorTestCase):

    NODES = {
        '/a': {'attrs': {'x': {'value': '1'},
                         'y': {'value': '${x}'}}},
        '/b': {'attrs': {'z': {'value': '${/a.x}'},
                         'x': {'value': '2'},
                         'w': {'value': '${x}'}},
               'code': ['print(${/a.x})']},
    }

    def test_the_tokens_follow_the_rename(self):
        self.model.rename_node_attr('/a', 'x', 'size')
        self.assertEqual('${size}', self.attr('/a', 'y'))
        self.assertEqual('${/a.size}', self.attr('/b', 'z'))
        self.assertEqual('print(${/a.size})', self.code('/b'))
        # /b's own x is another attr of the same name.
        self.assertEqual('${x}', self.attr('/b', 'w'))

    def test_undo_puts_them_back(self):
        self.model.rename_node_attr('/a', 'x', 'size')
        self.undo()
        self.assertEqual('1', self.attr('/a', 'x'))
        self.assertEqual('${x}', self.attr('/a', 'y'))
        self.assertEqual('${/a.x}', self.attr('/b', 'z'))
        self.assertEqual('print(${/a.x})', self.code('/b'))
        self.redo()
        self.assertEqual('${/a.size}', self.attr('/b', 'z'))
        self.assertEqual('1', self.attr('/a', 'size'))

    def test_turned_off_only_the_attr_is_renamed(self):
        with prefs_with(user_dir.USER_PREF.REFACTOR_ATTR_RENAME, False):
            self.model.rename_node_attr('/a', 'x', 'size')
        self.assertEqual('1', self.attr('/a', 'size'))
        self.assertEqual('${/a.x}', self.attr('/b', 'z'))


class ParentUpdatesInstancePaths(RefactorTestCase):

    NODES = {
        '/src': {'attrs': {'x': {'value': '1'}}},
        '/grp': {},
        '/inst': {'instance': '/src'},
        '/near': {'child_order': ['kid', 'other']},
        '/near/kid': {'instance': '../other'},
        '/near/other': {},
    }

    def instance_path(self, path):
        return self.model.get_node_instance_path(
            path, layer=self.model.target_layer, expand=False)

    def test_instances_follow_a_parented_node(self):
        self.model.parent_nodes(['/src'], '/grp')
        self.assertEqual('/grp/src', self.instance_path('/inst'))
        self.assertEqual('1', self.model.get_node_attr_value(
            '/inst', 'x', layer=self.model.comp_layer))

    def test_a_relative_path_stays_relative(self):
        self.model.parent_nodes(['/near/kid'], '/grp')
        self.assertEqual('../../near/other',
                         self.instance_path('/grp/kid'))

    def test_undo_puts_them_back(self):
        self.model.parent_nodes(['/src'], '/grp')
        self.undo()
        self.assertEqual('/src', self.instance_path('/inst'))
        self.redo()
        self.assertEqual('/grp/src', self.instance_path('/inst'))

    def test_turned_off_the_instance_path_is_left(self):
        with prefs_with(user_dir.USER_PREF.REFACTOR_INSTANCE_PATHS, False):
            self.model.parent_nodes(['/src'], '/grp')
        self.assertEqual('/src', self.instance_path('/inst'))


if __name__ == '__main__':
    unittest.main()
