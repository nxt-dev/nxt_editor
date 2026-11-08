"""The assistant remembers notes and the folders it was let into, asks
before reading anywhere new, and inspects imports without running them.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

# External
from Qt import QtCore, QtWidgets

# Internal
from nxt.session import Session
from nxt_editor import stage_model, user_dir
from nxt_editor.ai import files, memory, providers, tools
from nxt_editor.ai.memory import Memory
from nxt_editor.test.test_ai_assistant import (PREF, FakeProvider, app,
                                               memory_store, wait_for)

PLANTED = '''"""A rig library, found by the tests."""
import os
open(os.path.join(os.path.dirname(__file__), "RAN"), "w").close()

SIDES = ("L", "R")


def make_joint(name, parent=None, radius=1.0):
    """Make a joint under parent."""
    return name


class Limb(object):
    """A chain of joints."""

    def build(self, count=3):
        """Build the chain."""
        return [make_joint("j%d" % i) for i in range(count)]
'''


class Folders(unittest.TestCase):
    """A graph in one folder, and code in two others."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix='nxt_mem_')
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.graph_dir = os.path.join(self.root, 'graph')
        self.code_dir = os.path.join(self.root, 'code')
        self.other_dir = os.path.join(self.root, 'other')
        for folder in (self.graph_dir, self.code_dir, self.other_dir):
            os.makedirs(folder)
        with open(os.path.join(self.graph_dir, 'helper.py'), 'w') as fp:
            fp.write('VALUE = 1\n')
        package = os.path.join(self.code_dir, 'nxt_test_riglib')
        os.makedirs(package)
        with open(os.path.join(package, '__init__.py'), 'w') as fp:
            fp.write('')
        with open(os.path.join(package, 'joints.py'), 'w') as fp:
            fp.write(PLANTED)
        with open(os.path.join(self.code_dir, 'notes.txt'), 'w') as fp:
            fp.write('\n'.join('line {}'.format(i) for i in range(1, 51)))
        with open(os.path.join(self.code_dir, 'blob.bin'), 'wb') as fp:
            fp.write(b'\0\1\2')
        graph = {'version': '1.17', 'alias': 'top', 'nodes': {
            '/rig': {'code': ['import json',
                              'from nxt_test_riglib import joints',
                              'import nxt_test_missing']},
            '/rig/arm': {'code': ['import os.path']},
            '/tokens': {'code': ['import json', 'x = ${value}']}}}
        path = os.path.join(self.graph_dir, 'top.nxt')
        with open(path, 'w') as fp:
            json.dump(graph, fp)
        self.model = stage_model.StageModel(Session().load_file(
            filepath=path))
        self.prefs = {}
        self.memory = Memory(self.prefs)
        self.answers = []
        self.asked = []
        self.chat_folders = set()
        self.box = tools.Toolbox(self.model, memory=self.memory,
                                 chat_folders=self.chat_folders,
                                 ask_access=self.ask)
        sys.path.insert(0, self.code_dir)
        self.addCleanup(sys.path.remove, self.code_dir)

    def ask(self, folder, reason):
        self.asked.append((folder, reason))
        return self.answers.pop(0) if self.answers else tools.DENY

    def call(self, name, **args):
        return self.box.call(name, args)


