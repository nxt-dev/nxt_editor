"""The AI Assistant keeps every chat, so New Chat does not lose the last one.

Chats are listed to go back to, pinned to the top or deleted with a right
click, and each message shows when it was sent, with the day wherever it
changes, as chat apps do.
"""
# Builtin
import datetime
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

# External
from Qt import QtCore, QtWidgets

# Internal
from nxt_editor.ai import chat_render, chats, context, providers
from nxt_editor.test.test_ai_assistant import (PREF, FakeProvider, app,
                                               memory_store, wait_for)


class Slow(FakeProvider):
    """Answers only once let go."""

    def __init__(self, *args, **kwargs):
        super(Slow, self).__init__(*args, **kwargs)
        self.go = threading.Event()

    def stream_chat(self, messages, system, model=None, auth=None,
                    tools=None):
        yield 'Thinking'
        self.go.wait(5)
        yield ' about it'


class ChatsAreKept(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix='nxt_chats_')
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.store = memory_store()
        self.prefs = {PREF.AI_ENABLED: True}
        self.fake = FakeProvider(store=self.store, prefs=self.prefs)
        self.fake.save_api_key('k')
        self.fake.model = 'claude-test'
        patcher = mock.patch.object(providers, 'get_provider',
                                    side_effect=lambda *a, **k: self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, value in (('describe_selection', ''),):
            p = mock.patch.object(context, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch('nxt_editor.ai.graph_actions.describe_graph',
                       return_value='The graph')
        p.start()
        self.addCleanup(p.stop)
        providers._models.clear()
        self.panel = self.make_panel()

    def make_panel(self):
        from nxt_editor.dockwidgets.ai_assistant import AiAssistant
        panel = AiAssistant(store=self.store, prefs=self.prefs,
                            chat_store=chats.ChatStore(self.folder))
        wait_for(lambda: panel.model_combo.count())
        panel.stage_model = mock.Mock(selection=[])
        self.addCleanup(self.close, panel)
        return panel

    @staticmethod
    def close(panel):
        panel.stop()
        for thread in [panel.thread] + panel.left_threads:
            if thread:
                thread.wait(5000)
        panel.deleteLater()
        app.processEvents()

    def ask(self, text, panel=None):
        panel = panel or self.panel
        panel.send(text)
        wait_for(lambda: not panel.busy and panel.messages and
                 panel.messages[-1]['role'] == 'assistant')

    def listed(self, panel=None):
        panel = panel or self.panel
        rows = []
        for row in range(panel.chat_list.count()):
            item = panel.chat_list.item(row)
            rows.append(item.text().split('  ·  ')[0])
        return rows

    def click(self, title, panel=None):
        panel = panel or self.panel
        for row in range(panel.chat_list.count()):
            item = panel.chat_list.item(row)
            if item.text().startswith(title):
                panel.chat_list.itemClicked.emit(item)
                return
        self.fail('No chat called {}'.format(title))

    def shown(self, panel=None):
        return [m.get('shown') for m in (panel or self.panel).messages
                if m['role'] == 'user']

    def test_new_chat_keeps_the_last_one(self):
        self.ask('First question')
        self.panel.new_chat()
        self.assertEqual([], self.panel.messages)
        self.ask('Second question')
        self.assertEqual(['Second question', 'First question'], self.listed())
        self.click('First question')
        self.assertEqual(['First question'], self.shown())
        self.assertIn('print("hi")', self.panel.transcript.toPlainText())
        self.ask('A follow up')
        self.assertEqual(['First question', 'A follow up'], self.shown())
        self.assertEqual(['First question', 'Second question'], self.listed())

    def test_chats_are_there_next_time(self):
        self.ask('Remember me')
        later = self.make_panel()
        self.assertEqual([], later.messages)
        self.assertEqual(['Remember me'], self.listed(later))
        self.click('Remember me', later)
        self.assertEqual(['Remember me'], self.shown(later))
        self.assertEqual(2, len(later.messages))

    def test_an_empty_new_chat_is_not_listed(self):
        self.panel.new_chat()
        self.panel.new_chat()
        self.assertEqual([], self.listed())
        self.assertEqual([], os.listdir(self.folder))

    def test_a_question_that_fails_leaves_no_chat(self):
        def broken(*args, **kwargs):
            raise RuntimeError('No credit left')
            yield
        self.fake.stream_chat = broken
        self.panel.send('Hello')
        wait_for(lambda: not self.panel.busy and
                 self.panel.input.toPlainText())
        self.assertEqual([], self.listed())
        self.assertEqual([], os.listdir(self.folder))

    def test_pinning_keeps_a_chat_at_the_top(self):
        self.ask('Old one')
        self.panel.new_chat()
        self.ask('New one')
        old = self.panel.chat_store.list()[1]['id']
        self.panel.pin_chat(old, True)
        self.assertEqual(['Pinned', 'Old one', 'Recent', 'New one'],
                         self.listed())
        # Talking in another chat leaves the pinned one on top.
        self.ask('More')
        self.assertEqual(['Pinned', 'Old one', 'Recent', 'New one'],
                         self.listed())
        # And talking in the pinned one leaves it pinned.
        self.click('Old one')
        self.ask('Still pinned?')
        self.assertTrue(self.panel.chat_store.load(old)['pinned'])
        self.assertEqual('Pinned', self.listed(self.make_panel())[0])
        self.panel.pin_chat(old, False)
        self.assertEqual(['Old one', 'New one'], self.listed())

    def test_right_click_pins_and_deletes(self):
        self.ask('Right click me')
        item = self.panel.chat_list.item(0)
        pos = self.panel.chat_list.visualItemRect(item).center()
        menus = []

        def opened(menu, *args):
            menus.append({a.text(): a for a in menu.actions()})

        with mock.patch.object(QtWidgets.QMenu, 'exec_', opened):
            self.panel.chat_menu(pos)
        self.assertEqual(['Pin', 'Delete'], list(menus[0]))
        menus[0]['Pin'].trigger()
        self.assertEqual(['Pinned', 'Right click me'], self.listed())

        item = self.panel.chat_list.item(1)
        pos = self.panel.chat_list.visualItemRect(item).center()
        with mock.patch.object(QtWidgets.QMenu, 'exec_', opened):
            self.panel.chat_menu(pos)
        self.assertEqual(['Unpin', 'Delete'], list(menus[1]))
        no = QtWidgets.QMessageBox.No
        with mock.patch.object(QtWidgets.QMessageBox, 'question',
                               return_value=no):
            menus[1]['Delete'].trigger()
        self.assertEqual(['Pinned', 'Right click me'], self.listed())
        yes = QtWidgets.QMessageBox.Yes
        with mock.patch.object(QtWidgets.QMessageBox, 'question',
                               return_value=yes):
            menus[1]['Delete'].trigger()
        self.assertEqual([], self.listed())
        self.assertEqual([], self.panel.messages)
        self.assertEqual([], os.listdir(self.folder))

    def test_deleting_another_chat_keeps_this_one(self):
        self.ask('Delete me')
        self.panel.new_chat()
        self.ask('Keep me')
        other = self.panel.chat_store.list()[1]['id']
        self.panel.delete_chat(other, confirm=False)
        self.assertEqual(['Keep me'], self.listed())
        self.assertEqual(['Keep me'], self.shown())

    def test_leaving_a_chat_mid_reply(self):
        self.fake = Slow(store=self.store, prefs=self.prefs)
        self.panel.send('Slow question')
        wait_for(lambda: self.panel.reply)
        self.panel.new_chat()
        self.fake.go.set()
        wait_for(lambda: not self.panel.left_threads)
        self.assertEqual([], self.panel.messages)
        self.assertEqual('', self.panel.transcript.toPlainText())
        self.click('Slow question')
        self.assertEqual(['user', 'assistant'],
                         [m['role'] for m in self.panel.messages])
        self.assertEqual('Thinking', self.panel.messages[1]['content'])

    def test_messages_show_when_they_were_sent(self):
        self.ask('What time is it?')
        for message in self.panel.messages:
            self.assertAlmostEqual(time.time(), message['time'], delta=60)
        text = self.panel.transcript.toPlainText()
        self.assertIn('Today', text)
        self.assertIn(chat_render.clock(self.panel.messages[0]['time']),
                      text)

    def test_the_day_is_shown_where_it_changes(self):
        self.ask('First')
        last_week = time.time() - 7 * 24 * 3600
        for message in self.panel.messages:
            message['time'] = last_week
        self.ask('Again')
        self.panel.render()
        text = self.panel.transcript.toPlainText()
        self.assertEqual(1, text.count('Today'))
        self.assertEqual(1, text.count(chat_render.day_name(last_week)))
        self.assertIn(chat_render.day_name(last_week), text)
        self.assertLess(text.index(chat_render.day_name(last_week)),
                        text.index('Today'))


class WhenTests(unittest.TestCase):

    now = datetime.datetime(2026, 11, 7, 15, 0)

    def at(self, *args):
        return datetime.datetime(*args).timestamp()

    def test_the_clock(self):
        self.assertEqual('3:42 PM', chat_render.clock(
            self.at(2026, 11, 7, 15, 42)))
        self.assertEqual('12:05 AM', chat_render.clock(
            self.at(2026, 11, 7, 0, 5)))
        self.assertEqual('12:00 PM', chat_render.clock(
            self.at(2026, 11, 7, 12, 0)))

    def test_the_day(self):
        day = chat_render.day_name
        self.assertEqual('Today', day(self.at(2026, 11, 7, 1), self.now))
        self.assertEqual('Yesterday', day(self.at(2026, 11, 6, 23),
                                          self.now))
        self.assertEqual('Monday, November 2',
                         day(self.at(2026, 11, 2), self.now))
        self.assertEqual('Tuesday, December 30, 2025',
                         day(self.at(2025, 12, 30), self.now))

    def test_the_list_says_it_short(self):
        short = chat_render.short_when
        self.assertEqual('9:30 AM', short(self.at(2026, 11, 7, 9, 30),
                                          self.now))
        self.assertEqual('Yesterday', short(self.at(2026, 11, 6), self.now))
        self.assertEqual('Monday', short(self.at(2026, 11, 2), self.now))
        self.assertEqual('Oct 1', short(self.at(2026, 10, 1), self.now))
        self.assertEqual('Dec 30, 2025', short(self.at(2025, 12, 30),
                                               self.now))


class ChatStoreTests(unittest.TestCase):

    def test_the_title_is_the_start_of_the_first_question(self):
        self.assertEqual('Chat', chats.title_for([]))
        long = 'word ' * 40
        title = chats.title_for([{'role': 'user', 'shown': long}])
        self.assertLessEqual(len(title), chats.TITLE_LENGTH)
        self.assertTrue(title.endswith('...'))

    def test_only_what_is_needed_is_kept(self):
        store = chats.ChatStore(None)
        store.save({'id': 'a', 'messages': [
            {'role': 'user', 'content': 'c', 'shown': 's', 'time': 1,
             'extra': object()}]})
        self.assertEqual([{'role': 'user', 'content': 'c', 'shown': 's',
                           'time': 1}], store.load('a')['messages'])

    def test_a_damaged_chat_is_left_out(self):
        folder = tempfile.mkdtemp(prefix='nxt_chats_')
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        store = chats.ChatStore(folder)
        store.save({'id': 'good', 'messages': [{'role': 'user',
                                                'content': 'hi'}]})
        with open(os.path.join(folder, 'bad.json'), 'w') as fp:
            fp.write('{"id": ')
        self.assertEqual(['good'], [c['id'] for c in store.list()])


if __name__ == '__main__':
    unittest.main()
