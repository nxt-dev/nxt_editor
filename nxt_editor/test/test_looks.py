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
        self.modern = before
        self.addCleanup(vars(theme).update, before)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop(theme.LOOK_ENV_VAR, None)
        os.environ.pop(theme.STYLESHEET_ENV_VAR, None)
        del theme._unread_sheets[:]


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

    def test_a_look_written_by_hand_is_read_whatever_its_case(self):
        with mock.patch.object(user_dir.user_prefs, 'get',
                               return_value=' Classic '):
            self.assertEqual(theme.LOOK_CLASSIC, theme.stored_look())

    def test_a_value_that_is_no_look_is_modern(self):
        for value in (5, None, ['classic'], {'look': 'classic'}):
            with mock.patch.object(user_dir.user_prefs, 'get',
                                   return_value=value):
                self.assertEqual(theme.LOOK_MODERN, theme.stored_look())

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

    def test_the_sections_of_preferences_keep_their_order(self):
        sections = []
        for pref in preference_editor.PREFERENCES:
            if pref.section not in sections:
                sections.append(pref.section)
        self.assertEqual('Graph', sections[0])
        self.assertIn('Panels', sections)


class OwnStylesheet(LookCase):

    def sheet_file(self, text):
        import tempfile
        handle = tempfile.NamedTemporaryFile('w', suffix='.qss', delete=False)
        handle.write(text)
        handle.close()
        self.addCleanup(os.remove, handle.name)
        return handle.name

    def test_it_is_laid_over_the_look_in_the_looks_colors(self):
        path = self.sheet_file('QLabel { color: {TEXT}; }')
        os.environ[theme.STYLESHEET_ENV_VAR] = path
        sheet = nxt_editor.stylesheet()
        self.assertTrue(sheet.endswith('QLabel { color: %s; }' % theme.TEXT))
        self.assertIn(theme.BASE, sheet)

    def test_the_preference_names_one_too(self):
        path = self.sheet_file('QLabel { margin: 3px; }')
        with mock.patch.object(user_dir.user_prefs, 'get',
                               return_value=path):
            self.assertEqual('QLabel { margin: 3px; }',
                             theme.extra_stylesheet())

    def test_one_that_is_not_there_is_passed_over(self):
        os.environ[theme.STYLESHEET_ENV_VAR] = os.path.join(
            os.path.dirname(__file__), 'no_such_sheet.qss')
        with self.assertLogs('nxt_editor.theme', level='WARNING') as logs:
            self.assertEqual('', theme.extra_stylesheet())
            # Said once, however many windows ask for the sheet.
            self.assertEqual('', theme.extra_stylesheet())
        self.assertEqual(1, len(logs.records))

    def test_none_is_asked_for_to_begin_with(self):
        with mock.patch.object(user_dir.user_prefs, 'get',
                               side_effect=lambda key, default=None: default):
            self.assertEqual('', theme.extra_stylesheet())


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

    def test_the_editor_styles_next_to_nothing_itself(self):
        sheet = nxt_editor.stylesheet()
        self.assertEqual(theme.fill(theme.HOST_SHEET), sheet)
        self.assertNotIn('QPushButton', sheet)
        self.assertNotIn('{', sheet.replace('title {', ''))

    def test_text_is_the_size_the_host_uses(self):
        self.assertEqual(app.font().pointSizeF(), theme.font().pointSizeF())
        self.assertEqual(20, theme.font(20).pixelSize())

    def test_a_dimmed_layer_color_still_reads_on_the_hosts_panel(self):
        dimmed = QtGui.QColor('#cc3333').darker(150)
        self.assertLess(theme.contrast(dimmed, theme.BASE), 2.6)
        shown = theme.readable_on(dimmed, theme.BASE, 2.6)
        self.assertGreaterEqual(theme.contrast(shown, theme.BASE), 2.6)

    def test_colors_are_the_hosts(self):
        self.assertEqual('#444444', theme.BASE)
        self.assertEqual('#2b2b2b', theme.GRAPH)
        self.assertEqual('#c8c8c8', theme.TEXT)
        self.assertEqual('#5285a6', theme.ACCENT)

    def test_text_is_in_the_hosts_font(self):
        self.assertEqual(app.font().family(), theme.font_family())
        self.assertEqual(app.font().family(), theme.font().family())

    def test_without_an_application_it_is_modern(self):
        with mock.patch.object(QtWidgets.QApplication, 'instance',
                               return_value=None):
            theme.use_look(theme.LOOK_HOST)
        self.assertEqual(theme.LOOK_MODERN, theme.LOOK)

    def test_an_application_nxt_made_has_no_look_to_take(self):
        # Standalone, and in Blender and Unreal, which are not Qt.
        app.setProperty(nxt_editor.OWN_APP_PROPERTY, True)
        self.addCleanup(app.setProperty, nxt_editor.OWN_APP_PROPERTY, None)
        hosts = theme.BASE
        vars(theme).update(self.modern)
        theme.use_look(theme.LOOK_HOST)
        self.assertEqual(theme.LOOK_MODERN, theme.LOOK)
        self.assertNotEqual(hosts, theme.BASE)
        self.assertIn('QPushButton', nxt_editor.stylesheet())

    def test_a_light_host_keeps_the_modern_look(self):
        # The graph, the nodes and the log are drawn for a dark interface.
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor('#f0f0f0'))
        palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor('#000000'))
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor('#ffffff'))
        app.setPalette(palette)
        vars(theme).update(self.modern)
        theme.use_look(theme.LOOK_HOST)
        self.assertEqual(theme.LOOK_MODERN, theme.LOOK)
        self.assertEqual(self.modern['NODE_TEXT'], theme.NODE_TEXT)
        self.assertEqual(self.modern['BASE'], theme.BASE)



