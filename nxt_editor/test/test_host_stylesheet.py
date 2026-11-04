"""The editor's stylesheet works without the application having it too.

In a host such as Maya the application is the host's, so the editor's
widgets only get the stylesheet set on the editor's window. That copy was
read with str() of a QByteArray, a bytes literal Qt cannot parse, so in Maya
the editor lost its styling and the workflow buttons, too short for their
rounded corners without its padding, were drawn as plain rectangles.
"""
# Builtin
import os
import re
import sys
import unittest

# External
from Qt import QtWidgets

# Internal
import nxt_editor

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
QSS = os.path.join(os.path.dirname(nxt_editor.__file__), 'resources',
                   'styles', 'dark', 'dark.qss')
# What a workflow button sets on itself.
BUTTON_STYLE = ('QPushButton {background-color: #606060; '
                'border-radius: 9px; border: none;}')


class HostStylesheet(unittest.TestCase):

    def test_it_is_the_text_on_disk(self):
        with open(QSS, 'rb') as fp:
            self.assertEqual(fp.read().decode('utf-8'),
                             nxt_editor.stylesheet())

    def test_a_window_with_it_rounds_the_workflow_buttons(self):
        old = app.styleSheet()
        app.setStyleSheet('')
        window = QtWidgets.QWidget()
        try:
            window.setStyleSheet(nxt_editor.stylesheet())
            layout = QtWidgets.QVBoxLayout(window)
            button = QtWidgets.QPushButton('Build')
            button.setStyleSheet(BUTTON_STYLE)
            layout.addWidget(button)
            window.show()
            app.processEvents()
            # Qt drops a radius that does not fit, so the corners are only
            # round when the button is at least twice as tall.
            self.assertGreaterEqual(button.height(), 18)
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()
            app.setStyleSheet(old)

    def test_nothing_reads_it_with_str(self):
        package = os.path.dirname(nxt_editor.__file__)
        pattern = re.compile(r'str\(\s*\w+\.readAll\(\)\s*\)')
        found = []
        for root, dirs, files in os.walk(package):
            dirs[:] = [d for d in dirs if d not in ('test', '__pycache__')]
            for name in files:
                if name.endswith('.py'):
                    path = os.path.join(root, name)
                    with open(path, encoding='utf-8') as fp:
                        if pattern.search(fp.read()):
                            found.append(os.path.relpath(path, package))
        self.assertEqual([], found)


if __name__ == '__main__':
    unittest.main()
