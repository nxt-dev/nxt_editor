# Builtin
import os
import sys

# External
from Qt import QtCore, QtWidgets
import bpy

# Internal
from nxt.constants import NXT_DCC_ENV_VAR
from nxt_editor.constants import NXT_WEBSITE
import nxt_editor.main_window
import nxt_editor
os.environ[NXT_DCC_ENV_VAR] = 'blender'

bl_info = {
    "name": "NXT Blender",
    "blender": (2, 80, 0),
    "version": (0, 1, 0),
    "location": "NXT > Open Editor",
    "wiki_url": "https://nxt-dev.github.io/",
    "tracker_url": "https://github.com/nxt-dev/nxt_editor/issues",
    "category": "nxt",
    "warning": "This is an experimental version of nxt_blender. Save early, "
               "save often."
}


class BLENDER_PLUGIN_VERSION(object):
    plugin_v_data = {'MAJOR': bl_info["version"][0],
                     'MINOR': bl_info["version"][1],
                     'PATCH': bl_info["version"][2]}
    MAJOR = plugin_v_data['MAJOR']
    MINOR = plugin_v_data['MINOR']
    PATCH = plugin_v_data['PATCH']
    VERSION_TUPLE = (MAJOR, MINOR, PATCH)
    VERSION_STR = '.'.join(str(v) for v in VERSION_TUPLE)
    VERSION = VERSION_STR


__NXT_INSTANCE__ = None
__NXT_CREATED_QAPP__ = None


class OpenNxtEditor(bpy.types.Operator):
    bl_label = "Open NXT Editor"
    bl_idname = "nxt.nxt_editor"

    def execute(self, context):
        global __NXT_INSTANCE__
        global __NXT_CREATED_QAPP__
        if __NXT_INSTANCE__:
            __NXT_INSTANCE__.show()
            return
        if not __NXT_CREATED_QAPP__:
            nxt_win = nxt_editor.launch_editor()
        else:
            nxt_win = nxt_editor.show_new_editor()
        if 'win32' in sys.platform:
            # gives nxt it's own entry on taskbar
            nxt_win.setWindowFlags(QtCore.Qt.Window)

        def unregister_nxt():
            global __NXT_INSTANCE__
            __NXT_INSTANCE__ = None

        nxt_win.close_signal.connect(unregister_nxt)
        nxt_win.show()
        __NXT_INSTANCE__ = nxt_win
        return {'FINISHED'}


class UpdateNxt(bpy.types.Operator):
    bl_label = "Update NXT"
    bl_idname = "nxt.nxt_update"

    def execute(self, context):
        import nxt_editor.integration
        nxt_editor.integration.Blender.update()
        return {'FINISHED'}


class AboutNxt(bpy.types.Operator):
    bl_label = "Update NXT"
    bl_idname = "nxt.nxt_about"

    def execute(self, context):
        import webbrowser
        webbrowser.open_new(NXT_WEBSITE)
        return {'FINISHED'}


class TOPBAR_MT_nxt(bpy.types.Menu):
    bl_label = "NXT"

    def draw(self, context):
        layout = self.layout
        layout.operator("nxt.nxt_editor", text="Open Editor")
        layout.separator()
        layout.operator("nxt.nxt_update", text="Update NXT (Requires Blender "
                                               "Restart)")
        layout.separator()
        layout.operator("nxt.nxt_about", text="About")

    def menu_draw(self, context):
        self.layout.menu("TOPBAR_MT_nxt")


nxt_menu_operators = (TOPBAR_MT_nxt, OpenNxtEditor)


def register():
    global __NXT_CREATED_QAPP__
    existing = QtWidgets.QApplication.instance()
    if existing:
        __NXT_CREATED_QAPP__ = False
    else:
        __NXT_CREATED_QAPP__ = True
        nxt_editor._new_qapp()
    bpy.utils.register_class(TOPBAR_MT_nxt)
    bpy.utils.register_class(OpenNxtEditor)
    bpy.utils.register_class(AboutNxt)
    bpy.utils.register_class(UpdateNxt)
    bpy.types.TOPBAR_MT_editor_menus.append(TOPBAR_MT_nxt.menu_draw)


def unregister():
    global __NXT_CREATED_QAPP__
    if __NXT_CREATED_QAPP__:
        QtWidgets.QApplication.instance().quit()
        __NXT_CREATED_QAPP__ = False
    bpy.types.TOPBAR_MT_editor_menus.remove(TOPBAR_MT_nxt.menu_draw)
    bpy.utils.unregister_class(TOPBAR_MT_nxt)
    bpy.utils.unregister_class(OpenNxtEditor)
    bpy.utils.unregister_class(AboutNxt)
    bpy.utils.unregister_class(UpdateNxt)


if __name__ == "__main__":
    register()
