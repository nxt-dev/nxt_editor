"""The build view's find button jumps to whatever the graph has selected.

The build is an execution order, not a picture of the graph, so a selected
node is not always in it. The button has to say so rather than look broken.
"""
# Builtin
import os
import sys
import unittest

# External
from Qt import QtWidgets

# Internal
from nxt_editor.dockwidgets.build_view import BuildModel

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402


class BuildViewFindButton(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.chdir(os.path.dirname(__file__))
        # The dock's controls need the real action containers, so build the
        # real window rather than a stand in that has to grow every time
        # actions.py does.
        cls.win = MainWindow(filepath="StageInstanceTest.nxt")
        cls.view = cls.win.build_view
        cls.model = cls.win.model
        app.processEvents()
        # The build is empty until something says where to start. Typing a
        # node path into the starts box is how a person does it.
        cls.view.starts_combo.setEditText('/inst_source1')
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None

    def build_paths(self):
        return list(self.view.build_table.model()._nodes)

    def test_the_button_sits_left_of_play(self):
        layout = self.view.controls_layout
        order = [layout.itemAt(i).widget() for i in range(layout.count())]
        self.assertIn(self.view.find_selected_button, order)
        self.assertLess(order.index(self.view.find_selected_button),
                        order.index(self.view.pause_resume_button),
                        'find should come before play')

    def test_it_has_an_icon_and_a_tooltip(self):
        self.assertFalse(self.view.find_selected_button.icon().isNull())
        self.assertTrue(self.view.find_selected_button.toolTip())

    def test_scrolling_to_a_node_in_the_build(self):
        paths = self.build_paths()
        if not paths:
            self.skipTest('this graph produced an empty build')
        target = paths[-1]
        table = self.view.build_table
        self.assertTrue(table.scroll_to_path(target))
        self.assertEqual(paths.index(target), table.currentIndex().row())
        self.assertEqual(BuildModel.PATH_COLUMN,
                         table.currentIndex().column())

    def test_a_node_outside_the_build_reports_rather_than_moves(self):
        table = self.view.build_table
        self.assertFalse(table.scroll_to_path('/not/in/this/build'))

    def test_the_button_follows_the_graph_selection(self):
        paths = self.build_paths()
        if not paths:
            self.skipTest('this graph produced an empty build')
        target = paths[-1]
        self.model.selection = [target]
        self.view.find_selected_pressed()
        self.assertEqual(paths.index(target),
                         self.view.build_table.currentIndex().row())

    def test_the_found_node_is_scrolled_to_the_top(self):
        """Not centred: centring spends half the view on what already ran.

        Asserts the hint asked for rather than the pixels it produced. A
        dock with no laid out height has nothing to scroll, so measuring
        the result would be testing Qt's layout and not this decision.
        """
        table = self.view.build_table
        rows = ['/filler_%02d' % i for i in range(60)]
        self.view.build_model.nodes = rows
        app.processEvents()
        asked = []
        real_scroll_to = table.scrollTo

        def spy(index, hint=table.ScrollHint.EnsureVisible):
            asked.append(hint)
            return real_scroll_to(index, hint)

        table.scrollTo = spy
        try:
            self.assertTrue(table.scroll_to_path(rows[40]))
        finally:
            table.scrollTo = real_scroll_to
        self.assertEqual([table.ScrollHint.PositionAtTop], asked)

    def test_no_selection_is_harmless(self):
        self.model.selection = []
        # Must not raise; there is simply nothing to go to.
        self.view.find_selected_pressed()


if __name__ == '__main__':
    unittest.main()
