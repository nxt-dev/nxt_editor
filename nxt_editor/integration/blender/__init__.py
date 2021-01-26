# Builtin
import os
import shutil
import sys
import atexit

# External
import bpy
from Qt import QtCore, QtWidgets

# Internal
from nxt.constants import NXT_DCC_ENV_VAR
from nxt_editor.integration import NxtIntegration
import nxt_editor

__NXT_INTEGRATION__ = None


class Blender(NxtIntegration):
    def __init__(self):
        super(Blender, self).__init__(name='blender')
        b_major, b_minor, b_patch = bpy.app.version
        if b_major != 2 or b_minor < 80:
            raise RuntimeError('Blender version is not compatible with this '
                               'version of nxt.')
        user_dir = os.path.expanduser('~/AppData/Roaming/Blender '
                                      'Foundation/Blender/'
                                      '{}.{}'.format(b_major, b_minor))
        self.user_dir = user_dir
        nxt_modules = os.path.join(user_dir, 'scripts/addons/modules')
        self.modules_dir = nxt_modules.replace(os.sep, '/')
        self.instance = None
        self.nxt_qapp = QtWidgets.QApplication.instance()

    @classmethod
    def setup(cls):
        self = cls()
        bpy.ops.preferences.addon_disable(module='nxt_' + self.name)
        addons_dir = os.path.join(self.user_dir, 'scripts/addons')
        integration_filepath = self.get_integration_filepath()
        shutil.copy(integration_filepath, addons_dir)
        bpy.ops.preferences.addon_enable(module='nxt_' + self.name)

    @classmethod
    def update(cls):
        self = cls()
        og_cwd = os.getcwd()
        os.chdir(self.modules_dir)
        super(Blender, self).update()
        os.chdir(og_cwd)

    @classmethod
    def launch_nxt(cls):
        self = cls()
        os.environ[NXT_DCC_ENV_VAR] = 'blender'
        global __NXT_INTEGRATION__
        if not __NXT_INTEGRATION__:
            __NXT_INTEGRATION__ = self
        else:
            self = __NXT_INTEGRATION__
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
            if self.nxt_qapp:
                self.nxt_qapp.quit()
                self.nxt_qapp = None

        nxt_win.close_signal.connect(unregister_nxt)
        nxt_win.show()
        atexit.register(nxt_win.close)
        self.instance = nxt_win
        return self

    def quit_nxt(self):
        if self.instance:
            self.instance.close()
            atexit.unregister(self.instance.close)
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

