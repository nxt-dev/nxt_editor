"""The Output Log following new text, and how it lays out long lines."""
# Builtin
import os
import sys
import unittest

# External
from Qt import QtCore, QtWidgets

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

# Imported after the application exists, because building the main window
# touches widgets.
from nxt_editor.main_window import MainWindow  # noqa: E402


class OutputLogTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.chdir(os.path.dirname(__file__))
        cls.win = MainWindow()
        cls.win.resize(1200, 900)
        cls.win.show()
        cls.log = cls.win.output_log
        cls.log.show()
        app.processEvents()

    @classmethod
    def tearDownClass(cls):
        cls.win.close()
        cls.win = None

    def setUp(self):
        self.log.rich_output_textedit.clear()
        self.log.raw_output_textedit.clear()
        app.processEvents()

    def fill(self, write, lines=200):
        # Long enough to wrap, so the number of lines on screen, and with
        # it the scroll range, changes with the width.
        for i in range(lines):
            write('line %d %s\n' % (i, 'word ' * 40))
        app.processEvents()

    def resize_log(self, width):
        self.log.setFloating(True)
        self.log.resize(width, 300)
        app.processEvents()


class TestStickToBottom(OutputLogTestCase):

    def tearDown(self):
        self.log.setFloating(False)
        app.processEvents()

    def check_follows_after_resize(self, text_edit, write, fill=None):
        # Only the tab on show is laid out.
        self.log.tabs_widget.setCurrentWidget(text_edit.parent())
        bar = text_edit.verticalScrollBar()
        self.resize_log(900)
        self.fill(fill or write)
        self.assertEqual(bar.maximum(), bar.value())
        # Narrower re-wraps every line, which raises the maximum without
        # the bar moving. The log was at the bottom, so it stays there.
        self.resize_log(500)
        self.assertGreater(bar.maximum(), 0)
        self.assertEqual(bar.maximum(), bar.value())
        self.fill(write, lines=5)
        self.assertEqual(bar.maximum(), bar.value())

    def test_rich_log_follows_after_resize(self):
        # What write_rich_output writes is preformatted and never wraps, but
        # the log it catches up from the log file at start up does.
        rich = self.log.rich_output_textedit
        self.check_follows_after_resize(rich, self.log.write_rich_output,
                                        fill=lambda text: rich.append(text))

    def test_raw_log_follows_after_resize(self):
        self.check_follows_after_resize(self.log.raw_output_textedit,
                                        self.log._write_raw_output)

    def test_scrolled_up_log_stays_put(self):
        text_edit = self.log.raw_output_textedit
        self.log.tabs_widget.setCurrentWidget(text_edit.parent())
        bar = text_edit.verticalScrollBar()
        self.resize_log(700)
        self.fill(self.log._write_raw_output)
        bar.setValue(bar.maximum() // 2)
        app.processEvents()
        held = bar.value()
        self.fill(self.log._write_raw_output, lines=5)
        self.assertEqual(held, bar.value())
        # Back at the bottom it follows again.
        bar.setValue(bar.maximum())
        self.fill(self.log._write_raw_output, lines=5)
        self.assertEqual(bar.maximum(), bar.value())


if __name__ == '__main__':
    unittest.main()
