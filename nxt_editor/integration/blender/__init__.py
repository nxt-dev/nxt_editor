# Builtin
import atexit
import os
import shutil
import subprocess
import sys

# External
import bpy
from Qt import QtCore, QtWidgets

# Internal
from nxt.constants import NXT_DCC_ENV_VAR
from nxt_editor.integration import NxtIntegration
import nxt_editor

__NXT_INTEGRATION__ = None
b_major, b_minor, b_patch = bpy.app.version


class Blender(NxtIntegration):
    def __init__(self):
        super(Blender, self).__init__(name='blender')
        b_major, b_minor, b_patch = bpy.app.version
        if b_major == 2 and b_minor < 80:
            raise RuntimeError('Blender version is not compatible with this '
                               'version of nxt.')
        if b_major == 2:
            addons_dir = bpy.utils.user_resource('SCRIPTS', 'addons')
        else:
            addons_dir = os.path.join(bpy.utils.user_resource('SCRIPTS'),
                                      '/addons')
        self.addons_dir = addons_dir.replace(os.sep, '/')
        self.instance = None
        self.nxt_qapp = QtWidgets.QApplication.instance()

    @staticmethod
    def show_message(message, title, icon='INFO'):

        def draw(self, *args):
            self.layout.label(text=message)

        bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)

    @classmethod
    def setup(cls):
        self = cls()
        bpy.ops.preferences.addon_disable(module='nxt_' + self.name)
        integration_filepath = self.get_integration_filepath()
        shutil.copy(integration_filepath, self.addons_dir)
        bpy.ops.preferences.addon_enable(module='nxt_' + self.name)

    def _install_and_import_package(self, module_name, package_name=None,
                                    global_name=None):
        """Calls a subprocess to pip install the given package name and then
        attempts to import the new package.

        :param module_name: Desired module to import after install
        :param package_name: pip package name
        :param global_name: Global name to access the module if different
        than the module name.
        :raises: subprocess.CalledProcessError
        :return: bool
        """
        if package_name is None:
            package_name = module_name
        if global_name is None:
            global_name = module_name
        environ_copy = dict(os.environ)
        environ_copy["PYTHONNOUSERSITE"] = "1"
        pkg = 'nxt-editor'
        if b_major == 2:
            exe = bpy.app.binary_path_python
        else:
            exe = sys.executable
        print('INSTLALING: ' + pkg)
        subprocess.run([exe, "-m", "pip", "install", pkg],
                       check=True, env=environ_copy)
        success = self._safe_import_package(package_name=package_name,
                                            global_name=global_name)
        Blender.show_message('NXT package Installed! '
                             'You may need to restart Blender.',
                             'Success!')
        return success

    @staticmethod
    def _update_package(package_name):
        """Calls a subprocess to pip update the given package name.

        :param package_name: pip package name
        :raises: subprocess.CalledProcessError
        :return: None
        """
        environ_copy = dict(os.environ)
        environ_copy["PYTHONNOUSERSITE"] = "1"
        if b_major == 2:
            exe = bpy.app.binary_path_python
        else:
            exe = sys.executable
        subprocess.run([exe, "-m", "pip", "install", "-U",
                        package_name], check=True, env=environ_copy)
        Blender.show_message('NXT package updated! '
                             'Please restart Blender.', 'Success!')

    @classmethod
    def update(cls):
        self = cls()
        og_cwd = os.getcwd()
        super(Blender, self).update()
        os.chdir(og_cwd)
        addon_file = os.path.join(os.path.dirname(__file__), 'nxt_blender.py')
        shutil.copy(addon_file, self.addons_dir)

    @classmethod
    def launch_nxt(cls):
        global __NXT_INTEGRATION__
        if __NXT_INTEGRATION__:
            self = __NXT_INTEGRATION__
        else:
            self = cls()
            __NXT_INTEGRATION__ = self
        os.environ[NXT_DCC_ENV_VAR] = 'blender'
        if self.instance:
            self.instance.show()
            return
        if not self.nxt_qapp:
            self.nxt_qapp = nxt_editor._new_qapp()
            nxt_win = nxt_editor.show_new_editor(start_rpc=False)
        else:
            nxt_win = nxt_editor.show_new_editor(start_rpc=False)
        if 'win32' in sys.platform:
            # gives nxt it's own entry on taskbar
            nxt_win.setWindowFlags(QtCore.Qt.Window)

        def unregister_nxt():
            self.instance = None

        nxt_win.close_signal.connect(unregister_nxt)
        nxt_win.show()
        # Forces keyboard focus
        nxt_win.activateWindow()
        atexit.register(nxt_win.close)
        self.instance = nxt_win
        return self

    def quit_nxt(self):
        if self.instance:
            atexit.unregister(self.instance.close)
            self.instance.close()
        if self.nxt_qapp:
            self.nxt_qapp.quit()
        global __NXT_INTEGRATION__
        __NXT_INTEGRATION__ = None

    def create_context(self):
        placeholder_txt = 'Blender {}.{}'.format(*bpy.app.version)
        args = ['-noaudio', '--background', '--python']
        self.instance.create_remote_context(placeholder_txt,
                                            interpreter_exe=bpy.app.binary_path,
                                            exe_script_args=args)

    def check_for_nxt_core(self, install=False):
        success = super(Blender, self).check_for_nxt_core(install=install)
        if not success:
            Blender.show_message('Failed to import and/or install '
                                 'nxt-editor.', 'Failed!')
        return success

    @staticmethod
    def _uninstall_package(package_name):
        """Calls a subprocess to pip uninstall the given package name. Will
        NOT prompt the user to confrim uninstall.

        :param package_name: pip package name
        :raises: subprocess.CalledProcessError
        :return: None
        """
        environ_copy = dict(os.environ)
        environ_copy["PYTHONNOUSERSITE"] = "1"
        if b_major == 2:
            exe = bpy.app.binary_path_python
        else:
            exe = sys.executable
        subprocess.run([exe, "-m", "pip", "uninstall",
                        package_name, '-y'], check=True, env=environ_copy)

    def uninstall(self):
        super(Blender, self).uninstall()
        Blender.show_message('NXT was uninstalled, sorry '
                             'to see you go.', 'Uninstalled!')
