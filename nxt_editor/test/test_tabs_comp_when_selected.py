"""A graph is composited and drawn when its tab is selected, and once.

Opening a session full of files composited and drew every one of them up
front, for tabs nobody had looked at. The work belongs to the tab being
selected, and once a graph has been composited it stays composited, so
going back to a tab is free.

The dock widgets are the other half of it. One build view and one set of
workflow tools serve every tab, so what they were showing for a graph has
to be kept while another graph is in front of them. The build view used
to blank its start box on every tab change, which emptied the build and
read as the dock having given up on the graph; the workflow tools rebuilt
every widget from scratch, which on a real graph means walking all of it
looking for the window node.
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
from nxt_editor.main_window import MainWindow

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def write_graph(path, name, title):
    """Write a graph with a workflow window holding one button."""
    data = {
        "version": "1.17", "alias": name, "mute": False, "solo": False,
        "references": [], "meta_data": {"positions": {"/win": [0.0, 0.0]}},
        "nodes": {
            "/button": {"attrs": {"button_label": {"value": "''"}}},
            "/only": {},
            "/win": {
                "child_order": ["btn"],
                "attrs": {"_widget_window": {"value": "True"},
                          # Not resolved before it is used as a title,
                          # so it is written as plain text.
                          "window_title": {"value": title}},
            },
            "/win/btn": {"instance": "/button",
                         "attrs": {"button_label": {"value": "'%s'" % title}}},
        },
    }
    with open(path, 'w') as file_object:
        json.dump(data, file_object, indent=4)
    return path


class SelectingATab(unittest.TestCase):

    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.mkdtemp(prefix='nxt_tabs_')
        self.first = write_graph(os.path.join(self.tmp, 'first.nxt'),
                                 'first', 'First')
        self.second = write_graph(os.path.join(self.tmp, 'second.nxt'),
                                  'second', 'Second')
        self.win = MainWindow(filepath=self.first)
        self.win.show()
        app.processEvents()
        # How a session restores its tabs: the file is opened but the tab
        # it lands in is not the one being looked at.
        self.win.in_startup = True
        self.win.load_file(self.second)
        self.win.in_startup = False
        app.processEvents()

    def tearDown(self):
        # close() only hides it; the widget tree is finished with here
        # rather than left for whatever collects next.
        self.win.close()
        app.processEvents()
        self.win.deleteLater()
        app.processEvents()
        self.win = None
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    @property
    def tabs(self):
        return self.win.open_files_tab_widget

    def view(self, index):
        return self.tabs.widget(index)

    def select(self, index):
        self.tabs.setCurrentIndex(index)
        app.processEvents()

    # -- the graph itself -----------------------------------------------

    def test_there_are_two_tabs(self):
        self.assertEqual(2, self.tabs.count())

    def test_the_background_tab_is_not_composited(self):
        background = self.view(1)
        self.assertFalse(background.model.comp_is_built,
                         'a graph nobody has looked at was composited on '
                         'the way in')

    def test_the_background_tab_is_not_drawn(self):
        background = self.view(1)
        self.assertFalse(background.is_drawn)
        self.assertEqual([], background.scene().items(),
                         'a whole graph was drawn into a tab nobody has '
                         'looked at')

    def test_selecting_it_composites_and_draws_it(self):
        background = self.view(1)
        self.select(1)
        self.assertTrue(background.model.comp_is_built)
        self.assertTrue(background.is_drawn)
        self.assertTrue(background.scene().items())

    def test_coming_back_does_not_composite_it_again(self):
        self.select(1)
        generation = self.view(1).model.comp_generation
        self.select(0)
        self.select(1)
        self.assertEqual(generation, self.view(1).model.comp_generation,
                         'the graph was composited all over again for a '
                         'tab that nothing had touched')

    def test_coming_back_does_not_draw_it_again(self):
        self.select(1)
        drawn = self.view(1).scene().items()
        self.select(0)
        self.select(1)
        self.assertEqual(drawn, self.view(1).scene().items())

    # -- the build view -------------------------------------------------

    def test_the_build_view_keeps_a_start_point_per_graph(self):
        build_view = self.win.build_view
        self.select(0)
        build_view.starts_combo.setEditText('/only')
        app.processEvents()
        self.select(1)
        self.assertNotEqual('/only', build_view.starts_combo.currentText())
        self.select(0)
        self.assertEqual('/only', build_view.starts_combo.currentText(),
                         'switching tabs threw away the start point, so '
                         'the build came back empty')

    def test_the_build_comes_back_with_it(self):
        build_view = self.win.build_view
        self.select(0)
        build_view.starts_combo.setEditText('/only')
        app.processEvents()
        build = list(build_view.build_table.model()._nodes)
        self.assertEqual(['/only'], build)
        self.select(1)
        self.select(0)
        self.assertEqual(build, list(build_view.build_table.model()._nodes))

    def test_the_build_view_describes_the_graph_in_front_of_it(self):
        build_view = self.win.build_view
        self.select(0)
        build_view.starts_combo.setEditText('/only')
        app.processEvents()
        self.select(1)
        self.assertIs(self.view(1).model, build_view.build_model.stage_model)

    def test_a_start_point_that_is_gone_is_not_kept(self):
        build_view = self.win.build_view
        self.select(0)
        build_view.starts_combo.setEditText('/no_such_node')
        app.processEvents()
        self.assertEqual([], list(build_view.build_table.model()._nodes))

    # -- the workflow tools ---------------------------------------------

    def test_the_workflow_tools_are_built_at_startup(self):
        # Showing a main window does not call show() on its docks, so
        # this used to sit empty until an edit happened to announce
        # itself.
        self.assertIsNotNone(self.win.workflow_tools._page)
        self.assertEqual('First', self.win.workflow_tools.windowTitle())

    def test_each_graph_gets_its_own_page(self):
        tools = self.win.workflow_tools
        self.select(1)
        self.assertEqual('Second', tools.windowTitle())
        self.assertEqual(2, len(tools._pages))
        self.select(0)
        self.assertEqual('First', tools.windowTitle())
        self.assertEqual(2, len(tools._pages))

    def test_coming_back_to_a_page_does_not_build_it_again(self):
        tools = self.win.workflow_tools
        self.select(1)
        built = []
        original = tools.rebuild_page

        def counted(page):
            built.append(page)
            return original(page)

        tools.rebuild_page = counted
        self.select(0)
        self.select(1)
        self.select(0)
        self.assertEqual([], built,
                         'the workflow tools walked the graph again for a '
                         'window they had already built')

    def test_a_closed_graph_does_not_keep_its_page(self):
        tools = self.win.workflow_tools
        self.select(1)
        self.assertEqual(2, len(tools._pages))
        self.tabs.close_tab(1)
        app.processEvents()
        self.assertEqual(1, len(tools._pages),
                         'the page of a graph that is no longer open was '
                         'kept for the rest of the session')


if __name__ == '__main__':
    unittest.main()