def in_host(name):
    """The editor as a host's integration opens it."""
    from nxt.constants import NXT_DCC_ENV_VAR
    return mock.patch.dict(os.environ, {NXT_DCC_ENV_VAR: name})


class HostsThatAreNotQt(LookCase):
    """Blender and Unreal are not Qt applications, so the editor draws its
    widgets there itself, in that host's colors and font."""

    def look_in(self, host):
        with in_host(host):
            theme.use_look(theme.LOOK_HOST)

    def test_blender_has_its_own_colors_and_font(self):
        self.look_in(theme.BLENDER)
        self.assertEqual(theme.LOOK_HOST, theme.LOOK)
        self.assertEqual(theme.BLENDER, theme.HOST)
        self.assertEqual('#303030', theme.BASE)
        self.assertEqual('#545454', theme.BUTTON)
        self.assertEqual('#4772b3', theme.ACCENT)
        self.assertEqual('Inter', theme.font_family())
        self.assertEqual('Inter', theme.font().family())

    def test_unreal_has_its_own_colors_and_font(self):
        self.look_in(theme.UNREAL)
        self.assertEqual(theme.UNREAL, theme.HOST)
        self.assertEqual('#242424', theme.BASE)
        self.assertEqual('#0f0f0f', theme.INPUT)
        self.assertEqual('#0070e0', theme.ACCENT)
        self.assertEqual('Roboto', theme.font().family())

    def test_the_editor_draws_its_widgets_there(self):
        self.look_in(theme.BLENDER)
        self.assertFalse(theme.HOST_DRAWS)
        sheet = nxt_editor.stylesheet()
        self.assertIn('QPushButton', sheet)
        self.assertIn('#545454', sheet)
        self.assertIn('"Inter"', sheet)

    def test_the_host_is_known_from_its_module(self):
        # Before its integration says so.
        with mock.patch.dict(sys.modules, {'bpy': mock.Mock()}):
            self.assertEqual(theme.BLENDER, theme.running_host())
        with mock.patch.dict(sys.modules, {'unreal': mock.Mock()}):
            self.assertEqual(theme.UNREAL, theme.running_host())

    def test_modern_and_classic_are_the_same_in_them(self):
        for host in (theme.BLENDER, theme.UNREAL):
            with in_host(host):
                theme.use_look(theme.LOOK_MODERN)
                self.assertEqual(self.modern['BASE'], theme.BASE)
                self.assertEqual('', theme.HOST)


class ModernTokens(LookCase):

    def test_inputs_buttons_and_menus_are_as_before(self):
        # New names, with the values modern had there.
        self.assertEqual(theme.GRAPH, theme.INPUT)
        self.assertEqual(theme.RAISED, theme.BUTTON)
        self.assertEqual(theme.RAISED, theme.MENU)

    def test_classic_and_a_qt_host_fill_them_in(self):
        theme.use_look(theme.LOOK_CLASSIC)
        self.assertEqual(theme.GRAPH, theme.INPUT)
        self.assertEqual(theme.RAISED, theme.BUTTON)


class WorkflowShapes(LookCase):
    """In a host that draws the editor, a workflow's buttons keep the
    modern shapes, in the host's colors."""

    def test_modern_shapes_in_the_hosts_colors(self):
        vars(theme).update({'LOOK': theme.LOOK_HOST, 'HOST_DRAWS': 1,
                            'BUTTON': '#5d5d5d', 'RADIUS': 2})
        sheet = nxt_editor.modern_shapes()
        self.assertIn('border-radius: 2px', sheet)
        self.assertIn('#5d5d5d', sheet)
        from nxt_editor.dockwidgets.widget_builder import WidgetBuilder
        builder = WidgetBuilder()
        self.addCleanup(builder.deleteLater)
        self.assertTrue(builder.styleSheet().startswith(sheet))
        # The dock's own rules still come after, and win.
        self.assertIn('QDockWidget', builder.styleSheet()[len(sheet):])

    def test_not_in_modern(self):
        from nxt_editor.dockwidgets.widget_builder import WidgetBuilder
        builder = WidgetBuilder()
        self.addCleanup(builder.deleteLater)
        self.assertNotIn('QPushButton', builder.styleSheet())


class LookPreference(LookCase):

    def editor(self):
        look = [p for p in preference_editor.PREFERENCES
                if p.key == user_dir.USER_PREF.LOOK][0]
        dialog = preference_editor.PreferenceEditor.__new__(
            preference_editor.PreferenceEditor)
        QtWidgets.QDialog.__init__(dialog)
        dialog._filling = False
        self.addCleanup(dialog.deleteLater)
        return dialog.make_editor(look)

    def host_item(self, editor):
        return editor.model().item(editor.findData(theme.LOOK_HOST))

    def test_host_is_greyed_out_on_its_own(self):
        editor = self.editor()
        self.assertFalse(self.host_item(editor).isEnabled())
        self.assertTrue(editor.isEnabled())

    def test_host_can_be_chosen_in_a_host(self):
        with in_host(theme.MAYA):
            editor = self.editor()
        self.assertTrue(self.host_item(editor).isEnabled())

    def test_the_environment_variable_is_shown_and_wins(self):
        os.environ[theme.LOOK_ENV_VAR] = 'classic'
        editor = self.editor()
        self.assertEqual(theme.LOOK_CLASSIC, editor.currentData())
        self.assertFalse(editor.isEnabled())
        self.assertIn(theme.LOOK_ENV_VAR, editor.toolTip())


if __name__ == '__main__':
    unittest.main()
