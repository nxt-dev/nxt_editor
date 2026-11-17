"""A host plugin can be told to leave nxt's own menu out.

Studios that open the editor from their pipeline menu ended up patching the
plug-in to comment the menu out, and redoing the patch on every update. The
env var NXT_NO_MENU does the same without touching the file, by one rule in
Maya, Blender and Unreal, and each still has a way to open the editor:
the nxt_ui command, bpy.ops.nxt.open_editor() and
nxt_unreal_menu.launch_nxt_editor().

Nothing here needs a host. Each plugin is loaded by its path with stand ins
for the host's own modules, and the tests look at what it asked them for.
"""
# Built-in
import importlib.util
import os
import sys
import types
import unittest
from unittest import mock

# Internal
from nxt_editor import integration
# What the maya plug-in imports, imported here first, so the sys.modules a
# test puts back still holds the same modules every other test uses.
import nxt.remote.nxt_socket  # noqa: F401
import nxt_editor.main_window  # noqa: F401

EDITOR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_DIR = os.path.dirname(EDITOR_DIR)
INTEGRATION_DIR = os.path.join(EDITOR_DIR, 'integration')
MAYA_PLUGIN = os.path.join(INTEGRATION_DIR, 'maya', 'plug-ins',
                           'nxt_maya.py')
BLENDER_ADDON = os.path.join(INTEGRATION_DIR, 'blender', 'nxt_blender.py')
UNREAL_MENU = os.path.join(INTEGRATION_DIR, 'unreal', 'Content', 'Python',
                           'nxt_unreal_menu.py')


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_maya():
    maya = types.ModuleType('maya')
    maya.cmds = mock.MagicMock(name='cmds')
    maya.mel = mock.MagicMock(name='mel')
    api = types.ModuleType('maya.api')
    api.OpenMaya = mock.MagicMock(name='OpenMaya')
    api.OpenMaya.MPxCommand = type('MPxCommand', (), {})
    maya.api = api
    return {'maya': maya, 'maya.cmds': maya.cmds, 'maya.mel': maya.mel,
            'maya.api': api, 'maya.api.OpenMaya': api.OpenMaya}


def fake_blender():
    bpy = types.ModuleType('bpy')
    bpy.types = types.SimpleNamespace(
        Operator=type('Operator', (), {}), Menu=type('Menu', (), {}),
        TOPBAR_MT_editor_menus=mock.MagicMock(name='TOPBAR_MT_editor_menus'))
    bpy.props = mock.MagicMock(name='props')
    bpy.utils = mock.MagicMock(name='utils')
    bpy.app = mock.MagicMock(name='app')
    extras = types.ModuleType('bpy_extras')
    io_utils = types.ModuleType('bpy_extras.io_utils')
    io_utils.ImportHelper = type('ImportHelper', (), {})
    extras.io_utils = io_utils
    return {'bpy': bpy, 'bpy_extras': extras,
            'bpy_extras.io_utils': io_utils}


class HostTest(unittest.TestCase):
    """A clean NXT_NO_MENU, and the sys.path the Blender add-on changes,
    both put back afterwards."""

    def setUp(self):
        self.path_before = list(sys.path)
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(integration.NO_MENU_ENV_VAR, None)
        # The plugins keep the files they load by path in sys.modules.
        modules = mock.patch.dict(sys.modules)
        modules.start()
        self.addCleanup(modules.stop)
        for name in ('nxt_qt_deps', 'nxt_integration'):
            sys.modules.pop(name, None)

    def tearDown(self):
        sys.path[:] = self.path_before

    def no_menu(self):
        os.environ[integration.NO_MENU_ENV_VAR] = '1'


class MenuRule(unittest.TestCase):

    def setUp(self):
        self.before = os.environ.pop(integration.NO_MENU_ENV_VAR, None)

    def tearDown(self):
        os.environ.pop(integration.NO_MENU_ENV_VAR, None)
        if self.before is not None:
            os.environ[integration.NO_MENU_ENV_VAR] = self.before

    def test_menu_is_wanted_by_default(self):
        self.assertTrue(integration.wants_menu())

    def test_set_means_no_menu(self):
        for value in ('1', 'true', 'True', 'yes', 'anything'):
            os.environ[integration.NO_MENU_ENV_VAR] = value
            self.assertFalse(integration.wants_menu(), value)

    def test_falsy_strings_keep_the_menu(self):
        # NXT_NO_MENU=0 reads as "no, I do want it" to anyone setting it.
        for value in ('', '0', 'false', 'False', 'no', 'off', ' 0 '):
            os.environ[integration.NO_MENU_ENV_VAR] = value
            self.assertTrue(integration.wants_menu(), repr(value))

    def test_the_rule_loads_without_qt(self):
        # Blender and Unreal load it by path before Qt may be installed.
        with mock.patch.dict(sys.modules, {'Qt': None, 'PySide6': None}):
            module = load(os.path.join(INTEGRATION_DIR, '__init__.py'),
                          'nxt_integration_without_qt')
        os.environ[integration.NO_MENU_ENV_VAR] = '1'
        self.assertFalse(module.wants_menu())


