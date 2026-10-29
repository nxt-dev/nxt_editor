"""Show a layer's file in Explorer, the Finder or the file manager.

Nothing is opened for real: the commands each platform would run are
caught and checked instead.
"""
# Builtin
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

# External
from Qt import QtWidgets

# Internal
from nxt_editor import file_browser

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

from nxt_editor.main_window import MainWindow  # noqa: E402


class ShowInFileBrowser(unittest.TestCase):

    def setUp(self):
        self.folder = os.path.realpath(tempfile.mkdtemp())
        self.file = os.path.join(self.folder, 'graph.nxt')
        with open(self.file, 'w') as f:
            f.write('{}')
        popen = mock.patch.object(file_browser.subprocess, 'Popen')
        run = mock.patch.object(file_browser.subprocess, 'run')
        open_url = mock.patch.object(file_browser.QtGui.QDesktopServices,
                                     'openUrl', return_value=True)
        self.popen = popen.start()
        self.run = run.start()
        self.open_url = open_url.start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def on(self, platform):
        patcher = mock.patch.object(file_browser.sys, 'platform', platform)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_windows_selects_the_file_in_explorer(self):
        self.on('win32')
        self.assertTrue(file_browser.show_in_file_browser(self.file))
        command = self.popen.call_args[0][0]
        self.assertEqual('explorer /select,"{}"'.format(
            os.path.normpath(self.file)), command)

    def test_windows_opens_a_folder(self):
        self.on('win32')
        file_browser.show_in_file_browser(self.folder)
        self.assertEqual(['explorer', os.path.normpath(self.folder)],
                         self.popen.call_args[0][0])

    def test_mac_reveals_the_file_in_the_finder(self):
        self.on('darwin')
        file_browser.show_in_file_browser(self.file)
        self.assertEqual(['open', '-R', self.file],
                         self.popen.call_args[0][0])

    def test_linux_asks_the_file_manager_to_select_the_file(self):
        self.on('linux')
        self.run.return_value = mock.Mock(returncode=0)
        file_browser.show_in_file_browser(self.file)
        command = self.run.call_args[0][0]
        self.assertEqual('dbus-send', command[0])
        self.assertIn('org.freedesktop.FileManager1.ShowItems', command)
        self.assertTrue(command[-2].startswith('array:string:file://'))
        self.open_url.assert_not_called()

    def test_linux_opens_the_folder_without_a_file_manager_service(self):
        self.on('linux')
        self.run.side_effect = OSError('no dbus-send')
        self.assertTrue(file_browser.show_in_file_browser(self.file))
        url = self.open_url.call_args[0][0]
        self.assertEqual(os.path.normcase(self.folder),
                         os.path.normcase(os.path.normpath(url.toLocalFile())))

    def test_a_missing_file_shows_the_nearest_folder_there_is(self):
        self.on('darwin')
        gone = os.path.join(self.folder, 'deleted', 'graph.nxt')
        self.assertTrue(file_browser.show_in_file_browser(gone))
        self.assertEqual(['open', self.folder], self.popen.call_args[0][0])

    def test_an_unsaved_layer_opens_nothing(self):
        self.assertFalse(file_browser.show_in_file_browser(None))
        self.assertFalse(file_browser.show_in_file_browser(''))
        self.popen.assert_not_called()
        self.open_url.assert_not_called()


class LayerMenus(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.win = MainWindow()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None

    def test_the_file_menu_has_it(self):
        action = self.win.layer_actions.show_in_file_browser_action
        self.assertIn(action, self.win.menu_bar.file_menu.actions())
        self.assertEqual(file_browser.ACTION_TEXT, action.text())

    def test_it_shows_the_layer_it_was_given(self):
        action = self.win.layer_actions.show_in_file_browser_action
        layer = mock.Mock(real_path='/some/graph.nxt')
        target = 'nxt_editor.main_window.file_browser.show_in_file_browser'
        model = mock.patch.object(MainWindow, 'model',
                                  new_callable=mock.PropertyMock)
        with mock.patch(target) as show, model:
            action.setData(layer)
            action.trigger()
        show.assert_called_once_with('/some/graph.nxt')


if __name__ == '__main__':
    unittest.main()
