"""Optional components: where they go, what is there, and putting them in.

PySide6 for the hosts with no Qt, and jedi for every host, installed by pip
into a folder of nxt's own. Nothing here runs pip; where a test needs an
install it writes what pip would have, a package and its dist-info.
"""
# Builtin
import ast
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

# Internal
from nxt_editor.integration import optional_deps as deps
from nxt_editor.integration import qt_deps

PY_TAG = 'py%d%d' % sys.version_info[:2]
SETUP_PY = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'setup.py')
ENV_VARS = (deps.DEPS_ENV_VAR, deps.LEGACY_DEPS_ENV_VAR, deps.WHEELS_ENV_VAR,
            deps.DCC_ENV_VAR)


def make_dist(folder, name, version, requires=(), files=None):
    """What pip --target leaves for a package: its code and its dist-info,
    with a RECORD of the files.
    """
    files = files if files is not None else [name + '/__init__.py']
    os.makedirs(folder, exist_ok=True)
    for each in files:
        path = os.path.join(folder, each)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as handle:
            handle.write('__version__ = {!r}\n'.format(version))
    info = os.path.join(folder, '{}-{}.dist-info'.format(name, version))
    os.makedirs(info, exist_ok=True)
    with open(os.path.join(info, 'METADATA'), 'w') as handle:
        handle.write('Metadata-Version: 2.1\nName: {}\nVersion: {}\n'.format(
            name, version))
        for line in requires:
            handle.write('Requires-Dist: {}\n'.format(line))
    record = list(files) + ['{}-{}.dist-info/METADATA'.format(name, version),
                            '{}-{}.dist-info/RECORD'.format(name, version)]
    with open(os.path.join(info, 'RECORD'), 'w') as handle:
        handle.write(''.join('{},,\n'.format(r) for r in record))
    return info


def make_jedi(folder, version='0.20.1', parso='0.8.7'):
    make_dist(folder, 'jedi', version, ['parso>=0.8.4,<0.9',
                                        'pytest; extra == "testing"'])
    make_dist(folder, 'parso', parso)


