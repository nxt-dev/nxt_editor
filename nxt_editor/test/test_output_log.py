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


class TestLongLogs(OutputLogTestCase):
    """Resizing was slow with a long log, which re-wrapped every line."""

    def tearDown(self):
        self.log.wrap_action.setChecked(True)
        self.log.setFloating(False)
        app.processEvents()

    def test_logs_keep_a_limited_number_of_lines(self):
        from nxt_editor.dockwidgets.output_log import OutputLog
        limit = OutputLog.MAX_LINES
        for text_edit in self.log.text_edits():
            self.assertEqual(limit, text_edit.document().maximumBlockCount())
        lines = ['line %d' % i for i in range(limit + 50)]
        self.log._write_raw_output('\n'.join(lines))
        document = self.log.raw_output_textedit.document()
        self.assertLessEqual(document.blockCount(), limit)
        self.assertEqual(lines[-1], document.lastBlock().text())
        self.assertNotEqual(lines[0], document.firstBlock().text())

    def test_wrap_toggle_changes_both_logs_and_is_remembered(self):
        from nxt_editor import user_dir
        key = user_dir.USER_PREF.OUTPUT_LOG_WRAP
        self.log.wrap_action.setChecked(False)
        for text_edit in self.log.text_edits():
            self.assertEqual(QtWidgets.QTextEdit.NoWrap,
                             text_edit.lineWrapMode())
        self.assertIs(False, user_dir.user_prefs.get(key))
        self.log.wrap_action.setChecked(True)
        for text_edit in self.log.text_edits():
            self.assertEqual(QtWidgets.QTextEdit.WidgetWidth,
                             text_edit.lineWrapMode())
        self.assertIs(True, user_dir.user_prefs.get(key))

    def test_wrap_is_in_both_right_click_menus(self):
        for text_edit in self.log.text_edits():
            menu = QtWidgets.QMenu()
            self.log.add_menu_actions(menu, text_edit)
            self.assertIn(self.log.wrap_action, menu.actions())

    def test_new_log_reads_the_preference(self):
        from nxt_editor import user_dir
        from nxt_editor.dockwidgets.output_log import OutputLog
        user_dir.user_prefs[user_dir.USER_PREF.OUTPUT_LOG_WRAP] = False
        other = OutputLog(parent=self.win)
        try:
            self.assertFalse(other.wrap_action.isChecked())
            self.assertEqual(QtWidgets.QTextEdit.NoWrap,
                             other.raw_output_textedit.lineWrapMode())
        finally:
            other.detach_from_logging()
            other.hide()
            user_dir.user_prefs[user_dir.USER_PREF.OUTPUT_LOG_WRAP] = True

    def test_unwrapped_log_does_not_relayout_on_resize(self):
        text_edit = self.log.raw_output_textedit
        self.log.tabs_widget.setCurrentWidget(text_edit.parent())
        self.log.wrap_action.setChecked(False)
        bar = text_edit.verticalScrollBar()
        self.resize_log(900)
        self.fill(self.log._write_raw_output)
        tall = bar.maximum()
        self.resize_log(500)
        self.assertEqual(tall, bar.maximum())


class TestPrintedOutput(OutputLogTestCase):
    """Printed output is gathered and written to the logs together. Written
    a piece at a time, a node that printed a line at a time ran hundreds of
    times slower in the editor than on its own."""

    def setUp(self):
        self.log.flush_output()
        super(TestPrintedOutput, self).setUp()

    def lines(self):
        return self.log.raw_output_textedit.toPlainText().splitlines()

    def wait_for_flush(self):
        timer = QtCore.QElapsedTimer()
        timer.start()
        while timer.elapsed() < self.log.FLUSH_MS * 4:
            app.processEvents()

    def test_output_is_written_together(self):
        writes = []
        write = self.log._write_raw_output
        self.log._write_raw_output = lambda val: (writes.append(val),
                                                  write(val))
        try:
            for i in range(500):
                self.log.write_raw_output('line')
                self.log.write_raw_output(' %d\n' % i)
            self.wait_for_flush()
        finally:
            del self.log._write_raw_output
        self.assertEqual(1, len(writes))
        self.assertEqual(['line %d' % i for i in range(500)], self.lines())

    def test_output_shows_without_a_log_record(self):
        self.log.write_raw_output('on its own\n')
        self.wait_for_flush()
        self.assertEqual(['on its own'], self.lines())
        self.assertEqual([], self.log.pending_output)

    def test_a_log_record_comes_after_the_output_before_it(self):
        self.log.write_raw_output('before\n', 1.0)
        self.log.write_raw_output('after\n', 3.0)
        self.log.flush_output(until=2.0)
        self.assertEqual(['before'], self.lines())
        self.assertEqual([('after\n', 3.0)], self.log.pending_output)
        self.log.flush_output()
        self.assertEqual(['before', 'after'], self.lines())


if __name__ == '__main__':
    unittest.main()