class AccessTests(Folders):

    def test_the_graphs_folder_is_free_to_read(self):
        text, failed = self.call('read_file', path='helper.py')
        self.assertFalse(failed, text)
        self.assertIn('VALUE = 1', text)
        self.assertEqual([], self.asked)
        text, failed = self.call('list_files')
        self.assertIn('helper.py', text)

    def test_anywhere_else_is_asked_first(self):
        self.answers = [tools.DENY]
        text, failed = self.call('read_file',
                                 path=os.path.join(self.code_dir,
                                                   'notes.txt'),
                                 reason='to see the notes')
        self.assertTrue(failed)
        self.assertIn('did not let you read', text)
        self.assertEqual([(self.code_dir, 'to see the notes')], self.asked)
        # Not asked again in the same reply.
        self.call('list_files', path=self.code_dir)
        self.assertEqual(1, len(self.asked))

    def test_allowed_for_the_chat(self):
        self.answers = [tools.ONCE]
        text, failed = self.call('list_files', path=self.code_dir)
        self.assertFalse(failed, text)
        self.assertIn('notes.txt', text)
        self.assertIn('nxt_test_riglib/', text)
        self.assertEqual({self.code_dir}, self.chat_folders)
        self.call('read_file', path=os.path.join(self.code_dir, 'notes.txt'))
        self.assertEqual(1, len(self.asked))
        self.assertEqual([], self.memory.folders())
        # Another chat starts without it.
        other = tools.Toolbox(self.model, memory=self.memory,
                              ask_access=self.ask)
        other.call('list_files', {'path': self.code_dir})
        self.assertEqual(2, len(self.asked))

    def test_always_allowed_is_remembered(self):
        self.answers = [tools.ALWAYS]
        self.call('search_files', path=self.code_dir, text='make_joint',
                  reason='To find where joints are made.',
                  about='the rig library')
        self.assertEqual([self.code_dir],
                         [f['path'] for f in self.memory.folders()])
        self.assertEqual('the rig library',
                         self.memory.folders()[0]['about'])
        later = tools.Toolbox(self.model, memory=Memory(self.prefs),
                              ask_access=self.ask)
        text, failed = later.call('read_file', {'path': os.path.join(
            self.code_dir, 'nxt_test_riglib', 'joints.py')})
        self.assertFalse(failed)
        self.assertEqual(1, len(self.asked))
        self.assertIn(self.code_dir, Memory(self.prefs).describe())

    def test_a_folder_inside_an_allowed_one_is_allowed(self):
        self.memory.allow(self.code_dir)
        text, failed = self.call('list_files', path=os.path.join(
            self.code_dir, 'nxt_test_riglib'))
        self.assertFalse(failed)
        self.assertEqual([], self.asked)

    def test_a_folder_beside_an_allowed_one_is_not(self):
        self.memory.allow(self.code_dir)
        self.assertFalse(self.memory.allowed(self.code_dir + '_evil'))
        self.call('list_files', path=self.other_dir)
        self.assertEqual(1, len(self.asked))

    def test_without_anyone_to_ask_nothing_new_is_read(self):
        box = tools.Toolbox(self.model, memory=self.memory)
        text, failed = box.call('list_files', {'path': self.code_dir})
        self.assertTrue(failed)


class ReadingTests(Folders):

    def setUp(self):
        super(ReadingTests, self).setUp()
        self.memory.allow(self.code_dir)

    def test_reading_part_of_a_file(self):
        text, _ = self.call('read_file', path=os.path.join(
            self.code_dir, 'notes.txt'), start_line=10, end_line=12)
        self.assertIn('   10  line 10', text)
        self.assertIn('   12  line 12', text)
        self.assertNotIn('   13  line 13', text)
        self.assertIn('read on from line 13', text)

    def test_binary_files_are_not_read(self):
        text, failed = self.call('read_file', path=os.path.join(
            self.code_dir, 'blob.bin'))
        self.assertTrue(failed)
        self.assertIn('not a text file', text)

    def test_searching(self):
        text, _ = self.call('search_files', path=self.code_dir,
                            text='def \\w+_joint', regex=True,
                            pattern='*.py')
        self.assertIn('joints.py:8: def make_joint', text)


