import os
import sys
import subprocess
import importlib

import bpy

b_major, b_minor, b_patch = bpy.app.version


class NxtIntegration(object):

    def __init__(self, name):
        self.name = name

    @staticmethod
    def show_message(message, title, icon='INFO'):

        def draw(self, *args):
            self.layout.label(text=message)

        bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)

    @classmethod
    def setup(cls):
        if not cls.check_for_nxt_core(cls, install=True):
            return False
        if not cls.check_for_nxt_editor(cls, install=True):
            return False

    def get_integration_filepath(self):
        filename = 'nxt_' + self.name + '.py'
        filepath = os.path.join(os.path.dirname(__file__), self.name, filename)
        return filepath

    @staticmethod
    def _safe_import_package(package_name, global_name=None):
        if global_name is None:
            global_name = package_name
        try:
            globals()[global_name] = importlib.import_module(package_name)
        except ImportError:
            return False
        return True

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
        subprocess.run([exe, "-m", "pip", "install", pkg],
                       check=True, env=environ_copy)
        success = self._safe_import_package(package_name=package_name,
                                            global_name=global_name)
        NxtIntegration.show_message('NXT package Installed! '
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
        NxtIntegration.show_message('NXT package updated! '
                                    'Please restart Blender.', 'Success!')

    def check_for_nxt_core(self, install=False):
        has_core = self._safe_import_package('nxt')
        if has_core:
            return True
        if not install:
            return has_core
        success = self._install_and_import_package('nxt',
                                                   package_name='nxt-core')
        if not success:
            NxtIntegration.show_message('Failed to import and/or install '
                                        'nxt-editor.', 'Failed!')
        return success

    def check_for_nxt_editor(self, install=False):
        has_core = self._safe_import_package('nxt_editor')
        if has_core:
            return True
        if not install:
            return has_core
        success = self._install_and_import_package('nxt_editor',
                                                   package_name='nxt-editor')
        if not success:
            NxtIntegration.show_message('Failed to import and/or install '
                                        'nxt-editor.', 'Failed!')
        return success

    def update(self):
        if self.check_for_nxt_core():
            self._update_package('nxt-core')
        if self.check_for_nxt_editor():
            self._update_package('nxt-editor')

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
        if self.check_for_nxt_core():
            self._uninstall_package('nxt-core')
        if self.check_for_nxt_editor():
            self._uninstall_package('nxt-editor')
        NxtIntegration.show_message('NXT was uninstalled, sorry '
                                    'to see you go.', 'Uninstalled!')
        # print('Please restart your DCC or Python interpreter')

    def launch_nxt(self):
        raise NotImplementedError('Your DCC needs it own nxt launch method.')

    def quit_nxt(self):
        raise NotImplementedError('Your DCC needs it own nxt quit method.')

    def create_context(self):
        raise NotImplementedError('Your DCC needs it own method of creating a '
                                  'context.')
