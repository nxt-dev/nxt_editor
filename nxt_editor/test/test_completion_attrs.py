"""self. completes every attribute a node's compute can use.

That is what the node says itself, what it inherits from its parent and
what it gets from the node it instances, from any layer, the same names
the Property Editor lists. ${/node. offers the same for another node.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import unittest

# External
from Qt import QtWidgets

# Internal
from nxt import DATA_STATE

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402


class InheritedAttrs(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='nxt_completion_attrs_')
        cls.graph = os.path.join(cls.tmp, 'attrs.nxt')
        with open(cls.graph, 'w') as fp:
            json.dump({'version': '1.17', 'alias': 'attrs', 'nodes': {
                '/parent': {'attrs': {'from_parent': {'value': '1'}}},
                '/parent/child': {'attrs': {'own': {'value': '2'}},
                                  'code': ['']},
                '/proto': {'attrs': {'from_proto': {'value': '3'}}},
                '/inst': {'instance': '/proto',
                          'attrs': {'overridden': {'value': '4'}},
                          'code': ['']},
            }}, fp)
        cls.win = MainWindow(filepath=cls.graph)
        cls.model = cls.win.model
        cls.editor = cls.win.code_editor.editor
        cls.model.data_state = DATA_STATE.RAW
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def words_for(self, node_path):
        self.model.set_selection([node_path])
        app.processEvents()
        self.editor.invalidate_completion_words()
        return self.editor.build_completion_words()

    def test_self_offers_what_the_parent_gives(self):
        words = self.words_for('/parent/child')
        self.assertIn('self.own', words)
        self.assertIn('self.from_parent', words)

    def test_self_offers_what_the_instance_gives(self):
        words = self.words_for('/inst')
        self.assertIn('self.overridden', words)
        self.assertIn('self.from_proto', words)

    def test_another_nodes_token_offers_them_too(self):
        self.words_for('/inst')
        got = self.editor.token_completions('${/parent/child.')
        self.assertIn('${/parent/child.from_parent}', got)
        got = self.editor.token_completions('${/inst.')
        self.assertIn('${/inst.from_proto}', got)


if __name__ == '__main__':
    unittest.main()