class ImportTests(Folders):

    def tearDown(self):
        for name in list(sys.modules):
            if name.startswith('nxt_test_riglib'):
                del sys.modules[name]

    def ran(self):
        return os.path.exists(os.path.join(self.code_dir, 'nxt_test_riglib',
                                           'RAN'))

    def test_a_module_is_inspected_without_running_it(self):
        text, failed = self.call('inspect_import',
                                 module='nxt_test_riglib.joints')
        self.assertFalse(failed, text)
        info = json.loads(text)
        self.assertFalse(info['imported'])
        self.assertTrue(info['file'].endswith('joints.py'))
        self.assertEqual('A rig library, found by the tests.', info['doc'])
        self.assertIn("def make_joint(name, parent=None, radius=1.0)  "
                      "Make a joint under parent.", info['members'])
        self.assertIn('class Limb  A chain of joints.', info['members'])
        self.assertIn('    def build(self, count=3)  Build the chain.',
                      info['members'])
        self.assertIn('SIDES = ...', info['members'])
        self.assertFalse(self.ran())
        self.assertNotIn('nxt_test_riglib', sys.modules)

    def test_a_member_in_full(self):
        text, _ = self.call('inspect_import', module='nxt_test_riglib.joints',
                            member='Limb.build')
        info = json.loads(text)
        self.assertIn('return [make_joint', info['source'])
        self.assertFalse(self.ran())

    def test_a_package_lists_its_modules(self):
        info = json.loads(self.call('inspect_import',
                                    module='nxt_test_riglib')[0])
        self.assertEqual(['joints'], info['submodules'])

    def test_an_imported_module_is_looked_at_live(self):
        info = json.loads(self.call('inspect_import', module='json')[0])
        self.assertTrue(info['imported'])
        self.assertTrue(any(m.startswith('def dumps(') for m in
                            info['members']))
        member = json.loads(self.call('inspect_import', module='json',
                                      member='dumps')[0])
        self.assertIn('obj', member['signature'])
        self.assertIn('def dumps', member['source'])

    def test_a_missing_module(self):
        text, failed = self.call('inspect_import', module='nxt_test_missing')
        self.assertTrue(failed)
        self.assertIn('not on the Python path', text)

    def test_a_nodes_imports(self):
        found = json.loads(self.call('get_node_imports', path='/rig',
                                     children=True)[0])
        rig = {i['module']: i for i in found['/rig']}
        self.assertEqual(['json', 'nxt_test_riglib',
                          'nxt_test_missing'], list(rig))
        self.assertTrue(rig['nxt_test_riglib']['from'].endswith(
            '__init__.py'))
        self.assertEqual('not found on the Python path',
                         rig['nxt_test_missing']['from'])
        self.assertEqual('os.path', found['/rig/arm'][0]['module'])
        self.assertFalse(self.ran())

    def test_code_with_tokens(self):
        self.assertEqual(['json'], files.imports_in('import json\nx = ${v}'))


class MemoryTests(Folders):

    def test_remember_and_forget(self):
        text, failed = self.call('remember',
                                 note='  Name controls side_part_ctrl ')
        self.assertFalse(failed)
        notes = self.memory.notes()
        self.assertEqual(['Name controls side_part_ctrl'],
                         [n['text'] for n in notes])
        # The same note twice is kept once.
        self.call('remember', note='name controls side_part_ctrl')
        self.assertEqual(1, len(self.memory.notes()))
        described = self.memory.describe()
        self.assertIn('[{}] Name controls'.format(notes[0]['id']), described)
        self.call('forget', id=notes[0]['id'])
        self.assertEqual([], self.memory.notes())
        self.assertTrue(self.call('forget', id='nope')[1])

    def test_paths_are_compared_however_typed(self):
        self.memory.allow(self.code_dir + os.sep)
        self.assertTrue(self.memory.allowed(os.path.join(
            self.code_dir, '.', 'notes.txt')))
        self.memory.allow(self.code_dir)
        self.assertEqual(1, len(self.memory.folders()))
        self.assertTrue(self.memory.disallow(self.code_dir))
        self.assertFalse(self.memory.allowed(self.code_dir))


class Answering(FakeProvider):
    """Reads a file outside the graph's folder, as a provider would."""

    def stream_chat(self, messages, system, model=None, auth=None,
                    tools=None):
        self.system = system
        self.result = tools.call('list_files', {'path': self.folder,
                                                'reason': 'the rig code',
                                                'about': 'the rig code'})
        yield 'Done.'


