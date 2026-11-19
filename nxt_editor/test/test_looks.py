"""The editor has three looks to choose from.

Modern is its own, the same in every host. Classic is how it looked
before. Host application takes the host's colors, font and widgets. The
look is asked for in Options > Preferences, or by NXT_EDITOR_LOOK, and put
in place as the theme loads.
"""
# Builtin
import os
import sys
import unittest
from unittest import mock

# External
from Qt import QtGui, QtWidgets

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

# Internal
import nxt_editor  # noqa: E402
from nxt_editor import preference_editor, theme, user_dir  # noqa: E402


class LookCase(unittest.TestCase):

    def setUp(self):
        before = dict(theme.tokens())
        self.addCleanup(vars(theme).update, before)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(theme.LOOK_ENV_VAR, None)


class Asked(LookCase):

    def test_modern_unless_told_otherwise(self):
        with mock.patch.object(user_dir.user_prefs, 'get',
                               side_effect=lambda key, default=None: default):
            self.assertEqual(theme.LOOK_MODERN, theme.stored_look())

    def test_the_preference_is_read(self):
        with mock.patch.object(user_dir.user_prefs, 'get',
                               return_value=theme.LOOK_CLASSIC):
            self.assertEqual(theme.LOOK_CLASSIC, theme.stored_look())

    def test_the_environment_has_the_last_word(self):
        os.environ[theme.LOOK_ENV_VAR] = 'Host'
        with mock.patch.object(user_dir.user_prefs, 'get',
                               return_value=theme.LOOK_CLASSIC):
            self.assertEqual(theme.LOOK_HOST, theme.stored_look())

    def test_a_look_nobody_knows_is_modern(self):
        os.environ[theme.LOOK_ENV_VAR] = 'neon'
        with mock.patch.object(user_dir.user_prefs, 'get',
                               return_value='plaid'):
            self.assertEqual(theme.LOOK_MODERN, theme.stored_look())

    def test_prefs_that_cannot_be_read_do_not_stop_the_editor(self):
        with mock.patch.object(user_dir.user_prefs, 'get',
                               side_effect=IOError('no prefs')):
            self.assertEqual(theme.LOOK_MODERN, theme.stored_look())

    def test_preferences_offers_the_three(self):
        look = [p for p in preference_editor.PREFERENCES
                if p.key == user_dir.USER_PREF.LOOK][0]
        self.assertEqual([theme.LOOK_MODERN, theme.LOOK_CLASSIC,
                          theme.LOOK_HOST],
                         [value for value, _label in look.choices])
        self.assertEqual(theme.LOOK_MODERN, look.default)
        self.assertEqual(theme.LOOK_PREF, look.key)


class Modern(LookCase):

    def test_it_is_the_look_in_use(self):
        self.assertEqual(theme.LOOK_MODERN, theme.LOOK)
        self.assertIn(theme.BASE, nxt_editor.stylesheet())


class Classic(LookCase):

    def setUp(self):
        super(Classic, self).setUp()
        theme.use_look(theme.LOOK_CLASSIC)

    def test_the_original_sheet_is_used_as_it_was_written(self):
        sheet = nxt_editor.stylesheet()
        self.assertEqual(nxt_editor._read_resource(nxt_editor.STYLESHEET),
                         sheet)
        self.assertIn('#148CD2', sheet)

    def test_sheets_written_for_the_old_colors_keep_them(self):
        self.assertEqual('color: #3E3E3E;', theme.restyle('color: #3E3E3E;'))

    def test_nodes_are_square_and_in_the_code_font(self):
        self.assertEqual(2, theme.NODE_RADIUS)
        self.assertTrue(theme.NODE_MONO)
        self.assertEqual('#232323', theme.fill('{GRAPH}'))


class Host(LookCase):

    def setUp(self):
        super(Host, self).setUp()
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor('#444444'))
        palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor('#c8c8c8'))
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor('#2b2b2b'))
        palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor('#5285a6'))
        before = app.palette()
        self.addCleanup(app.setPalette, before)
        app.setPalette(palette)
        theme.use_look(theme.LOOK_HOST)

    def test_the_editor_sets_no_sheet_of_its_own(self):
        self.assertEqual('', nxt_editor.stylesheet())

    def test_colors_are_the_hosts(self):
        self.assertEqual('#444444', theme.BASE)
        self.assertEqual('#2b2b2b', theme.GRAPH)
        self.assertEqual('#c8c8c8', theme.TEXT)
        self.assertEqual('#5285a6', theme.ACCENT)

    def test_text_is_in_the_hosts_font(self):
        self.assertEqual(app.font().family(), theme.font_family())
        self.assertEqual(app.font().family(), theme.font().family())

    def test_without_an_application_it_is_modern(self):
        with mock.patch.object(QtGui.QGuiApplication, 'instance',
                               return_value=None):
            theme.use_look(theme.LOOK_HOST)
        self.assertEqual(theme.LOOK_MODERN, theme.LOOK)


if __name__ == '__main__':
    unittest.main()
