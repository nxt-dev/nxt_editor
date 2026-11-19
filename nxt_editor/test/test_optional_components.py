"""Edit > Preferences > Optional Components: a card per component, pip in a QProcess.

pip is never run. A stand in for QProcess takes its place, says what pip
would, and writes what pip would have installed into the folder it was
given, so everything after pip is real: the move into place, the status,
and jedi being picked up by completion without a restart.
"""
# Builtin
import gc
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

# External
from Qt import QtCore, QtWidgets

# Internal
from nxt_editor.integration import optional_deps as deps
from nxt_editor.test.test_optional_deps import ENV_VARS, make_jedi

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


def put_away(widget):
    """Close a window and keep it, the way conftest.keep_windows keeps
    every window a test leaves.

    Freeing a window in the middle of a run, through Qt or the collector,
    is what crashes on macOS and corrupts the heap on Windows, so a closed
    window is only hidden and lives until the run ends.
    """
    widget.close()
    _PUT_AWAY.append(widget)


#: Windows closed by these tests, kept until the run ends. See put_away.
_PUT_AWAY = []

from nxt_editor import optional_components as oc  # noqa: E402
from nxt_editor.dockwidgets import code_completion  # noqa: E402

#: A jedi that imports, for completion to pick up.
FAKE_JEDI = ('class settings(object):\n'
             '    cache_directory = None\n'
             '    allow_unsafe_interpreter_executions = True\n'
             '__version__ = "0.20.1"\n')


class FakeProcess(QtCore.QObject):
    """What InstallJob uses of QProcess, driven by the test."""
    readyReadStandardOutput = QtCore.Signal()
    finished = QtCore.Signal(int, object)
    errorOccurred = QtCore.Signal(object)
    made = []

    def __init__(self, parent=None):
        super(FakeProcess, self).__init__(parent)
        self.args = None
        self.program = None
        self.env = None
        self.killed = False
        self._out = b''
        FakeProcess.made.append(self)

    def setProcessChannelMode(self, mode):
        pass

    def setProcessEnvironment(self, env):
        self.env = env

    def start(self, program, args):
        self.program = program
        self.args = list(args)

    @property
    def target(self):
        return self.args[self.args.index('--target') + 1]

    def say(self, text):
        self._out += text.encode('utf-8')
        self.readyReadStandardOutput.emit()

    def readAllStandardOutput(self):
        out, self._out = self._out, b''
        return out

    def kill(self):
        self.killed = True
        self.finished.emit(-1, None)

    def errorString(self):
        return 'no such file'

    def install_jedi(self, version='0.20.1', real=False):
        """Do what a successful pip run does, and finish."""
        self.say('Collecting jedi<0.21,>=0.19\n')
        self.say('Downloading jedi-{}-py2.py3-none-any.whl (4.9 MB)\n'
                 .format(version))
        self.say('Progress 262144 of 4885980\r\n')
        self.say('Installing collected packages: parso, jedi\n')
        make_jedi(self.target, version)
        if real:
            with open(os.path.join(self.target, 'jedi', '__init__.py'),
                      'w') as handle:
                handle.write(FAKE_JEDI)
        self.say('Successfully installed jedi-{} parso-0.8.7'.format(version))
        self.finished.emit(0, None)


class DialogTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='nxt_components_')
        self.user = os.path.join(self.tmp, 'user')
        env = {k: v for k, v in os.environ.items() if k not in ENV_VARS}
        env[deps.USER_DIR_ENV_VAR] = self.user
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()
        self.path = list(sys.path)
        self.pure = os.path.join(self.user, 'deps', 'pure')
        FakeProcess.made[:] = []
        # As if this python had no jedi of its own.
        self.elsewhere = mock.patch.object(deps, 'elsewhere_version',
                                           lambda comp: None)
        self.elsewhere.start()

    def tearDown(self):
        self.elsewhere.stop()
        self.env.stop()
        sys.path[:] = self.path
        oc.forget_modules(['jedi', 'parso'])
        code_completion.JEDI.reset()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def dialog(self, host='maya'):
        dialog = oc.OptionalComponentsDialog(host=host, crt=(14, 44, 0),
                                             process_factory=FakeProcess)
        self.addCleanup(put_away, dialog)
        return dialog

    def visible(self, widget):
        return not widget.isHidden()


