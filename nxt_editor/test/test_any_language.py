# -*- coding: utf-8 -*-
"""The editor works in any language.

A graph whose node names, attributes, comments and code are in Chinese,
Russian, Arabic or any other script opens, shows its nodes, takes edits,
saves and runs, from a folder whose name is not English either. Completion
offers names in any language, and the output log shows them as written,
even when a character arrives split across two reads of the log file.
"""
# Builtin
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

# External
from Qt import QtGui, QtWidgets

# Internal
from nxt import DATA_STATE, nxt_io
from nxt.session import Session

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.dockwidgets.output_log import FileTailingThread  # noqa: E402
from nxt_editor.main_window import MainWindow  # noqa: E402

NAMES = [u'节点', u'ノード', u'노드', u'узел', u'κόμβος', u'عقدة', u'Ñandú']


class AnyLanguage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix='nxt_any_language_')
        cls.dir = os.path.join(cls.root, u'项目 Проект')
        os.makedirs(cls.dir)
        cls.out = os.path.join(cls.dir, u'输出.txt').replace(os.sep, '/')
        nodes = {'/': {'attrs': {'out': {'value': repr(cls.out)}}}}
        previous = None
        for index, name in enumerate(NAMES):
            node = {'comment': u'注释 ' + name,
                    'attrs': {u'名字': {'value': repr(name),
                                       'comment': u'属性说明'}},
                    'code': [u'# 这是注释 😀',
                             u"with open(${out}, 'a', encoding='utf-8') as fp:",
                             u"    fp.write(${名字} + '\\n')"]}
            if previous:
                node['execute_in'] = previous
            else:
                node['start_point'] = True
            nodes[u'/' + name] = node
            previous = u'/' + name
        cls.graph = os.path.join(cls.dir, u'图表.nxt')
        # Written out as the characters themselves, the way a person or
        # another tool might save it.
        with io.open(cls.graph, 'w', encoding='utf-8') as fp:
            fp.write(json.dumps({'version': '1.17', 'alias': u'图',
                                 'nodes': nodes}, ensure_ascii=False))
        cls.win = MainWindow(filepath=cls.graph)
        cls.model = cls.win.model
        cls.editor = cls.win.code_editor.editor
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        # The edits are not kept, so there is nothing to ask about saving.
        cls.model.effected_layers.clear()
        cls.win.close()
        cls.win = None
        app.processEvents()
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_it_opens_with_every_node(self):
        for name in NAMES:
            self.assertTrue(self.model.node_exists(u'/' + name),
                            name + ' is missing')

    def test_selecting_a_node_shows_its_code(self):
        for state in (DATA_STATE.RAW, DATA_STATE.RESOLVED):
            self.model.data_state = state
            self.model.set_selection([u'/' + NAMES[3]])
            app.processEvents()
            self.assertIn(u'这是注释 😀', self.editor.toPlainText())
        self.model.data_state = DATA_STATE.RAW

    def test_edits_save_and_reopen(self):
        layer = self.model.target_layer
        self.model.add_node(name=u'새노드', parent_path='/', layer=layer)
        self.model.set_node_comment(u'/' + NAMES[0], u'Привет мир', layer)
        self.model.set_node_attr_value(u'/' + NAMES[1], u'名字',
                                       repr(u'مرحبا'), layer)
        app.processEvents()
        saved = os.path.join(self.dir, u'保存.nxt')
        self.win.nxt.save_layer(layer, filepath=saved, as_copy=True)
        data = nxt_io.load_file_data(saved)
        self.assertIn(u'/새노드', data['nodes'])
        self.assertEqual(u'Привет мир',
                         data['nodes'][u'/' + NAMES[0]]['comment'])
        self.assertIn(u'مرحبا', json.dumps(data, ensure_ascii=False))

    def test_it_runs(self):
        if os.path.exists(self.out):
            os.remove(self.out)
        Session().execute_graph(self.graph)
        with io.open(self.out, encoding='utf-8') as fp:
            self.assertEqual(NAMES, fp.read().split())

    def test_completion_offers_names_in_any_language(self):
        self.model.set_selection([u'/' + NAMES[0]])
        app.processEvents()
        self.editor.setReadOnly(False)
        self.editor.setPlainText(u'значение = 1\nзнач')
        cursor = self.editor.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.editor.setTextCursor(cursor)
        self.assertEqual(u'знач', self.editor.completion_prefix())
        self.editor.invalidate_completion_words()
        words = self.editor.build_completion_words()
        self.assertIn(u'значение', words)
        self.assertIn(u'${名字}', words)
        self.editor.setPlainText(u'x = ${名')
        cursor.movePosition(QtGui.QTextCursor.End)
        self.editor.setTextCursor(self.editor.textCursor())
        cursor = self.editor.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.editor.setTextCursor(cursor)
        self.assertEqual(u'${名', self.editor.completion_prefix())

    def test_the_log_shows_a_character_split_across_reads(self):
        log = os.path.join(self.dir, u'日志.nxtlog')
        encoded = u'第一行 😀\n'.encode('utf-8')
        tail = FileTailingThread(log)
        got = []
        tail.new_text.connect(got.append)
        # Half of the emoji now, the rest on the next read.
        with open(log, 'wb') as fp:
            fp.write(encoded[:-3])
        self.read_once(tail)
        with open(log, 'ab') as fp:
            fp.write(encoded[-3:])
        self.read_once(tail)
        self.assertEqual(u'第一行 😀\n', u''.join(got))

    @staticmethod
    def read_once(tail):
        """Run one turn of the tail's loop."""
        tail.last_mtime = 0
        calls = []
        tail.isInterruptionRequested = lambda: bool(calls) or calls.append(1)
        import time
        sleep, time.sleep = time.sleep, lambda _seconds: None
        try:
            tail.run()
        finally:
            time.sleep = sleep


if __name__ == '__main__':
    unittest.main()
