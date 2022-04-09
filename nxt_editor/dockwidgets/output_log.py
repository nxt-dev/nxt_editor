# Built-in
import logging
import re
from code import InteractiveConsole
import sys
import os
import time

# External
from Qt import QtWidgets, QtGui, QtCore

# Internal
import nxt_editor
from nxt_editor import user_dir
from nxt_editor.dockwidgets.dock_widget_base import DockWidgetBase
from nxt import nxt_log
from nxt_editor import LoggingSignaler, colors

logger = logging.getLogger(nxt_editor.LOGGER_NAME)


class VisualLogHandler(logging.Handler):
    def __init__(self, output_log):
        logging.Handler.__init__(self)
        self.setFormatter(nxt_log.nxt_formatter)
        self.signaller = LoggingSignaler()
        self.signaller.signal.connect(self.update)
        self.target_output_log = output_log

    @staticmethod
    def format_links(message, links):
        """Given a message string and a list of links, replace every occurance
        of each given link in the message with a link.

        :param message: string containing unformatted links
        :type message: str
        :param links: list of strings to format into links
        :type links: list
        :return: message with links replacing original text
        :rtype: str
        """
        # Determine max length and sort links by length
        links_by_length = {}
        max_length = 0
        for link_str in links:
            length = len(link_str)
            links_by_length.setdefault(length, [])
            links_by_length[length].append(link_str)
            if length > max_length:
                max_length = length
        # search_message is always length of original string. When searching,
        # found link_str are replaced with % to prevent links within links.
        search_message = str(message)
        out_mesage = ''
        # Gather matches list that is ordered from left to right
        matches = []
        for i in reversed(range(max_length + 1)):
            for link_str in links_by_length.get(i, []):
                length = len(link_str)
                new_search = search_message
                for new_match in re.finditer(link_str, search_message):
                    start = new_match.start()
                    end = new_match.end()
                    filler = length*'%'
                    new_search = new_search[:start] + filler + new_search[end:]
                    # Order matches from left to right based on start index
                    if len(matches) == 0:
                        matches.append(new_match)
                    else:
                        for m in matches:
                            if start < m.start():
                                matches.insert(0, new_match)
                                break
                        else:
                            matches.append(new_match)
                search_message = new_search
        # assemble formatted message using indices of matches.
        prev_idx = 0
        for match in matches:
            out_mesage += message[prev_idx:match.start()]
            out_mesage += nxt_log.make_link(match.re.pattern)
            prev_idx = match.end()
        out_mesage += message[prev_idx:]

        return out_mesage

    def format(self, record):
        if isinstance(record.msg, tuple):
            text = record.msg[0]
            original_msg = record.msg
            multi = True
        else:
            text = record.msg
            original_msg = text
            multi = False
        try:
            links = record.links
        except AttributeError:
            links = []
        if links:
            text = self.format_links(text, links)
        msg = '<font face="Roboto Mono" color="white">{}</font>'.format(text)
        if multi:
            replacement = (msg, record.msg[1])
        else:
            replacement = msg
        record.msg = replacement
        formatted = super(VisualLogHandler, self).format(record)
        record.msg = original_msg
        return formatted

    def emit(self, record):
        self.signaller.signal.emit(record)

    def update(self, record):
        text = self.format(record)
        text += '\n'
        self.target_output_log.write_rich_output(text, level=record.levelno)


class WriteDuper(QtCore.QObject):
    message_written = QtCore.Signal(str, float)

    def __init__(self, orig_obj):
        """Given an object to wrap, and a method to use as write. Produces an
        object that can be used as a proxy for the original to duplicate
        write calls both to given write function as well as to original object.

        Designed for wrapping sys.stdout and sys.stderr to duplicate output.

        :param orig_obj: Object to produce wrapper for
        :type orig_obj: object
        """
        super(WriteDuper, self).__init__()
        self._orig_obj = orig_obj

    def __getattr__(self, attr):
        if attr in self.__dict__:
            return getattr(self, attr)
        return getattr(self._orig_obj, attr)

    def write(self, val):
        self.message_written.emit(val, time.time())
        self._orig_obj.write(val)