class TestCards(DialogTest):

    def test_not_installed_offers_install(self):
        card = self.dialog().card('jedi')
        self.assertEqual(card.pill.text, 'Not installed')
        self.assertEqual(card.button.text(), 'Install')
        self.assertEqual(card.button.objectName(), 'primary')
        self.assertIn('Installs to', card.where.text())

    def test_installed_offers_remove(self):
        make_jedi(self.pure)
        card = self.dialog().card('jedi')
        self.assertEqual(card.pill.text, 'Installed 0.20.1')
        self.assertEqual(card.button.text(), 'Remove')
        self.assertEqual(card.button.objectName(), 'secondary')

    def test_out_of_range_offers_update(self):
        make_jedi(self.pure, '0.18.2')
        card = self.dialog().card('jedi')
        self.assertEqual(card.pill.text, 'Update available')
        self.assertEqual(card.button.text(), 'Update')
        self.assertIn('older', card.meta.text())

    def test_a_studio_copy_is_read_only(self):
        shared = os.path.join(self.tmp, 'studio')
        make_jedi(os.path.join(shared, 'pure'))
        os.environ[deps.DEPS_ENV_VAR] = shared
        real = deps.writable
        with mock.patch.object(deps, 'writable', lambda path: (
                False if path.startswith(shared) else real(path))):
            dialog = self.dialog()
            card = dialog.card('jedi')
            self.assertEqual(card.pill.text, 'Managed by your studio')
            self.assertFalse(self.visible(card.button))
            self.assertIn('Your studio provides', dialog.note.text())

    def test_offline_is_said(self):
        os.environ[deps.WHEELS_ENV_VAR] = os.path.join(self.tmp, 'wheels')
        dialog = self.dialog()
        self.assertTrue(self.visible(dialog.note))
        self.assertIn('offline', dialog.note.text())

    def test_no_note_without_the_variables(self):
        self.assertFalse(self.visible(self.dialog().note))

    def test_qt_is_dimmed_and_last_where_the_host_has_it(self):
        dialog = self.dialog('maya')
        card = dialog.card('pyside6')
        self.assertEqual(card.pill.text, 'Not needed here')
        self.assertFalse(self.visible(card.button))
        self.assertIn('Maya has its own', card.description.text())
        layout = dialog.layout()
        self.assertGreater(layout.indexOf(card),
                           layout.indexOf(dialog.card('jedi')))

    def test_qt_from_nxt_folder_can_be_updated_but_not_removed(self):
        def status(comp):
            if comp is deps.PYSIDE6:
                return deps.Status(comp, deps.Status.INSTALLED, '6.11.2',
                                   '/deps/py311', '>=6,<6.12')
            return deps.status(comp, 'blender')
        dialog = oc.OptionalComponentsDialog(host='blender', crt=(14, 44, 0),
                                             process_factory=FakeProcess,
                                             status_func=status)
        self.addCleanup(put_away, dialog)
        self.assertFalse(self.visible(dialog.card('pyside6').button))
        dialog.status_func = lambda comp: deps.Status(
            comp, deps.Status.UPDATE, '6.5.0', '/deps/py311', '>=6,<6.12',
            too_old=True)
        dialog.refresh()
        self.assertEqual(dialog.card('pyside6').button.text(), 'Update')