class PanelAsksTests(Folders):

    def setUp(self):
        super(PanelAsksTests, self).setUp()
        from nxt_editor.dockwidgets.ai_assistant import AiAssistant
        self.prefs.update({PREF.AI_ENABLED: True})
        store = memory_store()
        self.fake = Answering(store=store, prefs=self.prefs)
        self.fake.folder = self.code_dir
        self.fake.save_api_key('k')
        patcher = mock.patch.object(providers, 'get_provider',
                                    side_effect=lambda *a, **k: self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        providers._models.clear()
        self.panel = AiAssistant(store=store, prefs=self.prefs)
        wait_for(lambda: self.panel.model_combo.count())
        self.panel.set_stage_model(self.model)

    def tearDown(self):
        self.panel.stop()
        if self.panel.thread:
            self.panel.thread.wait(5000)
        self.panel.deleteLater()
        app.processEvents()

    def ask_and_answer(self, button):
        """Answer the question once it shows, as a click would: from the
        event loop, while the panel waits for it."""
        seen = {}

        def answer():
            if self.panel.ask_frame.isHidden():
                return
            timer.stop()
            seen['path'] = self.panel.ask_path.text()
            seen['reason'] = self.panel.ask_reason.text()
            if button is None:
                self.panel.stop()
            else:
                button.click()

        timer = QtCore.QTimer()
        timer.timeout.connect(answer)
        timer.start(20)
        self.panel.send('Look at the rig code')
        wait_for(lambda: seen and not self.panel.busy, timeout=10)
        timer.stop()
        self.assertIn(self.code_dir, seen['path'])
        self.assertIn('the rig code', seen['reason'])
        self.assertTrue(self.panel.ask_frame.isHidden())

    def test_allow(self):
        self.ask_and_answer(self.panel.allow_button)
        self.assertFalse(self.fake.result[1])
        self.assertIn('notes.txt', self.fake.result[0])
        self.assertEqual([], Memory(self.prefs).folders())

    def test_always_allow(self):
        self.ask_and_answer(self.panel.always_button)
        self.assertFalse(self.fake.result[1])
        self.assertEqual([self.code_dir],
                         [f['path'] for f in Memory(self.prefs).folders()])
        # The next chat is told about it.
        self.panel.new_chat()
        self.panel.send('Again')
        wait_for(lambda: not self.panel.busy)
        self.assertIn(self.code_dir, self.fake.system)
        self.assertIn('the rig code', self.fake.system)

    def test_deny(self):
        self.ask_and_answer(self.panel.deny_button)
        self.assertTrue(self.fake.result[1])

    def test_stop_while_asking(self):
        self.ask_and_answer(None)
        self.assertTrue(self.fake.result[1])

    def test_notes_go_with_every_chat(self):
        Memory(self.prefs).add('Always comment new nodes')
        self.memory.allow(self.code_dir)
        self.panel.send('Hi')
        wait_for(lambda: not self.panel.busy)
        self.assertIn('Always comment new nodes', self.fake.system)


class MemoryPageTests(unittest.TestCase):

    def test_notes_and_folders_can_be_changed(self):
        from nxt_editor.ai.memory_page import MemoryPage
        prefs = {}
        Memory(prefs).add('First note')
        folder = tempfile.mkdtemp(prefix='nxt_mem_')
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        Memory(prefs).allow(folder, 'rig code')
        page = MemoryPage(prefs=prefs)
        self.assertEqual('First note', page.notes_list.item(0).text())
        self.assertEqual('rig code',
                         page.folders_list.topLevelItem(0).text(1))
        item = page.notes_list.item(0)
        item.setText('Changed note')
        self.assertEqual(['Changed note'],
                         [n['text'] for n in Memory(prefs).notes()])
        page.notes_list.setCurrentItem(page.notes_list.item(0))
        page.remove_note()
        self.assertEqual([], Memory(prefs).notes())
        page.folders_list.topLevelItem(0).setText(1, 'the rig library')
        self.assertEqual('the rig library',
                         Memory(prefs).folders()[0]['about'])
        page.folders_list.topLevelItem(0).setSelected(True)
        page.remove_folder()
        self.assertEqual([], Memory(prefs).folders())
        page.add_folder(folder)
        self.assertEqual(1, len(Memory(prefs).folders()))

    def test_the_settings_have_a_memory_tab(self):
        from nxt_editor.ai.settings_dialog import AiSettingsDialog
        with mock.patch.dict('os.environ', {}, clear=True):
            dialog = AiSettingsDialog(store=memory_store(),
                                      prefs={PREF.AI_ENABLED: True})
        tabs = [dialog.body.tabText(i) for i in range(dialog.body.count())]
        self.assertEqual(['Sign In', 'Memory'], tabs)
        dialog.deleteLater()


if __name__ == '__main__':
    unittest.main()