class FileTailingThread(QtCore.QThread):
    """A QThread to continuously monitor a file path and signal when text
    is added. On initial start, if the watched file has existing text, the
    the first signal will contain all the initial text.
    """
    new_text = QtCore.Signal(str)

    def __init__(self, path):
        """Watch given path

        :param path: [description]
        :type path: [type]
        """
        super(FileTailingThread, self).__init__()
        self.watch_path = path
        self.last_mtime = 0
        self.last_read_pos = 0

    def run(self):
        while not self.isInterruptionRequested():
            # Consider using a QTimer instead of a thread... -LB
            time.sleep(.2)
            try:
                current_mtime = os.path.getmtime(self.watch_path)
            except OSError:
                # We consume this error because we're watching a file path
                # and the file may be deleted and re-created at any moment.
                continue
            if current_mtime == self.last_mtime:
                continue
            self.last_mtime = current_mtime
            with open(self.watch_path, 'r') as fp:
                fp.seek(self.last_read_pos)
                new_text = fp.read()
            self.last_read_pos += len(new_text)
            self.new_text.emit(new_text)


class OutputLog(DockWidgetBase):
    write_raw = QtCore.Signal(str, float)

    def __init__(self, graph_model=None, parent=None):
        super(OutputLog, self).__init__('Output Log', graph_model=graph_model,
                                        minimum_height=100, parent=parent)
        self.main_frame = QtWidgets.QFrame(self)
        self.main_frame.setStyleSheet('background-color: #3E3E3E; '
                                      'border-radius: 0px;')
        self.main_layout = QtWidgets.QVBoxLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.setWidget(self.main_frame)
        self.main_frame.setLayout(self.main_layout)

        # Rich Output
        self.rich_output_textedit = OutputTextBrowser(self)
        self.log_filter_button = LogFilterButton()
        self.clear_rich_button = QtWidgets.QPushButton('Clear Log')
        self.clear_rich_button.pressed.connect(self.rich_output_textedit.clear)

        self.buttons_layout = QtWidgets.QHBoxLayout()
        self.buttons_layout.addWidget(self.log_filter_button)
        self.buttons_layout.addStretch(stretch=1)
        self.buttons_layout.addWidget(self.clear_rich_button)

        self.rich_output_layout = QtWidgets.QVBoxLayout()
        self.rich_output_layout.setContentsMargins(0, 0, 0, 0)
        self.rich_output_layout.setSpacing(0)
        self.rich_output_layout.addWidget(self.rich_output_textedit)
        self.rich_output_layout.addSpacing(3)
        self.rich_output_layout.addLayout(self.buttons_layout)
        self.rich_output_page = QtWidgets.QWidget()
        self.rich_output_page.setLayout(self.rich_output_layout)
        # Raw Output
        self.raw_output_textedit = OutputTextEdit(self)
        console_locals = {'main_window': parent}
        self.python_edit = PythonConsoleLineEdit(locals=console_locals)

        self.python_layout = QtWidgets.QHBoxLayout()
        self.python_layout.addWidget(QtWidgets.QLabel("Python: "))
        self.python_layout.addWidget(self.python_edit, stretch=1)
        self.clear_raw_button = QtWidgets.QPushButton('Clear Log')
        self.clear_raw_button.pressed.connect(self.raw_output_textedit.clear)
        self.python_layout.addWidget(self.clear_raw_button)

        self.raw_output_layout = QtWidgets.QVBoxLayout()
        self.raw_output_layout.setContentsMargins(0, 0, 0, 0)
        self.raw_output_layout.setSpacing(0)
        self.raw_output_layout.addWidget(self.raw_output_textedit)
        self.raw_output_layout.addSpacing(3)
        self.raw_output_layout.addLayout(self.python_layout)
        self.raw_output_page = QtWidgets.QWidget()
        self.raw_output_page.setLayout(self.raw_output_layout)
        self.write_raw.connect(self.write_raw_output)
        # Tabs
        self.tabs_widget = QtWidgets.QTabWidget()
        self.tabs_widget.addTab(self.rich_output_page, 'Rich Output')
        self.tabs_widget.addTab(self.raw_output_page, 'Raw Output')

        self.main_layout.addWidget(self.tabs_widget)

        self.log_watcher = None
        self.wrapped_stdout = None
        self.wrapped_stderr = None
        self.removed_stderr_handler = None
        self.replaced_stderr_handler = None
        self.wrap_std_streams_for_raw_output()

        # Catch-up visual log to file log
        with open(self.parent().nxt.log_file, 'r') as fp:
            catch_up = fp.read()
        catch_up = catch_up.rstrip()  # removing hanging newlines.
        self.rich_output_textedit.append(catch_up)

        # Install visual handler to output nxt logging to rich log
        self.visual_handler = VisualLogHandler(self)
        self.visual_handler.addFilter(self.log_filter_button)
        nxt_logger = logging.getLogger('nxt')
        nxt_logger.addHandler(self.visual_handler)

    def wrap_std_streams_for_raw_output(self):
        if self.log_watcher:
            self.log_watcher.requestInterruption()
        if self.wrapped_stderr or self.wrapped_stdout:
            logger.debug("std streams already wrapped, not re-wrapping")
            return
        # Make our "Raw Output" log stand in for stdout and stderr
        self.wrapped_stdout = WriteDuper(sys.stdout)
        self.wrapped_stdout.message_written.connect(self.write_raw_output)
        sys.stdout = self.wrapped_stdout
        self.wrapped_stderr = WriteDuper(sys.stderr)
        self.wrapped_stderr.message_written.connect(self.write_raw_output)
        sys.stderr = self.wrapped_stderr

        # Nxt log maintainence
        # nxt's logging goes out stderr and has started before output log,
        # replace existing nxt stdout/err handlers.
        nxt_logger = logging.getLogger('nxt')
        replace_handler = None
        for handler in nxt_logger.handlers:
            if not isinstance(handler, logging.StreamHandler):
                continue
            if handler.stream == sys.__stderr__:
                replace_handler = handler
                break
        if replace_handler:
            self.removed_stderr_handler = replace_handler
            nxt_logger.removeHandler(handler)

            stderr_handler = logging.StreamHandler(self.wrapped_stderr)
            stderr_handler.setLevel(replace_handler.level)
            self.replaced_stderr_handler = stderr_handler
            stderr_handler.setFormatter(nxt_log.nxt_formatter)
            nxt_logger.addHandler(stderr_handler)

    def unwrap_std_streams(self):
        if not (self.wrapped_stdout and self.wrapped_stderr):
            # Not wrapped
            return
        # Wrapping
        sys.stdout = self.wrapped_stdout._orig_obj
        sys.stderr = self.wrapped_stderr._orig_obj
        # Nxt log maintainence
        if self.replaced_stderr_handler:
            nxt_logger = logging.getLogger('nxt')
            nxt_logger.removeHandler(self.replaced_stderr_handler)
            self.replaced_stderr_handler = None
        if self.removed_stderr_handler:
            nxt_logger.addHandler(self.removed_stderr_handler)
            self.removed_stderr_handler = None

    def write_raw_output(self, val, msg_time=0.):
        """Write text to the raw output textedit. May write to the rich out
        if there is a stage model and its current runtime layer is actively
        running.
        The use of the word write here is specific, no newlines are
        added implicitly, must be added
        via input.
        :param msg_time: Optional time when the message was processed,
        if no is given the val will never be logged to the rich log.
        :param val: Text to add to textedit
        :type val: str
        """
        self._write_raw_output(val)
        if not self.stage_model:
            return
        curr_rt_layer = self.stage_model.current_rt_layer
        if not (curr_rt_layer and
                curr_rt_layer.cache_layer.was_during_node_exec(msg_time)):
            return
        if self.log_filter_button.is_level_enabled(nxt_log.NODEOUT):
            # Intentionally breaking html syntax here. Printing type(object)
            # was being interpreted as html. <class 'type'>
            self.write_rich_output(val.replace('<', '&lt;'))

    def _write_raw_output(self, val):
        """Write text to the raw output textedit. Dose NOT write to the rich
        output. The use of the word write here is specific, no newlines are
        added implicitly, must be added via input.
        :param val: Text to add to textedit
        :type val: str
        """
        _max = self.raw_output_textedit.verticalScrollBar().maximum()
        cur = self.raw_output_textedit.verticalScrollBar().value()
        self.raw_output_textedit.moveCursor(QtGui.QTextCursor.End)
        self.raw_output_textedit.insertPlainText(val)
        if _max == cur:
            new_max = self.raw_output_textedit.verticalScrollBar().maximum()
            self.raw_output_textedit.verticalScrollBar().setValue(new_max)
        else:
            self.raw_output_textedit.verticalScrollBar().setValue(cur)

    def write_rich_output(self, val, level=None):
        """Neighbor to write_raw_output. Use of write as naming is specific,
        no newlines created from thin air, must come form input.

        :param val: text to add
        :type val: str
        :param level: logging level to color text as, defaults to None
        :type level: int, optional
        """
        _max = self.rich_output_textedit.verticalScrollBar().maximum()
        cur = self.rich_output_textedit.verticalScrollBar().value()
        self.rich_output_textedit.moveCursor(QtGui.QTextCursor.End)
        if val == '\n':
            self.rich_output_textedit.append('')
        else:
            final_newline = False
            if val.endswith('\n'):
                final_newline = True
                text = val[:-1]
            else:
                text = val
            color = colors.LOGGING_COLORS.get(level, 'white')
            html = '<font face="Roboto Mono" color="{}">'.format(color)
            style = ("<style type='text/css'> "
                     "pre {margin: 0; font-family: 'Roboto Mono';} "
                     "</style>")
            text = style + ("<pre>{}</pre>".format(text))
            html += text + '</font>'
            self.rich_output_textedit.insertHtml(html)
            if final_newline:
                self.rich_output_textedit.append('')
        if _max == cur:
            new_max = self.rich_output_textedit.verticalScrollBar().maximum()
            self.rich_output_textedit.verticalScrollBar().setValue(new_max)
        else:
            self.rich_output_textedit.verticalScrollBar().setValue(cur)

    def tail_file_for_raw_output(self, file_path):
        """Treats the given file as what should be displayed in "raw output"
        Spawns a thread that continually watches given file for modifictions
        and appends new lines to the end of raw output. If this has not been
        called before, and nxt log has wrapped stdout, stdout will be restored
        to default and given file will be appended below. If this has been
        called before, successive calls will replace existing file, and
        continue to append below existing log.

        :param file_path: file to treat as raw output
        :type file_path: str
        """
        self.unwrap_std_streams()
        if self.log_watcher:
            self.log_watcher.requestInterruption()
        self.log_watcher = FileTailingThread(file_path)
        self.log_watcher.new_text.connect(self.write_raw_output)
        self.log_watcher.start()

    def link_clicked(self, link):
        view = self.parent().get_current_view()
        if not view:
            return
        model = view.model
        link = link.toString()
        model.select_and_frame(link)

    def closeEvent(self, event):
        if self.log_watcher:
            self.log_watcher.requestInterruption()
        super(OutputLog, self).closeEvent(event)


