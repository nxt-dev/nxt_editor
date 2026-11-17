"""Saving over a layer file that something else changed on disk asks first,
and coming back to the editor offers to reload it.

Graphs kept in version control are updated on disk while they are open,
and saving wrote over those updates without a word. The editor notes each
file's modified time and size when it reads or writes it, and compares.
"""
# Builtin
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

# External
from Qt import QtCore, QtWidgets

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor import main_window, user_dir  # noqa: E402
from nxt_editor.dialogs import FileChangedMessage  # noqa: E402
from nxt_editor.main_window import MainWindow  # noqa: E402

PREF = user_dir.USER_PREF.CHECK_DISK_CHANGES


def write_graph(path, nodes):
    with open(path, 'w') as file_object:
        json.dump({'version': '1.17', 'alias': 'graph', 'references': [],
                   'nodes': {n: {} for n in nodes}}, file_object)
    return path


def saved_nodes(path):
    with open(path) as file_object:
        return sorted(json.load(file_object).get('nodes', {}))


class FileChangedOnDisk(unittest.TestCase):

    def setUp(self):
        user_dir.user_prefs[PREF] = True
        self.cwd = os.getcwd()
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix='nxt_on_disk_'))
        self.graph = write_graph(os.path.join(self.tmp, 'graph.nxt'), ['/a'])
        self.win = MainWindow(filepath=self.graph)
        self.win.show()
        app.processEvents()
        self.model = self.win.model
        self.layer = self.model.top_layer
        # As the editor spells it.
        self.path = self.layer.real_path

    def tearDown(self):
        user_dir.user_prefs[PREF] = True
        self.win.hide()
        app.processEvents()
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def change_on_disk(self):
        # Another size as well as another time, so the change shows on a
        # file system with coarse modified times.
        write_graph(self.graph, ['/a', '/from_disk'])

    def save(self, choice):
        with mock.patch.object(FileChangedMessage, 'before_save',
                               return_value=choice) as ask:
            self.win.save_layer(self.layer)
        return ask

    def test_an_unchanged_file_saves_without_asking(self):
        ask = self.save(FileChangedMessage.CANCEL)
        ask.assert_not_called()

    def test_a_changed_file_is_noticed(self):
        self.assertFalse(self.model.layer_file_changed_on_disk(self.path))
        self.change_on_disk()
        self.assertTrue(self.model.layer_file_changed_on_disk(self.path))
        self.assertEqual([self.path],
                         self.model.layer_files_changed_on_disk())

    def test_cancel_leaves_the_file_alone(self):
        self.change_on_disk()
        ask = self.save(FileChangedMessage.CANCEL)
        ask.assert_called_once()
        self.assertEqual(['/a', '/from_disk'], saved_nodes(self.graph))

    def test_overwrite_saves_and_stops_asking(self):
        self.change_on_disk()
        self.save(FileChangedMessage.OVERWRITE)
        self.assertEqual(['/a'], saved_nodes(self.graph))
        ask = self.save(FileChangedMessage.CANCEL)
        ask.assert_not_called()

    def test_reload_uses_reload_source(self):
        self.change_on_disk()
        with mock.patch.object(main_window.ReloadSourceDialog, 'get_layers',
                               return_value=[self.layer]) as dialog:
            ask = self.save(FileChangedMessage.RELOAD)
        ask.assert_called_once()
        dialog.assert_called_once()
        self.assertIn('/from_disk', self.model.stage.top_layer.descendants())
        # Nothing was written, and the file is what is loaded now.
        self.assertEqual(['/a', '/from_disk'], saved_nodes(self.graph))
        self.assertFalse(self.model.layer_file_changed_on_disk(self.path))

    def test_undoing_a_reload_notices_the_change_again(self):
        self.change_on_disk()
        self.model.reload_layers([self.path])
        self.assertFalse(self.model.layer_file_changed_on_disk(self.path))
        self.model.undo()
        self.assertTrue(self.model.layer_file_changed_on_disk(self.path))

    def offer(self, answer):
        with mock.patch.object(FileChangedMessage, 'offer_reload',
                               return_value=answer) as offer:
            self.win.check_files_changed_on_disk()
        return offer

    def test_coming_back_offers_a_reload(self):
        self.change_on_disk()
        offer = self.offer(True)
        offer.assert_called_once()
        self.assertEqual([self.path], offer.call_args.args[0])
        self.assertIn('/from_disk', self.model.stage.top_layer.descendants())

    def test_keep_mine_is_not_asked_again(self):
        self.change_on_disk()
        self.offer(False)
        offer = self.offer(False)
        offer.assert_not_called()
        # Saving over it still asks.
        ask = self.save(FileChangedMessage.CANCEL)
        ask.assert_called_once()

    def test_unsaved_layers_are_named_in_the_offer(self):
        self.model.effected_layers.add(self.path)
        self.change_on_disk()
        offer = self.offer(False)
        self.assertEqual([self.path], list(offer.call_args.args[1]))

    def test_nothing_is_offered_when_nothing_changed(self):
        offer = self.offer(True)
        offer.assert_not_called()

    def test_the_offer_can_be_turned_off(self):
        self.win.app_actions.check_disk_action.trigger()
        self.assertFalse(user_dir.user_prefs.get(PREF))
        self.change_on_disk()
        offer = self.offer(True)
        offer.assert_not_called()

    def send(self, event_type):
        app.sendEvent(self.win, QtCore.QEvent(event_type))
        app.processEvents()

    def test_coming_back_to_the_window_checks(self):
        with mock.patch.object(self.win,
                               'check_files_changed_on_disk') as check:
            self.send(QtCore.QEvent.WindowDeactivate)
            self.send(QtCore.QEvent.WindowActivate)
        check.assert_called_once()

    def test_the_window_coming_up_does_not_check(self):
        # It has only just read its files, and a test, or a script in a
        # host, writing them next is not news.
        with mock.patch.object(self.win,
                               'check_files_changed_on_disk') as check:
            self.send(QtCore.QEvent.WindowActivate)
        check.assert_not_called()


class TheMessages(unittest.TestCase):
    """The questions themselves, answered by pressing their buttons."""

    def answer(self, button_text):
        def press():
            for top in app.topLevelWidgets():
                if isinstance(top, FileChangedMessage) and top.isVisible():
                    for button in top.buttons():
                        if button.text() == button_text:
                            button.click()
                            return
        QtCore.QTimer.singleShot(100, press)

    def test_before_save(self):
        for text, choice in (('Overwrite', FileChangedMessage.OVERWRITE),
                             ('Reload...', FileChangedMessage.RELOAD),
                             ('Cancel', FileChangedMessage.CANCEL)):
            self.answer(text)
            self.assertEqual(choice,
                             FileChangedMessage.before_save('/x/graph.nxt'))

    def test_offer_reload(self):
        self.answer('Reload')
        self.assertTrue(FileChangedMessage.offer_reload(['/x/a.nxt'],
                                                        ['/x/a.nxt']))
        self.answer('Keep Mine')
        self.assertFalse(FileChangedMessage.offer_reload(['/x/a.nxt',
                                                          '/x/b.nxt']))


if __name__ == '__main__':
    unittest.main()
