"""Where Blender and Unreal look for, and install, PySide6.

Neither ships Qt. It is installed once into a folder of its own, named for
the python version because compiled extensions only load in the python they
were built for, and a studio can point every machine at a shared copy.

A host running an older Microsoft C++ runtime, as Blender 4.2 to 4.5 do,
crashes loading the newest PySide6, so it is given an older one in a folder
of its own.
"""
# Builtin
import os
import sys
import tempfile
import unittest
from unittest import mock

# Internal
from nxt_editor.integration import qt_deps

PY_TAG = 'py%d%d' % sys.version_info[:2]


def current_runtime():
    """As if the host had a current C++ runtime loaded, or none at all.

    The tests about folder names are not about the runtime, and the python
    running them may have loaded an older one, which adds a suffix.
    """
    return mock.patch.object(qt_deps, 'loaded_crt_version', lambda: None)


class TestQtDeps(unittest.TestCase):
    def test_env_var_wins(self):
        with mock.patch.dict(os.environ, {'NXT_QT_DEPS': '/shared/qt'}),                 current_runtime():
            self.assertEqual(qt_deps.deps_dir(),
                             os.path.join('/shared/qt', PY_TAG))

    def test_defaults_under_the_nxt_user_dir(self):
        env = {'NXT_USER_DIR': '/home/artist/nxt'}
        with mock.patch.dict(os.environ, env), current_runtime():
            os.environ.pop('NXT_QT_DEPS', None)
            self.assertEqual(qt_deps.deps_dir(),
                             os.path.join('/home/artist/nxt', 'deps', PY_TAG))

    def test_installs_into_the_deps_dir_not_the_host(self):
        with mock.patch.dict(os.environ, {'NXT_QT_DEPS': '/shared/qt'}),                 current_runtime():
            cmd = qt_deps.install_command()
        self.assertEqual(cmd[1:4], ['-m', 'pip', 'install'])
        self.assertIn('--target', cmd)
        self.assertEqual(cmd[cmd.index('--target') + 1],
                         os.path.join('/shared/qt', PY_TAG))
        self.assertEqual(cmd[-1], qt_deps.REQUIREMENT)

    def test_finds_python_when_the_host_is_the_executable(self):
        # Unreal's sys.executable is the editor itself.
        tmp = tempfile.mkdtemp()
        name = 'python.exe' if sys.platform == 'win32' else 'python3'
        python = os.path.join(tmp, name)
        open(python, 'w').close()
        with mock.patch.object(qt_deps.sys, 'executable',
                               os.path.join(tmp, 'UnrealEditor.exe')), \
                mock.patch.object(qt_deps.sys, 'prefix', tmp):
            self.assertEqual(qt_deps.python_executable(), python)
        os.remove(python)
        os.rmdir(tmp)

    def test_an_old_runtime_gets_its_own_folder_and_an_older_pyside(self):
        with mock.patch.dict(os.environ, {'NXT_QT_DEPS': '/shared/qt'}), \
                mock.patch.object(qt_deps, 'loaded_crt_version',
                                  lambda: (14, 29, 30139)):
            self.assertEqual(qt_deps.deps_dir(),
                             os.path.join('/shared/qt', PY_TAG + '-crt14.29'))
            self.assertEqual(qt_deps.requirement(),
                             qt_deps.LEGACY_CRT_REQUIREMENT)
            self.assertEqual(qt_deps.install_command()[-1],
                             qt_deps.LEGACY_CRT_REQUIREMENT)

    def test_a_current_runtime_gets_the_usual_folder(self):
        for crt in ((14, 44, 35211), None):
            with mock.patch.dict(os.environ, {'NXT_QT_DEPS': '/shared/qt'}), \
                    mock.patch.object(qt_deps, 'loaded_crt_version',
                                      lambda: crt):
                self.assertEqual(qt_deps.deps_dir(),
                                 os.path.join('/shared/qt', PY_TAG))
                self.assertEqual(qt_deps.requirement(), qt_deps.REQUIREMENT)

    def test_the_runtime_is_read_without_failing(self):
        # None outside Windows, or where no C++ runtime is loaded yet.
        crt = qt_deps.loaded_crt_version()
        self.assertTrue(crt is None or (len(crt) == 3 and crt[0] >= 14))

    def test_add_to_path_leaves_an_existing_qt_alone(self):
        before = list(sys.path)
        self.assertTrue(qt_deps.add_to_path())
        self.assertEqual(sys.path, before)


if __name__ == '__main__':
    unittest.main()
