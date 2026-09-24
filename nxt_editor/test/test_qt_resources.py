"""The editor's icons, fonts and styles, registered with no rcc.

They used to be compiled into qresources.py by rcc, which is a per platform
binary most hosts don't put on PATH, and a package that went out without
that file could not load in Maya. They are read from resources/ instead
and handed to Qt in the format rcc writes, so every ":" path the editor
uses has to read back exactly what is on disk.
"""
# Builtin
import os
import re
import shutil
import tempfile
import unittest

# External
from Qt import QtCore

# Internal
from nxt_editor import qt_resources


def read(path):
    handle = QtCore.QFile(path)
    if not handle.open(QtCore.QIODevice.ReadOnly):
        return None
    try:
        return bytes(handle.readAll())
    finally:
        handle.close()


class TestQtResources(unittest.TestCase):
    def test_every_listed_file_reads_back_as_it_is_on_disk(self):
        files = qt_resources.read_qrc()
        self.assertGreater(len(files), 200)
        for path, source in files.items():
            with open(source, 'rb') as fp:
                self.assertEqual(read(':' + path), fp.read(), path)

    def test_folders_list_what_the_qrc_puts_in_them(self):
        expected = {}
        for path in qt_resources.read_qrc():
            parts = path.split('/')
            for i in range(1, len(parts)):
                expected.setdefault('/'.join(parts[:i]), set()).add(parts[i])
        for folder, children in expected.items():
            listed = set(QtCore.QDir(':/' + folder).entryList())
            self.assertEqual(listed, children, folder)

    def test_paths_the_editor_uses(self):
        # Every whole ":" path written into the code and the stylesheets,
        # rather than the handful someone thought to list here.
        pattern = re.compile(
            r''':/?((?:icons|fonts|styles|dark_style)/[\w./-]+\.\w+)''')
        package = os.path.dirname(qt_resources.__file__)
        used = set()
        for root, dirs, files in os.walk(package):
            dirs[:] = [d for d in dirs if d not in ('test', '__pycache__')]
            for name in files:
                if name.endswith(('.py', '.qss')):
                    with open(os.path.join(root, name), encoding='utf-8',
                              errors='replace') as fp:
                        used.update(pattern.findall(fp.read()))
        self.assertGreater(len(used), 20)
        missing = sorted(p for p in used if not QtCore.QFile.exists(':' + p))
        self.assertEqual(missing, [])
        self.assertFalse(QtCore.QFile.exists(':icons/icons/not_there.png'))

    def test_registering_again_swaps_in_what_is_on_disk(self):
        # What a reload does: the old registration goes, and a file added
        # to the qrc since is there without anything being rebuilt.
        tmp = tempfile.mkdtemp()
        try:
            with open(os.path.join(tmp, 'extra.txt'), 'wb') as fp:
                fp.write(b'added later')
            qrc = os.path.join(tmp, 'test.qrc')
            with open(qrc, 'w') as fp:
                fp.write('<RCC><qresource prefix="nxt_test">'
                         '<file>extra.txt</file></qresource></RCC>')
            qt_resources.register(qrc)
            self.assertEqual(read(':nxt_test/extra.txt'), b'added later')
        finally:
            qt_resources.register()
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertIsNone(read(':nxt_test/extra.txt'))
        self.assertTrue(QtCore.QFile.exists(':styles/styles/dark/dark.qss'))


if __name__ == '__main__':
    unittest.main()
