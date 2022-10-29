"""
Loosely based on the example addon from this repo:
https://github.com/robertguetzkow/blender-python-examples
"""
# Builtin
import os
import sys
import subprocess

# External
import bpy

try:
    # External
    from Qt import QtCore, QtWidgets
    # Internal
    from nxt_editor.constants import NXT_WEBSITE
    from nxt_editor.integration import blender
    nxt_installed = True
except ImportError:
    nxt_installed = False
    NXT_WEBSITE = 'https://nxt-dev.github.io/'

nxt_package_name = 'nxt-editor'

bl_info = {
    "name": "NXT Blender",
    "blender": (3, 4, 0),
    "version": (0, 3, 0),
    "location": "NXT > Open Editor",
    "wiki_url": "https://nxt-dev.github.io/",
    "tracker_url": "https://github.com/nxt-dev/nxt_editor/issues",
    "category": "nxt",
    "description": "NXT is a general purpose code compositor designed for "
                   "rigging, scene assembly, and automation. (This is an "
                   "experimental version of nxt_blender. Save "
                   "early, save often.)",
    "warning": "This addon requires installation of dependencies."
}

b_major, b_minor, b_patch = bpy.app.version
if b_major == 2:
    bl_info["blender"] = (2, 80, 0)
elif b_major != 3:
    raise RuntimeError('Unsupported major Blender version: {}'.format(b_major))


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


class CreateBlenderContext(bpy.types.Operator):
    bl_label = "Create Remote Blender NXT Context"
    bl_idname = "nxt.create_blender_context"

    def execute(self, context):
        global nxt_installed
        if nxt_installed:
            b = blender.__NXT_INTEGRATION__
            if not b:
                b = blender.Blender.launch_nxt()
            b.create_context()
        else:
            show_dependency_warning()
        return {'FINISHED'}


class OpenNxtEditor(bpy.types.Operator):
    bl_label = "Open NXT Editor"
    bl_idname = "nxt.nxt_editor"

    def execute(self, context):
        global nxt_installed
        if nxt_installed:
            blender.Blender.launch_nxt()
        else:
            show_dependency_warning()
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
        layout.operator("nxt.nxt_update_dependencies",
                        text="Update NXT (Requires Blender Restart)")
        layout.separator()
        layout.operator('nxt.create_blender_context', text='Create Blender '
                                                           'Context')
        layout.separator()
        layout.operator("nxt.nxt_about", text="About")

    def menu_draw(self, context):
        self.layout.menu("TOPBAR_MT_nxt")


class NxtInstallDependencies(bpy.types.Operator):
    bl_idname = 'nxt.nxt_install_dependencies'
    bl_label = "Install NXT dependencies (Blender requires elevated permissions)"
    bl_description = ("Downloads and installs the required python packages "
                      "for NXT. Internet connection is required. "
                      "Blender may have to be started with elevated "
                      "permissions in order to install the package. "
                      "Alternatively you can pip install nxt-editor into your "
                      "Blender Python environment.")
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        global nxt_installed
        return not nxt_installed

    def execute(self, context):
        environ_copy = dict(os.environ)
        environ_copy["PYTHONNOUSERSITE"] = "1"
        pkg = 'nxt-editor'
        if b_major == 2:
            exe = bpy.app.binary_path_python
        else:
            exe = sys.executable
        try:
            subprocess.run([exe, "-m", "pip", "install", pkg],
                           check=True, env=environ_copy)
        except subprocess.CalledProcessError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        msg = 'Please restart Blender to finish installing NXT.'
        self.report({"INFO"}, msg)
        show_message(msg, "Installed dependencies!")
        return {"FINISHED"}


class NxtUpdateDependencies(bpy.types.Operator):
    bl_idname = 'nxt.nxt_update_dependencies'
    bl_label = "Update NXT dependencies"
    bl_description = ("Downloads and updates the required python packages "
                      "for NXT. Internet connection is required. "
                      "Blender may have to be started with elevated "
                      "permissions in order to install the package. "
                      "Alternatively you can pip install -U nxt-editor into "
                      "your Blender Python environment.")
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        global nxt_installed
        return nxt_installed

    def execute(self, context):
        try:
            blender.Blender._update_package('nxt-editor')
        except subprocess.CalledProcessError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, 'Please restart Blender to '
                              'finish updating NXT.')
        return {"FINISHED"}


class NxtUninstallDependencies(bpy.types.Operator):
    bl_idname = 'nxt.nxt_uninstall_dependencies'
    bl_label = "Uninstall NXT dependencies"
    bl_description = ("Uninstalls the NXT Python packages. "
                      "Blender may have to be started with elevated "
                      "permissions in order to install the package. "
                      "Alternatively you can pip uninstall nxt-editor from "
                      "your Blender Python environment.")
    bl_options = {"REGISTER", "INTERNAL"}

    @classmethod
    def poll(cls, context):
        global nxt_installed
        return nxt_installed

    def execute(self, context):
        try:
            blender.Blender().uninstall()
        except subprocess.CalledProcessError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        self.report({"INFO"}, 'Please restart Blender to '
                              'finish uninstalling NXT dependencies.')
        return {"FINISHED"}


class NxtDependenciesPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    def draw(self, context):
        layout = self.layout
        layout.operator(NxtInstallDependencies.bl_idname, icon="PLUGIN")
        layout.operator(NxtUpdateDependencies.bl_idname, icon="SCRIPT")
        layout.operator(NxtUninstallDependencies.bl_idname, icon="PANEL_CLOSE")


def show_dependency_warning():

    def draw(self, context):
        layout = self.layout
        lines = [
            f"Please install the missing dependencies for the NXT add-on.",
            "1. Open the preferences (Edit > Preferences > Add-ons).",
            f"2. Search for the \"{bl_info.get('name')}\" add-on.",
            "3. Open the details section of the add-on.",
            f"4. Click on the \"{NxtInstallDependencies.bl_label}\" button.",
            "This will download and install the missing Python packages. "
            "You man need to start Blender with elevated permissions",
            f"Alternatively you can pip install \"{nxt_package_name}\" into "
            f"your Blender Python environment."
        ]

        for line in lines:
            layout.label(text=line)
    bpy.context.window_manager.popup_menu(draw, title='NXT Warning!',
                                          icon="ERROR")


def show_message(message, title, icon='INFO'):

    def draw(self, *args):
        self.layout.label(text=message)

    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)


nxt_operators = (TOPBAR_MT_nxt, OpenNxtEditor, NxtUpdateDependencies,
                 NxtUninstallDependencies, NxtDependenciesPreferences,
                 NxtInstallDependencies, CreateBlenderContext)


def register():
    global nxt_installed
    for cls in nxt_operators:
        bpy.utils.register_class(cls)
    bpy.utils.register_class(AboutNxt)
    bpy.types.TOPBAR_MT_editor_menus.append(TOPBAR_MT_nxt.menu_draw)


def unregister():
    try:
        if blender.__NXT_INTEGRATION__:
            blender.__NXT_INTEGRATION__.quit_nxt()
    except NameError:
        pass
    bpy.types.TOPBAR_MT_editor_menus.remove(TOPBAR_MT_nxt.menu_draw)
    for cls in nxt_operators:
        bpy.utils.unregister_class(cls)
    bpy.utils.unregister_class(AboutNxt)


if __name__ == "__main__":
    register()