class TestInstalling(DialogTest):

    def test_install_runs_pip_in_a_process_and_shows_progress(self):
        dialog = self.dialog()
        card = dialog.card('jedi')
        card.button.click()
        process = FakeProcess.made[-1]
        self.assertEqual(process.args[:3], ['-m', 'pip', 'install'])
        self.assertIn('--progress-bar', process.args)
        self.assertTrue(process.target.startswith(
            os.path.join(self.user, 'deps', deps.STAGING_FOLDER)))
        self.assertEqual(card.button.text(), 'Cancel')
        self.assertEqual(card.pill.text, 'Installing')
        self.assertIsNone(card.progress.value)
        process.say('Collecting jedi<0.21,>=0.19\n')
        self.assertEqual(card.step_label.text(), 'Finding jedi')
        process.say('Downloading jedi-0.20.1-py2.py3-none-any.whl (4.9 MB)\n')
        process.say('Progress 2442990 of 4885980\n')
        self.assertAlmostEqual(card.progress.value, 0.5, places=2)
        self.assertIn('50%', card.step_label.text())
        # Details show what pip said, without the progress lines.
        card.details.click()
        self.assertTrue(self.visible(card.log))
        log = card.log.toPlainText()
        self.assertIn('Downloading jedi-0.20.1', log)
        self.assertNotIn('Progress 2442990', log)

    def test_success(self):
        changed = []
        dialog = self.dialog()
        dialog.changed.connect(changed.append)
        dialog.card('jedi').button.click()
        FakeProcess.made[-1].install_jedi()
        card = dialog.card('jedi')
        self.assertEqual(card.pill.text, 'Installed 0.20.1')
        self.assertEqual(card.button.text(), 'Remove')
        self.assertIn('Ready to use', card.step_label.text())
        self.assertEqual(changed, ['jedi'])
        self.assertEqual(deps.installed(deps.JEDI), ('0.20.1', self.pure))
        self.assertIn(self.pure, sys.path)
        self.assertFalse(dialog.busy())

    def test_failure_offers_retry(self):
        dialog = self.dialog()
        card = dialog.card('jedi')
        card.button.click()
        process = FakeProcess.made[-1]
        process.say('ERROR: No matching distribution found for jedi\n')
        process.finished.emit(1, None)
        self.assertEqual(card.pill.text, 'Failed')
        self.assertEqual(card.pill.color, oc.BAD)
        self.assertIn('No version of', card.step_label.text())
        self.assertEqual(card.button.text(), 'Retry')
        # Nothing half done is left.
        self.assertFalse(os.path.exists(process.target))
        card.button.click()
        FakeProcess.made[-1].install_jedi()
        self.assertEqual(card.pill.text, 'Installed 0.20.1')

    def test_cancel(self):
        dialog = self.dialog()
        card = dialog.card('jedi')
        card.button.click()
        process = FakeProcess.made[-1]
        card.button.click()
        self.assertTrue(process.killed)
        self.assertEqual(card.step_label.text(), 'Cancelled.')
        self.assertEqual(card.button.text(), 'Retry')
        self.assertFalse(os.path.exists(process.target))
        self.assertIsNone(deps.installed(deps.JEDI)[0])

    def test_an_older_pip_is_asked_again_without_progress(self):
        dialog = self.dialog()
        dialog.card('jedi').button.click()
        first = FakeProcess.made[-1]
        first.say("pip install: error: argument --progress-bar: invalid "
                  "choice: 'raw' (choose from 'on', 'off')\n")
        first.finished.emit(2, None)
        second = FakeProcess.made[-1]
        self.assertIsNot(first, second)
        self.assertNotIn('--progress-bar', second.args)
        second.install_jedi()
        self.assertEqual(dialog.card('jedi').pill.text, 'Installed 0.20.1')

    def test_a_process_that_does_not_start(self):
        dialog = self.dialog()
        card = dialog.card('jedi')
        card.button.click()
        FakeProcess.made[-1].errorOccurred.emit(
            QtCore.QProcess.FailedToStart)
        self.assertEqual(card.pill.text, 'Failed')
        self.assertIn("Couldn't start pip", card.step_label.text())

    def test_update_replaces_the_old_one(self):
        make_jedi(self.pure, '0.18.2')
        dialog = self.dialog()
        dialog.card('jedi').button.click()
        FakeProcess.made[-1].install_jedi('0.20.1')
        self.assertEqual(sorted(os.listdir(self.pure)),
                         ['jedi', 'jedi-0.20.1.dist-info', 'parso',
                          'parso-0.8.7.dist-info'])

    def test_remove(self):
        make_jedi(self.pure)
        changed = []
        dialog = self.dialog()
        dialog.changed.connect(changed.append)
        card = dialog.card('jedi')
        card.button.click()
        self.assertEqual(card.pill.text, 'Not installed')
        self.assertEqual(card.button.text(), 'Install')
        self.assertEqual(changed, ['jedi'])
        self.assertFalse(os.path.exists(self.pure))


class TestJediReset(unittest.TestCase):

    def test_reset_looks_again_and_takes_a_lock_if_there_is_one(self):
        import threading
        jedi = code_completion.Jedi()
        jedi._tried, jedi._module = True, object()
        jedi.reset()
        self.assertFalse(jedi._tried)
        self.assertIsNone(jedi._module)
        # Completion asked from a worker thread keeps its state under a
        # lock, and a cache of (key, names).
        jedi._lock = threading.Lock()
        jedi._cache = ('key', ['name'])
        jedi._tried = True
        jedi.reset()
        self.assertFalse(jedi._tried)
        self.assertEqual(jedi._cache, (None, []))
        self.assertFalse(jedi._lock.locked())


