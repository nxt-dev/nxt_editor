"""The editor's title can say which host session the window belongs to.

Two Maya sessions each have an editor, and both windows used to carry the
same title, so the taskbar could not tell them apart. A host can now give
the window a short label, and the Maya plug-in gives it the scene's name.

Nothing here needs Maya: the plug-in is loaded with a stand-in for the
maya modules.
"""
# Builtin
import importlib.util
import os
import sys
import types
import unittest
from unittest import mock

# External
from Qt import QtWidgets

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402
from nxt_editor.constants import EDITOR_VERSION  # noqa: E402

PLUGIN = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'integration', 'maya', 'plug-ins',
    'nxt_maya.py')


def pump(times=10):
    for _ in range(times):
        app.processEvents()


class HostLabelInTitle(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.win = MainWindow()
        cls.win.show()
        pump()
        cls.plain = cls.win.windowTitle()

    @classmethod
    def tearDownClass(cls):
        cls.win.hide()
        pump()

    def tearDown(self):
        self.win.set_host_label('')

    def test_no_label_is_the_title_as_it_always_was(self):
        start = 'nxt {} - Editor v{} | Graph v'.format(
            self.win.host_app, EDITOR_VERSION.VERSION_STR)
        self.assertTrue(self.plain.startswith(start), self.plain)
        self.assertEqual('', self.win.host_label)

    def test_label_sits_next_to_the_host_name(self):
        self.win.set_host_label('rig_v012.ma')
        start = 'nxt {} [rig_v012.ma] - Editor v'.format(self.win.host_app)
        self.assertTrue(self.win.windowTitle().startswith(start),
                        self.win.windowTitle())
        self.assertEqual('rig_v012.ma', self.win.host_label)

    def test_a_new_label_replaces_the_old_one(self):
        self.win.set_host_label('rig_v012.ma')
        self.win.set_host_label('rig_v013.ma')
        self.assertIn('[rig_v013.ma]', self.win.windowTitle())
        self.assertNotIn('rig_v012', self.win.windowTitle())

    def test_clearing_the_label_restores_the_title(self):
        self.win.set_host_label('rig_v012.ma')
        for nothing in ('', None, '   '):
            self.win.set_host_label(nothing)
            self.assertEqual(self.plain, self.win.windowTitle())
            self.win.set_host_label('rig_v012.ma')

    def test_a_long_label_is_shortened_from_the_middle(self):
        long_name = 'character_' + 'x' * 300 + '_rig_v012.ma'
        self.win.set_host_label(long_name)
        title = self.win.windowTitle()
        self.assertLess(len(title), len(self.plain) + 50)
        # Both ends say something: what it is and which version.
        self.assertIn('[character_', title)
        self.assertIn('v012.ma]', title)
        self.assertIn('...', title)
        # The whole label is still there to ask for.
        self.assertEqual(long_name, self.win.host_label)

    def test_label_survives_tabs_opening_and_closing(self):
        self.win.set_host_label('rig_v012.ma')
        expected = self.win.windowTitle()
        self.win.new_tab()
        pump()
        self.assertEqual(expected, self.win.windowTitle())
        self.win.new_tab()
        pump()
        self.win.open_files_tab_widget.setCurrentIndex(0)
        pump()
        self.assertEqual(expected, self.win.windowTitle())


class FakeSceneMessage(object):
    kAfterNew, kAfterOpen, kAfterSave = 'new', 'open', 'save'

    def __init__(self):
        self.callbacks = {}
        self.fail_on = None

    def addCallback(self, message, func, client_data=None):
        if message == self.fail_on:
            raise RuntimeError('maya said no')
        callback_id = len(self.callbacks) + 100
        self.callbacks[callback_id] = (message, func)
        return callback_id

    def removeCallback(self, callback_id):
        del self.callbacks[callback_id]


class FakeWindow(object):

    def __init__(self):
        self.labels = []

    def set_host_label(self, text):
        self.labels.append(text)


def load_plugin():
    """Import nxt_maya.py with stand-ins for the maya modules."""
    maya = types.ModuleType('maya')
    maya.cmds = types.ModuleType('maya.cmds')
    maya.mel = types.ModuleType('maya.mel')
    maya.api = types.ModuleType('maya.api')
    om = types.ModuleType('maya.api.OpenMaya')
    om.MPxCommand = object
    om.MSceneMessage = FakeSceneMessage()
    maya.api.OpenMaya = om
    maya.cmds.scene = ''
    maya.cmds.file = lambda *args, **kwargs: maya.cmds.scene
    fakes = {'maya': maya, 'maya.cmds': maya.cmds, 'maya.mel': maya.mel,
             'maya.api': maya.api, 'maya.api.OpenMaya': om}
    spec = importlib.util.spec_from_file_location('nxt_maya_under_test',
                                                  PLUGIN)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, fakes):
        spec.loader.exec_module(module)
    return module


