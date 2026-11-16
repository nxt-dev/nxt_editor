"""Which lines the graph shows, and how.

Exec lines always show. Ctrl+L hides every other line, and property,
instance and code lines can each be hidden as well, all remembered as
preferences. A property line shows only while the property is showing on
at least one of its nodes, and is dotted when the property it goes into is
inherited from an instance or a parent rather than set on its node. A right
click on a line goes to either of its nodes.
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
from Qt import QtCore, QtWidgets

# Internal
from nxt_editor import connection_graphics_item as lines
from nxt_editor import stage_model, user_dir

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402


def attr(type_, value):
    return {'type': type_, 'value': value}


GRAPH = {
    'version': '1.17', 'alias': 'kinds',
    'nodes': {
        '/settings': {'attrs': {'count': attr('int', '5'),
                                'side': attr('str', 'L')}},
        '/rig': {'execute_in': '/settings',
                 'attrs': {'size': attr('raw', '${/settings.count}')}},
        # Its own side, and the size it inherits from /rig.
        '/arm': {'instance': '/rig',
                 'attrs': {'side': attr('raw', '${/settings.side}')}},
        '/hand': {'code': ['print(${/settings.count})']},
    },
    'meta_data': {'positions': {'/settings': [0.0, 0.0],
                                '/rig': [500.0, 0.0],
                                '/arm': [1000.0, 0.0],
                                '/hand': [1000.0, 400.0]}},
}
INHERITED = ('/settings.count', '/arm.size')
OWN = ('/settings.side', '/arm.side')
PREFS = list(lines.LINE_PREFS.values()) + [
    user_dir.USER_PREF.SHOW_LINES, user_dir.USER_PREF.SHOW_IMPLICIT]


class LinesCase(unittest.TestCase):

    def setUp(self):
        # These are real preferences on disk; put the user's back after.
        saved = {key: user_dir.user_prefs.get(key) for key in PREFS}
        self.addCleanup(self.restore, saved)
        for key in PREFS:
            self.restore({key: None})
        self.tmp = tempfile.mkdtemp(prefix='nxt_line_kinds_')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        path = os.path.join(self.tmp, 'kinds.nxt')
        with open(path, 'w') as fp:
            json.dump(GRAPH, fp)
        self.win = MainWindow(filepath=path)
        self.win.show()
        app.processEvents()
        self.view = self.win.view
        self.model = self.view.model
        self.view.ensure_drawn()
        app.processEvents()

    @staticmethod
    def restore(saved):
        for key, value in saved.items():
            if value is None:
                if key in user_dir.user_prefs:
                    user_dir.user_prefs.pop(key)
            else:
                user_dir.user_prefs[key] = value

    def tearDown(self):
        unsaved = mock.patch.object(stage_model.StageModel,
                                    'get_unsaved_changes', return_value=[])
        with unsaved:
            self.win.close()
            app.processEvents()
        self.win.deleteLater()
        app.processEvents()

    def line(self, src, tgt):
        found = [line for line in self.view._connection_graphics
                 if (line.src_path, line.tgt_path) == (src, tgt)]
        self.assertEqual(1, len(found), (src, tgt))
        return found[0]

    def shown(self, kind=None):
        return sorted((line.src_path, line.tgt_path)
                      for line in self.view._connection_graphics
                      if line.isVisible() and kind in (None, line.kind))

    def show(self, paths, state):
        self.model.set_attr_display_state(paths, state)
        app.processEvents()


class PropertyLines(LinesCase):

    def test_with_every_node_closed_there_are_none(self):
        self.assertEqual([], self.shown(lines.PROPERTY_LINES))
        self.assertTrue(self.shown(lines.EXEC_LINES))

    def test_one_end_showing_shows_the_line(self):
        self.show(['/settings'], 3)
        self.assertIn(OWN, self.shown(lines.PROPERTY_LINES))
        self.show(['/settings'], 0)
        self.show(['/arm'], 1)
        self.assertEqual([OWN], self.shown(lines.PROPERTY_LINES))

    def test_closing_both_ends_hides_it_again(self):
        self.show(['/settings', '/arm'], 3)
        self.assertIn(OWN, self.shown())
        self.show(['/settings', '/arm'], 0)
        self.assertNotIn(OWN, self.shown())

    def test_an_inherited_property_gets_a_dotted_line(self):
        self.show(['/arm'], 3)
        self.assertTrue(self.line(*INHERITED).dashes)
        self.assertFalse(self.line(*OWN).dashes)
        self.assertFalse(self.line('/settings.count', '/rig.size').dashes)


class Toggles(LinesCase):

    def test_each_kind_can_be_hidden_and_is_remembered(self):
        self.show(['/settings'], 3)
        actions = self.win.view_actions
        for action, kind in ((actions.property_lines_action,
                              lines.PROPERTY_LINES),
                             (actions.instance_lines_action,
                              lines.INSTANCE_LINES),
                             (actions.code_lines_action, lines.CODE_LINES)):
            self.assertTrue(self.shown(kind), kind)
            action.trigger()
            app.processEvents()
            self.assertEqual([], self.shown(kind), kind)
            self.assertIs(False, user_dir.user_prefs.get(
                lines.LINE_PREFS[kind]))
            action.trigger()
            app.processEvents()
            self.assertTrue(self.shown(kind), kind)

    def test_there_is_no_hiding_exec_lines(self):
        actions = self.win.view_actions
        self.assertFalse(hasattr(actions, 'exec_lines_action'))
        self.assertNotIn(lines.EXEC_LINES, lines.LINE_PREFS)
        self.assertTrue(lines.lines_shown(lines.EXEC_LINES))
        with self.assertRaises(ValueError):
            lines.show_lines(lines.EXEC_LINES, False)
        # Not even by an old preference.
        self.addCleanup(self.restore, {
            'show_exec_lines': user_dir.user_prefs.get('show_exec_lines')})
        user_dir.user_prefs['show_exec_lines'] = False
        self.view.update_lines_shown()
        self.assertTrue(self.shown(lines.EXEC_LINES))

    def test_ctrl_l_hides_every_line_but_exec_and_brings_back_the_rest(
            self):
        self.show(['/settings'], 3)
        actions = self.win.view_actions
        self.assertEqual('Ctrl+L', actions.lines_action.shortcut().toString())
        actions.code_lines_action.trigger()
        app.processEvents()
        exec_lines = self.shown(lines.EXEC_LINES)
        self.assertTrue(exec_lines)
        actions.lines_action.trigger()
        app.processEvents()
        self.assertEqual(exec_lines, self.shown())
        self.assertIs(False, user_dir.user_prefs.get(
            user_dir.USER_PREF.SHOW_LINES))
        actions.lines_action.trigger()
        app.processEvents()
        for kind in (lines.EXEC_LINES, lines.PROPERTY_LINES,
                     lines.INSTANCE_LINES):
            self.assertTrue(self.shown(kind), kind)
        # Turned off on its own, it stays off.
        self.assertEqual([], self.shown(lines.CODE_LINES))

    def test_code_lines_start_hidden_if_the_old_toggle_hid_them(self):
        user_dir.user_prefs[user_dir.USER_PREF.SHOW_IMPLICIT] = False
        self.assertFalse(lines.lines_shown(lines.CODE_LINES))
        self.assertFalse(lines.lines_shown(lines.INSTANCE_LINES))
        self.assertTrue(lines.lines_shown())
        user_dir.user_prefs[user_dir.USER_PREF.SHOW_CODE_LINES] = True
        self.assertTrue(lines.lines_shown(lines.CODE_LINES))

    def test_the_toolbar_and_view_menu_have_the_lines_menu(self):
        toolbar = self.win.findChild(QtWidgets.QToolBar, 'Display Tools')
        menu = toolbar.lines_button.menu()
        actions = [a for a in menu.actions() if not a.isSeparator()]
        self.assertEqual([self.win.view_actions.lines_action] +
                         self.win.view_actions.lines_actions, actions)
        titles = [a.text() for a in self.win.menu_bar.view_menu.actions()]
        self.assertIn('Lines', titles)

    def test_a_hidden_line_is_not_clicked(self):
        self.model.set_nodes_pos({'/hand': [500.0, 600.0]})
        app.processEvents()
        line = self.line('/settings.count', '/hand._code')
        middle = self.view.mapFromScene(line.path().pointAtPercent(0.5))
        self.assertEqual([line], self.view.lines_at(middle))
        self.view.show_lines(lines.CODE_LINES, False)
        self.assertEqual([], self.view.lines_at(middle))


class GoTo(LinesCase):

    def test_a_code_line_can_be_gone_to_but_not_broken(self):
        line = self.line('/settings.count', '/hand._code')
        menu = self.view.make_lines_menu([line])
        texts = [a.text() for a in menu.actions() if not a.isSeparator()]
        self.assertEqual(['Go to Source: /settings', 'Go to Target: /hand'],
                         texts)
        menu.actions()[-1].trigger()
        app.processEvents()
        self.assertEqual(['/hand'], self.model.selection)

class Clicking(LinesCase):
    """A click a few pixels off a line lands on it, whichever way the line
    runs and however far out the graph is zoomed."""

    def test_a_steep_line_is_found_beside_it_at_any_zoom(self):
        self.model.set_nodes_pos({'/rig': [0.0, 900.0]})
        app.processEvents()
        line = self.line('/settings', '/rig._execute_in')
        for scale in (1.0, 0.5, 0.25):
            self.view.resetTransform()
            self.view.scale(scale, scale)
            middle = line.path().pointAtPercent(0.5)
            self.view.centerOn(middle)
            app.processEvents()
            beside = self.view.mapFromScene(middle) + QtCore.QPoint(6, 0)
            self.assertEqual([line], self.view.lines_at(beside), scale)
            far = self.view.mapFromScene(middle) + QtCore.QPoint(40, 0)
            self.assertEqual([], self.view.lines_at(far), scale)


if __name__ == '__main__':
    unittest.main()