class TestEditor(DialogTest):
    """In the editor: the menu, the hint, and jedi picked up live."""

    @classmethod
    def setUpClass(cls):
        from nxt_editor.main_window import MainWindow
        cls.win = MainWindow()
        # conftest freezes what exists after each test, but this window is
        # made before the first one ends. Frozen now, nothing it left for
        # the collector can be freed in the middle of a test, which on
        # macOS crashed whatever that test was doing at the time.
        gc.freeze()

    @classmethod
    def tearDownClass(cls):
        put_away(cls.win)
        cls.win = None

    def setUp(self):
        super(TestEditor, self).setUp()
        # A page of Preferences, made again with it.
        if self.win.preference_editor is not None:
            put_away(self.win.preference_editor)
        self.win.preference_editor = None
        self.win.optional_components_dialog = None
        self.win.jedi_offered = False
        if code_completion.Jedi.installed():
            self.skipTest('this python has jedi of its own')

    def test_it_is_a_page_of_preferences(self):
        self.win.app_actions.optional_components_action.trigger()
        dialog = self.win.optional_components_dialog
        self.assertIsInstance(dialog, oc.OptionalComponentsDialog)
        self.assertTrue(dialog.isVisible())
        self.assertEqual('Optional Components',
                         self.win.preference_editor.current_section())
        self.win.preference_editor.hide()

    def test_jedi_installed_from_the_dialog_is_used_at_once(self):
        actions = self.win.code_editor_actions
        actions.refresh_jedi_action()
        action = actions.complete_jedi_action
        self.assertFalse(action.isChecked())
        self.assertFalse(code_completion.JEDI.available())
        dialog = self.win.open_optional_components('jedi')
        self.addCleanup(dialog.hide)
        dialog.process_factory = FakeProcess
        dialog.install(deps.JEDI)
        FakeProcess.made[-1].install_jedi(real=True)
        self.assertTrue(code_completion.JEDI.installed())
        self.assertTrue(code_completion.JEDI.available())
        self.assertTrue(action.isChecked())
        self.assertEqual(action.text(), 'Python Analysis (jedi)')
        # Nothing was written to the hotkeys on the way.
        from nxt_editor import user_dir
        self.assertNotIn(None, [user_dir.hotkeys.get(name) for name in (
            'Python Analysis (jedi)', 'Python Analysis (jedi)...')
            if name in user_dir.hotkeys])
        # And it can be taken out again, live too.
        dialog.remove(deps.JEDI)
        self.assertFalse(code_completion.JEDI.installed())
        self.assertFalse(action.isChecked())

    def test_the_hint_is_asked_once_a_session(self):
        # A real dialog that runs a stand in pip, given to the window
        # before it needs one. Patching the dialog's class instead left
        # PySide holding methods that were swapped back, and connecting to
        # them later crashed Python 3.13 on macOS.
        dialog = oc.OptionalComponentsDialog(parent=self.win,
                                             process_factory=FakeProcess)
        self.win.optional_components_dialog = dialog
        self.addCleanup(dialog.hide)
        with mock.patch.object(oc.Hint, 'exec_',
                               return_value=QtWidgets.QDialog.Accepted):
            self.win.code_editor_actions.refresh_jedi_action()
            self.win.code_editor_actions.complete_jedi_action.trigger()
        self.assertEqual(1, len(FakeProcess.made))
        self.assertIn('jedi', ' '.join(FakeProcess.made[0].args))
        dialog.cancel(deps.JEDI)
        with mock.patch.object(oc.Hint, 'exec_') as hint:
            self.win.code_editor_actions.complete_jedi_action.trigger()
        hint.assert_not_called()

    def test_a_wanted_update_is_said_once_in_the_status_bar(self):
        make_jedi(self.pure, '0.18.2')
        oc._NOTICE_SHOWN[:] = []
        notice = self.win.show_component_notice()
        self.assertIsNotNone(notice)
        self.assertIn('Python Analysis (jedi) needs an update',
                      notice.label.text())
        self.assertIsNone(self.win.show_component_notice())
        with mock.patch.object(self.win, 'open_optional_components') as open_:
            notice.open_requested.disconnect()
            notice.open_requested.connect(open_)
            notice.label.linkActivated.emit('open')
        open_.assert_called_once_with()

    def test_no_notice_when_all_is_well(self):
        make_jedi(self.pure)
        oc._NOTICE_SHOWN[:] = []
        self.assertIsNone(self.win.show_component_notice())


if __name__ == '__main__':
    unittest.main()