class OutputTextEdit(QtWidgets.QTextEdit):
    def __init__(self, parent):
        super(OutputTextEdit, self).__init__(parent=parent)
        self._parent = parent
        self.setStyleSheet(self.parent().parent().styleSheet())
        self.setReadOnly(True)
        self.setFont(QtGui.QFont('Roboto Mono', 10))

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        menu.addAction('Clear', self.clear)
        menu.addAction(self._parent.parent().app_actions.clear_logs_action)
        menu.exec_(event.globalPos())


class OutputTextBrowser(QtWidgets.QTextBrowser):
    def __init__(self, parent):
        super(OutputTextBrowser, self).__init__(parent=parent)
        self._parent = parent
        self.anchorClicked.connect(self.parent().link_clicked)
        self.setStyleSheet(self.parent().parent().styleSheet())
        self.setOpenLinks(False)
        self.setFont(QtGui.QFont('Roboto Mono', 10))

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu()
        menu.addAction('Clear', self.clear)
        menu.addAction(self._parent.parent().app_actions.clear_logs_action)
        menu.exec_(event.globalPos())


class LogFilterButton(QtWidgets.QPushButton):
    VISUAL_LOG_LEVELS = [
        logging.DEBUG,
        logging.INFO,
        logging.WARNING,
        logging.ERROR,
        logging.CRITICAL,
        nxt_log.NODEOUT,
        nxt_log.COMPINFO,
        nxt_log.EXECINFO,
        nxt_log.GRAPHERROR,
        nxt_log.SOCKET
    ]
    PREF_KEY = user_dir.USER_PREF.LOG_FILTERS

    def __init__(self, *args, **kwargs):
        super(LogFilterButton, self).__init__('Filter Log', *args, **kwargs)
        self.menu = QtWidgets.QMenu()
        self.lvl_actions = {}
        for lvl in self.VISUAL_LOG_LEVELS:
            lvl_name = logging.getLevelName(lvl)
            new_action = self.menu.addAction(lvl_name)
            new_action.setCheckable(True)
            new_action.setChecked(True)
            self.lvl_actions[lvl] = new_action
        self.all_action = self.menu.addAction('All')
        self.all_action.setCheckable(True)
        self.all_action.setChecked(True)
        self.setMenu(self.menu)
        self.load_filters_from_pref()
        self.menu.triggered.connect(self.action_triggered)

    def filter(self, record):
        """"filter" for use in logging handlers.
        Name is critical, as logging calls `inst.filter` on given instance.
        """
        return self.is_level_enabled(record.levelno)

    def is_level_enabled(self, lvl):
        action = self.lvl_actions.get(lvl, None)
        if not action:
            # If we don't know we don't care.
            return True
        return action.isChecked()

    def load_filters_from_pref(self):
        pref_filters = user_dir.user_prefs.get(self.PREF_KEY)
        if not pref_filters:
            return
        for lvl, checked in pref_filters.items():
            lvl = int(lvl)
            action = self.lvl_actions.get(lvl)
            if not action:
                continue
            action.setChecked(checked)

    def action_triggered(self, action):
        if action == self.all_action:
            for other_action in self.lvl_actions.values():
                # don't want to recurse this method.
                other_action.setChecked(action.isChecked())
        self.save_filters_to_pref()

    def save_filters_to_pref(self):
        """Saves filter settings to a user preference.
        """
        output = {}
        for lvl, action in self.lvl_actions.items():
            output[lvl] = action.isChecked()
        user_dir.user_prefs[self.PREF_KEY] = output


class PythonConsoleLineEdit(QtWidgets.QLineEdit):
    def __init__(self, locals={}):
        super(PythonConsoleLineEdit, self).__init__('')
        self.console = InteractiveConsole(locals, '<nxt console>')
        self.returnPressed.connect(self.on_return)

    def on_return(self):
        need_more = self.console.push(self.text())
        if not need_more:
            self.clear()


class QtLogStreamHandler(nxt_log.LogRecordStreamHandler):
    """Handles logs by emitting the log record to a QtCore.Signal"""
    @classmethod
    def get_handler(cls, signal):
        """Get the QtLogStreamHandler class with the provided signal
        assigned to it. Meant to only be called once per UI session.
        :param signal: QtCore.Signal that takes a logging.LogRecord
        :return: QtLogStreamHandler
        """
        cls.new_log = signal
        return cls

    def handle_log_record(self, record):
        self.new_log.emit(record)
