import os
import shutil
import importlib


class NxtIntegration(object):

    def __init__(self, name):
        self.name = name

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
        if package_name is None:
            package_name = module_name
        if global_name is None:
            global_name = module_name
        args = ['install', package_name]
        self.ensure_pip()
        import pip
        if hasattr(pip, 'main'):
            pip.main(['install', package_name])
        else:
            pip._internal.main(['install', package_name])
        success = self._safe_import_package(package_name=package_name,
                                            global_name=global_name)
        return success

    def _update_package(self, package_name):
        args = ['install', '-U', package_name]
        self.ensure_pip()
        import pip
        if hasattr(pip, 'main'):
            pip.main(args)
        else:
            pip._internal.main(args)
        print('Please restart your DCC or Python interpreter')

    def check_for_nxt_core(self, install=False):
        has_core = self._safe_import_package('nxt')
        if has_core:
            return True
        if not install:
            return has_core
        success = self._install_and_import_package('nxt',
                                                   package_name='nxt-core')
        if not success:
            print('Failed to import and/or install nxt-core')
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
            print('Failed to import and/or install nxt-editor')
        return success

    @staticmethod
    def ensure_pip():
        try:
            import pip
        except ImportError:
            import ensurepip
            ensurepip.bootstrap()
            os.environ.pop('PIP_REQ_TRACKER', None)

    def update(self):
        if self.check_for_nxt_core():
            self._update_package('nxt-core')
        if self.check_for_nxt_editor():
            self._update_package('nxt-editor')


class Blender(NxtIntegration):
    def __init__(self):
        super(Blender, self).__init__(name='blender')
        import bpy
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

    @classmethod
    def setup(cls):
        self = cls()
        import bpy
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
