"""Finding nodes by name, in the Outliner and with Find Node (/).

Like the filters in mix: * stands for anything, commas separate names,
case is ignored, and a name matches anywhere in a node's name. A term with
a / in it matches the whole path. Nothing is a regex.
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
from Qt import QtCore, QtTest, QtWidgets

# Internal
from nxt_editor import finder, stage_model
from nxt_editor.node_search import NodeSearch, search_for

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402

PATHS = ['/rig', '/rig/arm_L_ctrl', '/rig/arm_R_ctrl', '/rig/leg_L',
         '/build', '/build/arm_L_ctrl', '/other.name', '/brackets[0]']


class Matching(unittest.TestCase):

    def found(self, text):
        return NodeSearch(text).filter(PATHS)

    def test_a_name_matches_anywhere_and_ignores_case(self):
        self.assertEqual(['/rig/leg_L'], self.found('EG'))

    def test_a_star_stands_for_anything(self):
        self.assertEqual(['/rig/arm_L_ctrl', '/rig/arm_R_ctrl',
                          '/build/arm_L_ctrl'], self.found('arm*ctrl'))

    def test_commas_find_any_of_several(self):
        self.assertEqual(['/rig/arm_R_ctrl', '/rig/leg_L'],
                         self.found('arm_R, leg'))

    def test_a_slash_matches_the_path(self):
        self.assertEqual(['/build/arm_L_ctrl'], self.found('build/*ctrl'))

    def test_nothing_is_a_regex(self):
        self.assertEqual(['/other.name'], self.found('r.n'))
        self.assertEqual(['/brackets[0]'], self.found('ts[0'))
        self.assertEqual([], self.found('^rig$'))

    def test_only_the_name_is_matched_without_a_slash(self):
        # "rig" is in the paths of rig's children, not in their names.
        self.assertEqual(['/rig'], self.found('rig'))

    def test_nothing_typed_finds_nothing(self):
        for text in ('', '  ', ',', '*', ' , * '):
            self.assertIsNone(search_for(text), repr(text))


GRAPH = {'version': '1.17', 'alias': 'find', 'nodes': {
    '/rig': {}, '/rig/arm_ctrl': {}, '/rig/leg_ctrl': {}, '/spine': {}}}


class FindNode(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_find_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'find.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.win = MainWindow(filepath=path)
        self.win.show()
        app.processEvents()
        self.model = self.win.model
        self.finder = finder.FinderWidget(self.win, self.model)
        self.finder.show()
        app.processEvents()
        self.box = self.finder.line_edit

    def tearDown(self):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def type(self, text):
        """Type text and stop, as the list waits for."""
        QtTest.QTest.keyClicks(self.box, text)
        QtTest.QTest.qWait(finder.SEARCH_DELAY_MS + 100)
        app.processEvents()

    def test_nothing_is_listed_until_typing_stops(self):
        QtTest.QTest.keyClicks(self.box, 'ctrl')
        app.processEvents()
        self.assertEqual([], self.box.matches)
        QtTest.QTest.qWait(finder.SEARCH_DELAY_MS + 100)
        self.assertEqual(['/rig/arm_ctrl', '/rig/leg_ctrl'], self.box.matches)

    def test_enter_before_the_list_shows_still_finds_them(self):
        QtTest.QTest.keyClicks(self.box, 'spine')
        QtTest.QTest.keyClick(self.box, QtCore.Qt.Key_Return)
        app.processEvents()
        self.assertEqual(['/spine'], self.model.get_selected_nodes())

    def test_it_opens_empty(self):
        self.assertEqual('', self.box.text())

    def test_matches_are_listed_as_you_type(self):
        self.type('ctrl')
        self.assertEqual(['/rig/arm_ctrl', '/rig/leg_ctrl'], self.box.matches)
        self.assertEqual(self.box.matches,
                         self.box.list_model.stringList())

    def test_enter_selects_every_match(self):
        self.type('arm*, spine')
        self.box.completer().popup().hide()
        QtTest.QTest.keyClick(self.box, QtCore.Qt.Key_Return)
        app.processEvents()
        self.assertEqual(['/rig/arm_ctrl', '/spine'],
                         sorted(self.model.get_selected_nodes()))

    def test_enter_on_a_highlighted_row_selects_only_it(self):
        self.type('ctrl')
        popup = self.box.completer().popup()
        popup.setCurrentIndex(popup.model().index(1, 0))
        QtTest.QTest.keyClick(popup, QtCore.Qt.Key_Return)
        app.processEvents()
        self.assertEqual(['/rig/leg_ctrl'], self.model.get_selected_nodes())

    def test_picking_one_selects_it(self):
        self.type('ctrl')
        self.box.completer().activated.emit('/rig/leg_ctrl')
        app.processEvents()
        self.assertEqual(['/rig/leg_ctrl'], self.model.get_selected_nodes())


if __name__ == '__main__':
    unittest.main()