class Maya(HostTest):

    def initialize(self):
        fakes = fake_maya()
        with mock.patch.dict(sys.modules, fakes):
            plugin = load(MAYA_PLUGIN, 'nxt_maya_under_test')
            fn = plugin.om.MFnPlugin.return_value
            plugin.initializePlugin(mock.MagicMock())
        return plugin, fakes['maya.cmds'], fn

    def test_menu_by_default(self):
        _, cmds, fn = self.initialize()
        fn.registerCommand.assert_called_once()
        cmds.menu.assert_called_once()
        labels = [c.args[0] for c in cmds.menuItem.call_args_list]
        self.assertIn('Open Editor', labels)

    def test_no_menu_keeps_the_command(self):
        self.no_menu()
        _, cmds, fn = self.initialize()
        fn.registerCommand.assert_called_once()
        self.assertEqual(fn.registerCommand.call_args.args[0], 'nxt_ui')
        cmds.menu.assert_not_called()
        cmds.menuItem.assert_not_called()


class Blender(HostTest):

    def register(self):
        fakes = fake_blender()
        with mock.patch.dict(sys.modules, fakes):
            addon = load(BLENDER_ADDON, 'nxt_blender_under_test')
            addon.register()
        return addon, fakes['bpy']

    def test_menu_by_default(self):
        addon, bpy = self.register()
        bpy.types.TOPBAR_MT_editor_menus.append.assert_called_once_with(
            addon._draw_menu)
        addon.unregister()
        bpy.types.TOPBAR_MT_editor_menus.remove.assert_called_once()

    def test_no_menu_keeps_the_operators(self):
        self.no_menu()
        addon, bpy = self.register()
        bpy.types.TOPBAR_MT_editor_menus.append.assert_not_called()
        registered = [c.args[0] for c in
                      bpy.utils.register_class.call_args_list]
        # bpy.ops.nxt.open_editor() opens the editor without the menu.
        self.assertIn(addon.NXT_OT_open_editor, registered)
        self.assertEqual(addon.NXT_OT_open_editor.bl_idname,
                         'nxt.open_editor')
        addon.unregister()
        bpy.types.TOPBAR_MT_editor_menus.remove.assert_not_called()


class Unreal(HostTest):

    def start(self):
        unreal = mock.MagicMock(name='unreal')
        with mock.patch.dict(sys.modules, {'unreal': unreal}):
            menu = load(UNREAL_MENU, 'nxt_unreal_menu_under_test')
        # The plugin carries nxt_editor beside this file. Here it is the
        # source tree, and the bundled copy must not replace nxt in
        # sys.modules for the rest of the run.
        menu.HERE = REPO_DIR
        menu._put_first = lambda path: None
        menu.is_nxt_available = lambda: True
        menu.startup()
        return menu, unreal

    def added(self, unreal):
        menus = unreal.ToolMenus.get.return_value
        nxt_menu = menus.find_menu.return_value
        return nxt_menu.add_menu_entry.call_count

    def test_menu_by_default(self):
        menu, unreal = self.start()
        unreal.ToolMenus.get.assert_called()
        # Open Editor.
        self.assertEqual(self.added(unreal), 1)

    def test_no_menu(self):
        self.no_menu()
        menu, unreal = self.start()
        unreal.ToolMenus.get.assert_not_called()
        # What opens the editor without the menu is still there to call.
        self.assertTrue(callable(menu.launch_nxt_editor))

    def test_installing_qt_does_not_bring_the_menu_back(self):
        # install_qt refreshes the menu once PySide6 is in.
        self.no_menu()
        menu, unreal = self.start()
        menu.refresh_nxt_menu()
        unreal.ToolMenus.get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