class Isolated(unittest.TestCase):
    """Every test gets an empty nxt user dir and none of the variables."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_optional_deps_')
        self.user = os.path.join(self.tmp, 'user')
        env = {k: v for k, v in os.environ.items() if k not in ENV_VARS}
        env[deps.USER_DIR_ENV_VAR] = self.user
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()
        self.path = list(sys.path)
        # The tests are not about the C++ runtime of the python running them.
        self.crt = mock.patch.object(deps, 'loaded_crt_version', lambda: None)
        self.crt.start()

    def tearDown(self):
        self.crt.stop()
        self.env.stop()
        sys.path[:] = self.path
        shutil.rmtree(self.tmp, ignore_errors=True)

    @property
    def pure(self):
        return os.path.join(self.user, 'deps', 'pure')


class TestRegistry(unittest.TestCase):

    def setup_requirements(self):
        tree = ast.parse(open(SETUP_PY).read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(
                    node.func, 'attr', '') == 'setup':
                return {k.arg: ast.literal_eval(k.value)
                        for k in node.keywords
                        if k.arg in ('install_requires', 'extras_require')}
        raise AssertionError('No setup() call in setup.py')

    def test_the_ranges_match_setup_py(self):
        found = self.setup_requirements()
        for comp in deps.COMPONENTS:
            listed = (found['extras_require'][comp.setup_extra]
                      if comp.setup_extra else found['install_requires'])
            specs = {deps.normalize(deps.split_requirement(r)[0]):
                     deps.split_requirement(r)[1] for r in listed}
            self.assertEqual(specs[deps.normalize(comp.setup_name)],
                             comp.spec, comp)

    def test_each_has_what_the_dialog_shows(self):
        for comp in deps.COMPONENTS:
            self.assertTrue(comp.name and comp.description and comp.size)
            self.assertIs(deps.component(comp.id), comp)
        self.assertTrue(deps.PYSIDE6.compiled)
        self.assertFalse(deps.JEDI.compiled)
        self.assertTrue(deps.JEDI.needed_in('maya'))
        self.assertFalse(deps.PYSIDE6.needed_in('maya'))
        self.assertTrue(deps.PYSIDE6.needed_in('blender'))

    def test_qt_deps_installs_the_same_pyside(self):
        self.assertEqual(qt_deps.REQUIREMENT, deps.PYSIDE6.requirement)
        self.assertEqual(qt_deps.LEGACY_CRT_REQUIREMENT,
                         deps.PYSIDE6.legacy_requirement)
        self.assertIs(qt_deps.optional_deps, deps)


class TestVersions(unittest.TestCase):

    def test_in_range(self):
        self.assertTrue(deps.in_range('0.19.0', '>=0.19,<0.21'))
        self.assertTrue(deps.in_range('0.20.1', '>=0.19,<0.21'))
        self.assertFalse(deps.in_range('0.18.2', '>=0.19,<0.21'))
        self.assertFalse(deps.in_range('0.21', '>=0.19,<0.21'))
        self.assertTrue(deps.in_range('6.11.2', '>=6,<6.12'))
        self.assertFalse(deps.in_range('6.12.0', '>=6,<6.12'))
        self.assertFalse(deps.in_range('', '>=6'))

    def test_too_old(self):
        self.assertTrue(deps.too_old('0.18.2', '>=0.19,<0.21'))
        self.assertFalse(deps.too_old('0.21.0', '>=0.19,<0.21'))

    def test_a_range_reads_as_words(self):
        self.assertEqual(deps.describe_range('>=0.19,<0.21'),
                         '0.19 or newer, before 0.21')


class TestFolders(Isolated):

    def test_defaults_under_the_nxt_user_dir(self):
        self.assertEqual(deps.folder(deps.JEDI), self.pure)
        self.assertEqual(deps.folder(deps.PYSIDE6),
                         os.path.join(self.user, 'deps', PY_TAG))

    def test_nxt_deps_wins_and_the_old_name_still_works(self):
        os.environ[deps.LEGACY_DEPS_ENV_VAR] = os.path.join(self.tmp, 'qt')
        self.assertEqual(deps.install_root(), os.path.join(self.tmp, 'qt'))
        os.environ[deps.DEPS_ENV_VAR] = os.path.join(self.tmp, 'shared')
        self.assertEqual(deps.install_root(),
                         os.path.join(self.tmp, 'shared'))
        self.assertEqual(deps.folder(deps.JEDI),
                         os.path.join(self.tmp, 'shared', 'pure'))
        # The user's own is still looked in, after the shared one.
        self.assertEqual(deps.roots(), [os.path.join(self.tmp, 'shared'),
                                        os.path.join(self.user, 'deps')])

    def test_a_read_only_shared_folder_sends_installs_home(self):
        shared = os.path.join(self.tmp, 'shared')
        os.makedirs(shared)
        os.environ[deps.DEPS_ENV_VAR] = shared
        with mock.patch.object(deps, 'writable', lambda path: False):
            self.assertEqual(deps.install_root(),
                             os.path.join(self.user, 'deps'))

    def test_an_old_runtime_gets_its_own_compiled_folder(self):
        crt = (14, 29, 30139)
        self.assertEqual(deps.folder(deps.PYSIDE6, crt=crt),
                         os.path.join(self.user, 'deps', PY_TAG + '-crt14.29'))
        self.assertEqual(deps.requirement(deps.PYSIDE6, crt),
                         deps.PYSIDE6.legacy_requirement)
        # Pure python does not care.
        self.assertEqual(deps.folder(deps.JEDI, crt=crt), self.pure)
        self.assertEqual(deps.requirement(deps.JEDI, crt),
                         deps.JEDI.requirement)

    def test_writable(self):
        self.assertTrue(deps.writable(os.path.join(self.tmp, 'not', 'yet')))
        self.assertEqual([], os.listdir(self.tmp))


class TestCommand(Isolated):

    def test_installs_into_the_folder_not_the_host(self):
        cmd = deps.install_command(deps.JEDI, '/stage')
        self.assertEqual(cmd[1:4], ['-m', 'pip', 'install'])
        self.assertEqual(cmd[cmd.index('--target') + 1], '/stage')
        self.assertEqual(cmd[-1], deps.JEDI.requirement)
        self.assertNotIn('--no-index', cmd)
        self.assertNotIn('--progress-bar', cmd)

    def test_progress_lines_are_asked_for(self):
        cmd = deps.install_command(deps.JEDI, '/stage', progress=True)
        self.assertEqual(cmd[cmd.index('--progress-bar') + 1], 'raw')

    def test_offline_installs_only_from_the_wheels_folders(self):
        first = os.path.join(self.tmp, 'wheels')
        second = os.path.join(self.tmp, 'more')
        os.environ[deps.WHEELS_ENV_VAR] = os.pathsep.join([first, second])
        cmd = deps.install_command(deps.JEDI, '/stage')
        self.assertIn('--no-index', cmd)
        links = [cmd[i + 1] for i, arg in enumerate(cmd)
                 if arg == '--find-links']
        self.assertEqual(links, [first, second])
        self.assertEqual(cmd[-1], deps.JEDI.requirement)

    def test_pip_runs_clean(self):
        env = deps.pip_environment({'PYTHONPATH': 'x', 'PATH': 'p'})
        self.assertNotIn('PYTHONPATH', env)
        self.assertEqual(env['PYTHONNOUSERSITE'], '1')
        self.assertEqual(env['PATH'], 'p')

    def test_finds_python_when_the_host_is_the_executable(self):
        name = 'python.exe' if sys.platform == 'win32' else 'python3'
        python = os.path.join(self.tmp, name)
        open(python, 'w').close()
        with mock.patch.object(deps.sys, 'executable',
                               os.path.join(self.tmp, 'UnrealEditor.exe')), \
                mock.patch.object(deps.sys, 'prefix', self.tmp):
            self.assertEqual(deps.python_executable(), python)

    def test_finds_mayapy_beside_maya(self):
        bin_dir = os.path.join(self.tmp, 'bin')
        os.makedirs(bin_dir)
        mayapy = os.path.join(
            bin_dir, 'mayapy.exe' if sys.platform == 'win32' else 'mayapy')
        open(mayapy, 'w').close()
        with mock.patch.object(deps.sys, 'executable',
                               os.path.join(bin_dir, 'maya.exe')), \
                mock.patch.object(deps.sys, 'prefix',
                                  os.path.join(self.tmp, 'Python')):
            self.assertEqual(deps.python_executable(), mayapy)


class TestStatus(Isolated):

    def test_not_installed(self):
        status = deps.status(deps.JEDI, 'maya')
        if status.state == deps.Status.ELSEWHERE:
            self.skipTest('this python has jedi of its own')
        self.assertEqual(status.state, deps.Status.NOT_INSTALLED)
        self.assertEqual(status.folder, self.pure)

    def test_installed(self):
        make_jedi(self.pure)
        status = deps.status(deps.JEDI, 'maya')
        self.assertEqual(status.state, deps.Status.INSTALLED)
        self.assertEqual(status.version, '0.20.1')
        self.assertEqual(status.folder, self.pure)

    def test_too_old_and_too_new_want_an_update(self):
        make_jedi(self.pure, '0.18.2')
        status = deps.status(deps.JEDI, 'maya')
        self.assertEqual(status.state, deps.Status.UPDATE)
        self.assertTrue(status.too_old)
        shutil.rmtree(self.pure)
        make_jedi(self.pure, '0.21.0')
        status = deps.status(deps.JEDI, 'maya')
        self.assertEqual(status.state, deps.Status.UPDATE)
        self.assertFalse(status.too_old)

    def test_a_studio_folder_that_is_read_only_is_managed(self):
        shared = os.path.join(self.tmp, 'studio')
        make_jedi(os.path.join(shared, 'pure'), '0.18.2')
        os.environ[deps.DEPS_ENV_VAR] = shared
        real = deps.writable
        with mock.patch.object(deps, 'writable', lambda path: (
                False if path.startswith(shared) else real(path))):
            status = deps.status(deps.JEDI, 'maya')
        self.assertEqual(status.state, deps.Status.MANAGED)
        self.assertTrue(status.out_of_range)

    def test_the_studio_copy_wins_over_the_users(self):
        shared = os.path.join(self.tmp, 'studio')
        make_jedi(os.path.join(shared, 'pure'), '0.19.2')
        make_jedi(self.pure, '0.20.1')
        os.environ[deps.DEPS_ENV_VAR] = shared
        self.assertEqual(deps.installed(deps.JEDI)[0], '0.19.2')

    def test_qt_is_not_needed_where_the_host_has_it(self):
        for host in ('maya', 'standalone'):
            self.assertEqual(deps.status(deps.PYSIDE6, host).state,
                             deps.Status.NOT_NEEDED)

    def test_qt_from_elsewhere_in_a_host_that_needs_it(self):
        if not deps.has_qt():
            self.skipTest('needs PySide6')
        import PySide6  # noqa: F401
        status = deps.status(deps.PYSIDE6, 'blender')
        self.assertEqual(status.state, deps.Status.ELSEWHERE)

    def test_qt_loaded_from_nxt_folder_is_shown_and_updatable(self):
        folder = os.path.join(self.user, 'deps', PY_TAG)
        make_dist(folder, 'pyside6_essentials', '6.12.1',
                  files=['PySide6/__init__.py'])
        fake = mock.Mock(__file__=os.path.join(folder, 'PySide6',
                                               '__init__.py'))
        with mock.patch.dict(sys.modules, {'PySide6': fake}):
            # Even where NXT_DCC does not say it is a host without Qt.
            status = deps.status(deps.PYSIDE6, 'standalone')
        self.assertEqual(status.state, deps.Status.UPDATE)
        self.assertEqual(status.version, '6.12.1')
        self.assertFalse(status.too_old)


class TestPath(Isolated):

    def test_the_pure_folder_is_appended(self):
        make_jedi(self.pure)
        added = deps.add_to_path()
        self.assertEqual(added, [self.pure])
        self.assertEqual(sys.path[-1], self.pure)
        # Not twice.
        self.assertEqual(deps.add_to_path(), [])

    def test_nothing_is_added_when_nothing_is_installed(self):
        before = list(sys.path)
        self.assertEqual(deps.add_to_path(), [])
        self.assertEqual(sys.path, before)

    def test_the_compiled_folder_only_without_qt(self):
        compiled = os.path.join(self.user, 'deps', PY_TAG)
        os.makedirs(compiled)
        with mock.patch.object(deps, 'has_qt', lambda: True):
            self.assertNotIn(compiled, deps.add_to_path())
        with mock.patch.object(deps, 'has_qt', lambda: False):
            self.assertIn(compiled, deps.add_to_path())

    def test_qt_deps_add_to_path_leaves_an_existing_qt_alone(self):
        if not deps.has_qt():
            self.skipTest('needs PySide6')
        before = list(sys.path)
        self.assertTrue(qt_deps.add_to_path())
        self.assertEqual(sys.path, before)


class TestInstallAndRemove(Isolated):

    def test_remove_takes_what_only_it_needed(self):
        make_jedi(self.pure)
        names = deps.remove(deps.JEDI)
        self.assertEqual(names, ['jedi', 'parso'])
        self.assertFalse(os.path.exists(self.pure))

    def test_remove_keeps_what_something_else_needs(self):
        make_jedi(self.pure)
        make_dist(self.pure, 'other', '1.0', ['parso'])
        deps.remove(deps.JEDI)
        self.assertEqual(sorted(os.listdir(self.pure)),
                         ['other', 'other-1.0.dist-info', 'parso',
                          'parso-0.8.7.dist-info'])

    def test_remove_says_when_there_is_nothing(self):
        with self.assertRaises(RuntimeError):
            deps.remove(deps.JEDI)

    def test_an_update_leaves_no_trace_of_the_old_one(self):
        make_jedi(self.pure, '0.18.2', '0.8.3')
        staging = deps.new_staging(deps.JEDI)
        make_jedi(staging, '0.20.1', '0.8.7')
        self.assertEqual(deps.finish_install(deps.JEDI, staging), 'installed')
        self.assertEqual(sorted(os.listdir(self.pure)),
                         ['jedi', 'jedi-0.20.1.dist-info', 'parso',
                          'parso-0.8.7.dist-info'])
        self.assertFalse(os.path.exists(staging))
        self.assertEqual(deps.installed(deps.JEDI)[0], '0.20.1')

    def test_a_staging_folder_left_behind_is_cleared(self):
        old = deps.new_staging(deps.JEDI)
        os.utime(old, (0, 0))
        new = deps.new_staging(deps.JEDI)
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.isdir(new))

    def test_a_qt_in_use_is_updated_at_the_next_start(self):
        folder = os.path.join(self.user, 'deps', PY_TAG)
        make_dist(folder, 'pyside6_essentials', '6.5.0', ['shiboken6'],
                  files=['PySide6/__init__.py'])
        make_dist(folder, 'shiboken6', '6.5.0')
        staging = deps.new_staging(deps.PYSIDE6)
        make_dist(staging, 'pyside6_essentials', '6.11.2', ['shiboken6'],
                  files=['PySide6/__init__.py'])
        make_dist(staging, 'shiboken6', '6.11.2')
        os.makedirs(os.path.join(staging, 'bin'))
        fake = mock.Mock(__file__=os.path.join(folder, 'PySide6',
                                               '__init__.py'))
        with mock.patch.dict(sys.modules, {'PySide6': fake}):
            self.assertEqual(deps.finish_install(deps.PYSIDE6, staging),
                             'restart')
            self.assertEqual(deps.status(deps.PYSIDE6, 'blender').state,
                             deps.Status.RESTART)
        # Nothing touched yet.
        self.assertEqual(deps.installed(deps.PYSIDE6)[0], '6.5.0')
        # The next start, before Qt is imported.
        self.assertEqual(deps.apply_pending(os.path.join(self.user, 'deps')),
                         ['pyside6'])
        self.assertEqual(deps.installed(deps.PYSIDE6)[0], '6.11.2')
        self.assertEqual(sorted(os.listdir(folder)),
                         ['PySide6', 'pyside6_essentials-6.11.2.dist-info',
                          'shiboken6', 'shiboken6-6.11.2.dist-info'])
        self.assertIsNone(deps.pending(deps.PYSIDE6))

    def fake_pip(self, version='0.20.1', fail_progress=False):
        """Stands in for _run_pip: installs into the --target it is given."""
        calls = []

        def run(cmd, on_line=None):
            calls.append(cmd)
            if fail_progress and '--progress-bar' in cmd:
                return 2, ("error: argument --progress-bar: invalid "
                           "choice: 'raw'")
            make_jedi(cmd[cmd.index('--target') + 1], version)
            if on_line:
                on_line('Successfully installed jedi parso')
            return 0, 'Successfully installed jedi parso'
        return calls, run

    def test_install_puts_it_in_place(self):
        calls, run = self.fake_pip()
        lines = []
        with mock.patch.object(deps, '_run_pip', run):
            self.assertEqual(deps.install(deps.JEDI, on_line=lines.append),
                             'installed')
        self.assertEqual(deps.installed(deps.JEDI), ('0.20.1', self.pure))
        self.assertEqual(lines, ['Successfully installed jedi parso'])
        # Nothing left behind in the staging folder.
        self.assertFalse(os.path.exists(os.path.join(
            self.user, 'deps', deps.STAGING_FOLDER)))

    def test_an_older_pip_is_asked_again_without_progress(self):
        calls, run = self.fake_pip(fail_progress=True)
        with mock.patch.object(deps, '_run_pip', run):
            deps.install(deps.JEDI)
        self.assertIn('--progress-bar', calls[0])
        self.assertNotIn('--progress-bar', calls[1])

    def test_a_failure_says_why(self):
        def run(cmd, on_line=None):
            return 1, ('ERROR: Could not find a version that satisfies the '
                       'requirement jedi\nERROR: No matching distribution '
                       'found for jedi')
        with mock.patch.object(deps, '_run_pip', run):
            with self.assertRaises(RuntimeError) as caught:
                deps.install(deps.JEDI)
        self.assertIn('No version of', str(caught.exception))
        self.assertFalse(os.path.exists(self.pure))

    def test_qt_deps_install_goes_through_the_same_steps(self):
        with mock.patch.object(deps, 'install') as install, \
                mock.patch.object(qt_deps, 'add_to_path', lambda: True):
            self.assertEqual(qt_deps.install(), qt_deps.deps_dir())
        self.assertIs(install.call_args[0][0], deps.PYSIDE6)


class TestReadingPip(unittest.TestCase):

    def test_lines(self):
        self.assertEqual(deps.parse_line('Collecting jedi<0.21,>=0.19'),
                         ('step', 'Finding jedi'))
        self.assertEqual(
            deps.parse_line('Downloading jedi-0.20.1-py2.py3-none-any.whl '
                            '(4.9 MB)'),
            ('step', 'Downloading jedi 0.20.1 (4.9 MB)'))
        self.assertIsNone(deps.parse_line(
            '  Downloading jedi-0.20.1-py2.py3-none-any.whl.metadata (23 kB)'))
        self.assertEqual(deps.parse_line('Progress 262144 of 4885980'),
                         ('progress', 262144, 4885980))
        self.assertEqual(
            deps.parse_line('Processing c:\\wheels\\parso-0.8.7-py2.py3-none-'
                            'any.whl'),
            ('step', 'Unpacking parso 0.8.7'))
        self.assertEqual(deps.parse_line('Installing collected packages: '
                                         'parso, jedi'),
                         ('step', 'Installing'))
        self.assertEqual(deps.parse_line('Using cached jedi-0.20.1-py2.py3-'
                                         'none-any.whl (4.9 MB)'),
                         ('step', 'Unpacking jedi 0.20.1'))
        self.assertIsNone(deps.parse_line('Requirement already satisfied'))

    def test_failures_in_plain_words(self):
        self.assertIn('internet', deps.explain_failure(
            'WARNING: Retrying ... NewConnectionError: Failed to establish '
            'a new connection'))
        self.assertIn('no pip', deps.explain_failure(
            'python.exe: No module named pip'))
        with mock.patch.dict(os.environ, {deps.WHEELS_ENV_VAR: '/wheels'}):
            self.assertIn('/wheels', deps.explain_failure(
                'ERROR: No matching distribution found for jedi'))
        self.assertEqual(deps.explain_failure('ERROR: something odd'),
                         'ERROR: something odd')


class TestLoadedByPath(unittest.TestCase):

    def test_neither_imports_qt_nor_nxt_editor(self):
        # How Blender and Unreal load them, before there is any Qt.
        here = os.path.dirname(deps.__file__)
        code = ('import importlib.util, sys\n'
                'spec = importlib.util.spec_from_file_location('
                '"nxt_qt_deps", sys.argv[1])\n'
                'module = importlib.util.module_from_spec(spec)\n'
                'spec.loader.exec_module(module)\n'
                'module.deps_dir(); module.install_command()\n'
                'module.optional_deps.statuses("blender")\n'
                'print(sorted(m for m in sys.modules if m.split(".")[0] in '
                '("PySide6", "Qt", "nxt_editor", "nxt")))\n')
        out = subprocess.check_output(
            [sys.executable, '-I', '-c', code,
             os.path.join(here, 'qt_deps.py')],
            env=dict(os.environ, NXT_USER_DIR=tempfile.mkdtemp(
                prefix='nxt_by_path_')))
        self.assertEqual(out.decode().strip(), '[]')


if __name__ == '__main__':
    unittest.main()