class MayaSceneLabel(unittest.TestCase):

    def setUp(self):
        self.plugin = load_plugin()
        self.cmds = self.plugin.cmds
        self.scene_message = self.plugin.om.MSceneMessage
        self.win = FakeWindow()

    def test_scene_path_becomes_its_file_name(self):
        scene_label = self.plugin.scene_label
        self.assertEqual('rig_v012.ma',
                         scene_label('C:/show/assets/hero/rig_v012.ma'))
        self.assertEqual('rig_v012.ma',
                         scene_label('C:\\show\\assets\\rig_v012.ma'))
        self.assertEqual('untitled', scene_label(''))
        self.assertEqual('untitled', scene_label(None))

    def test_tracking_labels_the_window_right_away(self):
        self.cmds.scene = 'C:/show/rig_v012.ma'
        self.plugin.track_scene(self.win)
        self.assertEqual(['rig_v012.ma'], self.win.labels)

    def test_new_open_and_save_update_the_label(self):
        self.plugin.track_scene(self.win)
        self.assertEqual(['untitled'], self.win.labels)
        messages = sorted(m for m, _ in self.scene_message.callbacks.values())
        self.assertEqual(['new', 'open', 'save'], messages)
        for number, (_, func) in enumerate(
                list(self.scene_message.callbacks.values())):
            self.cmds.scene = 'C:/show/rig_v{}.ma'.format(number)
            func(None)  # Maya passes the client data
            self.assertEqual('rig_v{}.ma'.format(number), self.win.labels[-1])

    def test_stop_removes_every_callback(self):
        stop = self.plugin.track_scene(self.win)
        self.assertEqual(3, len(self.scene_message.callbacks))
        stop()
        self.assertEqual({}, self.scene_message.callbacks)
        stop()  # Closing twice is not an error.

    def test_a_failing_callback_never_reaches_maya(self):
        self.plugin.track_scene(self.win)
        funcs = [func for _, func in self.scene_message.callbacks.values()]

        def gone(text):
            raise RuntimeError('Internal C++ object already deleted.')
        self.win.set_host_label = gone
        for func in funcs:
            func(None)

        def no_scene(*args, **kwargs):
            raise RuntimeError('no scene')
        self.cmds.file = no_scene
        for func in funcs:
            func(None)

    def test_a_refused_callback_leaves_none_behind(self):
        self.scene_message.fail_on = 'save'
        stop = self.plugin.track_scene(self.win)
        self.assertEqual(2, len(self.scene_message.callbacks))
        stop()
        self.assertEqual({}, self.scene_message.callbacks)



BLENDER = os.path.join(os.path.dirname(PLUGIN), os.pardir, os.pardir,
                       'blender', 'nxt_blender.py')


def load_blender():
    """Import nxt_blender.py with a stand-in for bpy."""
    bpy = types.ModuleType('bpy')
    bpy.types = types.SimpleNamespace(
        Operator=type('Operator', (), {}), Menu=type('Menu', (), {}),
        TOPBAR_MT_editor_menus=mock.MagicMock())
    bpy.props = mock.MagicMock()
    bpy.utils = mock.MagicMock()
    bpy.data = types.SimpleNamespace(filepath='')
    bpy.app = mock.MagicMock()
    bpy.app.handlers = types.SimpleNamespace(
        load_post=[], save_post=[], persistent=lambda func: func)
    extras = types.ModuleType('bpy_extras')
    extras.io_utils = types.ModuleType('bpy_extras.io_utils')
    extras.io_utils.ImportHelper = type('ImportHelper', (), {})
    fakes = {'bpy': bpy, 'bpy_extras': extras,
             'bpy_extras.io_utils': extras.io_utils}
    spec = importlib.util.spec_from_file_location('nxt_blender_under_test',
                                                  BLENDER)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, fakes):
        spec.loader.exec_module(module)
    return module


class ShownWindow(FakeWindow):

    def isVisible(self):
        return True

    def close(self):
        pass


class BlenderFileLabel(unittest.TestCase):

    def setUp(self):
        self.addon = load_blender()
        self.bpy = self.addon.bpy
        self.handlers = self.bpy.app.handlers
        self.win = ShownWindow()
        self.addon.__NXT_WINDOWS__.append(self.win)

    def test_it_labels_every_open_editor_with_the_file_name(self):
        self.bpy.data.filepath = '/show/shots/shot_010.blend'
        self.addon._label_windows()
        self.assertEqual(['shot_010.blend'], self.win.labels)

    def test_an_unsaved_file_is_untitled(self):
        self.addon._label_windows()
        self.assertEqual(['untitled'], self.win.labels)

    def test_a_load_and_a_save_update_the_label(self):
        self.addon._track_file()
        self.addon._track_file()  # Opening a second editor adds no more.
        self.assertEqual(1, len(self.handlers.load_post))
        self.assertEqual(1, len(self.handlers.save_post))
        for number, handlers in enumerate((self.handlers.load_post,
                                           self.handlers.save_post)):
            self.bpy.data.filepath = '/show/shot_{}.blend'.format(number)
            handlers[0](None)  # Blender passes the scene
            self.assertEqual('shot_{}.blend'.format(number),
                             self.win.labels[-1])

    def test_closing_the_editors_stops_following_the_file(self):
        self.addon._track_file()
        self.addon.close_nxt()
        self.assertEqual([], self.handlers.load_post)
        self.assertEqual([], self.handlers.save_post)
        self.addon.close_nxt()  # Closing twice is not an error.

    def test_a_failing_handler_never_reaches_blender(self):
        def gone(text):
            raise RuntimeError('Internal C++ object already deleted.')
        self.win.set_host_label = gone
        self.addon._label_windows(None)


if __name__ == '__main__':
    unittest.main()
