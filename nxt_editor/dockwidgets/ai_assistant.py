"""The AI Assistant panel: chat with Claude, OpenAI or Grok about the graph.

Only in the Window menu once the assistant is turned on in
Options > AI Assistant. Every chat is kept, so New Chat does not lose the
last one. The list of chats goes back to any of them, and right clicking
one pins it to the top or deletes it.

The assistant looks at the graph with tools (see ai.tools), and with the
toggles under the message box it may also change the graph and run code.
"""
# Builtin
import functools
import logging
import time

# External
from Qt import QtCore, QtWidgets

# Internal
import nxt_editor
from nxt_editor import theme, user_dir
from nxt_editor.ai import (chat_render, chats, claude_code, context,
                           graph_actions, providers, tools)
from nxt_editor.ai.memory import Memory
from nxt_editor.ai.workers import ChatThread, TaskThread
from nxt_editor.dockwidgets.dock_widget_base import DockWidgetBase

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

ACCENT = '#4f86d6'
STYLE = theme.fill('''
#aiPanel QLabel#aiMuted { color: #8a8a8a; }
#aiPanel QLabel#aiHeading { color: #8a8a8a; font-weight: bold;
    letter-spacing: 1px; font-size: 11px; }
#aiPanel QPushButton#aiGhost { background: {RAISED}; color: {TEXT};
    border: 1px solid #3c3c3c; border-radius: 5px; padding: 3px 10px; }
#aiPanel QPushButton#aiGhost:hover { background: #343434;
    border-color: #555555; }
#aiPanel QPushButton#aiGhost:pressed { background: {RAISED}; }
#aiPanel QPushButton#aiGhost:disabled { color: #6a6a6a;
    border-color: {BORDER}; }
#aiPanel QListWidget#aiChats { background: {GRAPH};
    border: 1px solid {BORDER}; border-radius: 6px; padding: 3px;
    outline: 0; }
#aiPanel QListWidget#aiChats::item { color: #d0d0d0; padding: 5px 8px;
    border-radius: 4px; margin: 1px 0; }
#aiPanel QListWidget#aiChats::item:hover { background: #2a2a2a; }
#aiPanel QListWidget#aiChats::item:selected { background: #2c3a4c;
    color: #ffffff; }
#aiPanel QListWidget#aiChats::item:disabled { background: transparent;
    color: #7c7c7c; padding: 6px 8px 2px 8px; }
#aiPanel QTextBrowser#aiTranscript { background: #1c1c1c;
    border: 1px solid {BORDER}; border-radius: 6px; padding: 4px; }
#aiPanel QFrame#aiComposer { background: {GRAPH};
    border: 1px solid {BORDER}; border-radius: 8px; }
#aiPanel QPlainTextEdit#aiInput { background: transparent; border: none;
    color: #e6e6e6; }
#aiPanel QPushButton#aiChip { background: {RAISED}; color: {TEXT_DIM};
    border: 1px solid {BORDER}; border-radius: 10px; padding: 0px 9px;
    min-height: 18px; font-size: 11px; }
#aiPanel QPushButton#aiChip:hover { border-color: {BORDER_STRONG};
    color: #c8c8c8; }
#aiPanel QPushButton#aiChip:checked { background: #26344a;
    color: #cfe0ff; border-color: #4a6f9e; }
#aiPanel QPushButton#aiChip[risk="true"]:checked { background: #43301c;
    color: #ffd29c; border-color: #a8763a; }
#aiPanel QPushButton#aiSend { background: ACCENT; color: #ffffff;
    border: none; border-radius: 6px; padding: 4px 16px;
    font-weight: bold; }
#aiPanel QPushButton#aiSend:hover { background: #5d94e3; }
#aiPanel QPushButton#aiSend:disabled { background: #2e3746;
    color: #7a8494; }
#aiPanel QPushButton#aiSend[stop="true"] { background: #b0473f; }
#aiPanel QPushButton#aiSend[stop="true"]:hover { background: #c45850; }
#aiPanel QSplitter::handle { background: transparent; }
#aiPanel QFrame#aiAsk { background: #2e2716; border: 1px solid #8a6d32;
    border-radius: 8px; }
#aiPanel QFrame#aiAsk QLabel { background: transparent; border: none; }
#aiPanel QLabel#aiAskTitle { color: #f0d9a8; font-weight: bold; }
#aiPanel QLabel#aiAskPath { color: #ffffff; font-family: Consolas,
    'DejaVu Sans Mono', Menlo, monospace; }
''').replace('ACCENT', ACCENT)


def _button(text, name):
    button = QtWidgets.QPushButton(text)
    button.setObjectName(name)
    button.setCursor(QtCore.Qt.PointingHandCursor)
    return button


def _chip(text, tip):
    """A small toggle, on or off, for what the assistant may do."""
    chip = _button(text, 'aiChip')
    chip.setCheckable(True)
    chip.setToolTip(tip)
    return chip


class AiAssistant(DockWidgetBase):

    open_settings = QtCore.Signal()

    def __init__(self, title='AI Assistant', parent=None, minimum_width=300,
                 store=None, prefs=None, chat_store=None):
        super(AiAssistant, self).__init__(title=title, parent=parent,
                                          minimum_width=minimum_width)
        self.store = store
        if chat_store is None:
            # Given its own prefs (as tests are), it keeps chats in memory.
            chat_store = chats.ChatStore(chats.CHATS_DIR if prefs is None
                                         else None)
        self.chat_store = chat_store
        self.prefs = prefs if prefs is not None else user_dir.user_prefs
        self.messages = []
        self.chat_id = None
        self.chat_created = None
        self.reply = ''
        self.reply_time = None
        # What the tools did in the reply coming, by call.
        self.reply_tools = []
        self.toolbox = None
        self.memory = Memory(self.prefs)
        # Folders the user let the assistant read in this chat only.
        self.chat_folders = set()
        self.access_loop = None
        self.access_answer = tools.DENY
        self.thread = None
        self.speaker = ''
        self.models_threads = []
        # Replies still ending for a chat that was left.
        self.left_threads = []

        self.main_widget = QtWidgets.QWidget(parent=self)
        self.main_widget.setObjectName('aiPanel')
        self.main_widget.setStyleSheet(STYLE)
        self.setWidget(self.main_widget)
        layout = QtWidgets.QVBoxLayout(self.main_widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        top = QtWidgets.QHBoxLayout()
        top.setSpacing(4)
        self.provider_combo = QtWidgets.QComboBox()
        self.provider_combo.currentIndexChanged.connect(
            self.on_provider_changed)
        top.addWidget(self.provider_combo)
        self.model_combo = QtWidgets.QComboBox()
        self.model_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.model_combo.setMinimumContentsLength(10)
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        top.addWidget(self.model_combo, 1)
        self.settings_button = _button('Settings', 'aiGhost')
        self.settings_button.setToolTip('Sign in, API keys and models')
        self.settings_button.clicked.connect(self.open_settings.emit)
        top.addWidget(self.settings_button)
        layout.addLayout(top)

        self.account_label = QtWidgets.QLabel()
        self.account_label.setObjectName('aiMuted')
        self.account_label.setWordWrap(True)
        layout.addWidget(self.account_label)

        self.setup_label = QtWidgets.QLabel()
        self.setup_label.setWordWrap(True)
        self.setup_label.linkActivated.connect(
            lambda _link: self.open_settings.emit())
        layout.addWidget(self.setup_label)

        chats_top = QtWidgets.QWidget()
        chats_layout = QtWidgets.QVBoxLayout(chats_top)
        chats_layout.setContentsMargins(0, 0, 0, 4)
        chats_layout.setSpacing(4)
        chats_header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel('CHATS')
        title.setObjectName('aiHeading')
        chats_header.addWidget(title)
        chats_header.addStretch()
        self.new_button = _button('+  New Chat', 'aiGhost')
        self.new_button.setToolTip('Start a new chat. This one is kept in '
                                   'the list.')
        self.new_button.clicked.connect(self.new_chat)
        chats_header.addWidget(self.new_button)
        chats_layout.addLayout(chats_header)
        self.chat_list = QtWidgets.QListWidget()
        self.chat_list.setObjectName('aiChats')
        self.chat_list.setToolTip('Right click a chat to pin or delete it')
        self.chat_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.chat_list.customContextMenuRequested.connect(
            self.chat_menu)
        self.chat_list.itemClicked.connect(self.on_chat_clicked)
        self.chat_list.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarAlwaysOff)
        self.chat_list.setTextElideMode(QtCore.Qt.ElideRight)
        chats_layout.addWidget(self.chat_list)

        self.transcript = QtWidgets.QTextBrowser()
        self.transcript.setObjectName('aiTranscript')
        self.transcript.setOpenExternalLinks(True)
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(6)
        self.splitter.addWidget(chats_top)
        self.splitter.addWidget(self.transcript)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([170, 400])
        layout.addWidget(self.splitter, 1)

        code_row = QtWidgets.QHBoxLayout()
        code_row.setSpacing(4)
        code_row.addStretch()
        self.apply_button = _button('Apply Code', 'aiGhost')
        self.apply_button.setToolTip(
            'Replace the selected node\'s code with the last code block in '
            'the reply. Undo puts it back.')
        self.apply_button.clicked.connect(self.apply_code)
        code_row.addWidget(self.apply_button)
        self.copy_button = _button('Copy Code', 'aiGhost')
        self.copy_button.setToolTip('Copy the last code block in the reply.')
        self.copy_button.clicked.connect(self.copy_code)
        code_row.addWidget(self.copy_button)
        layout.addLayout(code_row)

        # Asks before the assistant reads somewhere new, as Claude Code
        # does.
        self.ask_frame = QtWidgets.QFrame()
        self.ask_frame.setObjectName('aiAsk')
        ask_layout = QtWidgets.QVBoxLayout(self.ask_frame)
        ask_layout.setContentsMargins(10, 8, 10, 8)
        ask_layout.setSpacing(4)
        self.ask_title = QtWidgets.QLabel()
        self.ask_title.setObjectName('aiAskTitle')
        self.ask_title.setWordWrap(True)
        ask_layout.addWidget(self.ask_title)
        self.ask_path = QtWidgets.QLabel()
        self.ask_path.setObjectName('aiAskPath')
        self.ask_path.setWordWrap(True)
        self.ask_path.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.ask_path.setTextFormat(QtCore.Qt.PlainText)
        ask_layout.addWidget(self.ask_path)
        self.ask_reason = QtWidgets.QLabel()
        self.ask_reason.setObjectName('aiMuted')
        self.ask_reason.setTextFormat(QtCore.Qt.PlainText)
        self.ask_reason.setWordWrap(True)
        ask_layout.addWidget(self.ask_reason)
        ask_buttons = QtWidgets.QHBoxLayout()
        ask_buttons.setSpacing(4)
        self.allow_button = _button('Allow', 'aiSend')
        self.allow_button.setToolTip('Let it read this folder in this chat')
        self.allow_button.clicked.connect(
            lambda: self.answer_access(tools.ONCE))
        self.always_button = _button('Always allow', 'aiGhost')
        self.always_button.setToolTip(
            'Let it read this folder in every chat. It is remembered in '
            'Options > AI Assistant > Memory, where you can take it back.')
        self.always_button.clicked.connect(
            lambda: self.answer_access(tools.ALWAYS))
        self.deny_button = _button('Deny', 'aiGhost')
        self.deny_button.clicked.connect(
            lambda: self.answer_access(tools.DENY))
        for button in (self.allow_button, self.always_button,
                       self.deny_button):
            ask_buttons.addWidget(button)
        ask_buttons.addStretch()
        ask_layout.addLayout(ask_buttons)
        self.ask_frame.hide()
        layout.addWidget(self.ask_frame)

        # The message box, with what the assistant may do under it.
        composer = QtWidgets.QFrame()
        composer.setObjectName('aiComposer')
        composer_layout = QtWidgets.QVBoxLayout(composer)
        composer_layout.setContentsMargins(8, 6, 6, 6)
        composer_layout.setSpacing(4)
        self.input = QtWidgets.QPlainTextEdit()
        self.input.setObjectName('aiInput')
        self.input.setPlaceholderText('Ask about the graph, or ask for '
                                      'changes. Ctrl+Enter sends.')
        self.input.setMaximumHeight(90)
        self.input.installEventFilter(self)
        self.chat_list.installEventFilter(self)
        composer_layout.addWidget(self.input)
        options = QtWidgets.QHBoxLayout()
        options.setSpacing(4)
        self.include_check = _chip(
            'Selection', 'Send the selected nodes, their attributes and code '
            'with your message.')
        self.include_check.setChecked(bool(self.prefs.get(
            user_dir.USER_PREF.AI_INCLUDE_SELECTION, True)))
        self.include_check.toggled.connect(self.on_include_toggled)
        self.edit_check = _chip(
            'Edit graph', 'The assistant can make, change and delete nodes, '
            'hierarchies, code, attributes and layers. All the changes in '
            'a reply are one undo step, so Ctrl+Z takes them back.')
        self.edit_check.setChecked(bool(self.prefs.get(
            user_dir.USER_PREF.AI_ALLOW_EDITS, True)))
        self.edit_check.toggled.connect(self.on_edit_toggled)
        self.run_check = _chip(
            'Run code', 'The assistant can run nodes, builds and snippets of '
            'Python in the editor or host (such as Maya) to test its work '
            'and read what they print. Leave off unless you want that.')
        self.run_check.setProperty('risk', True)
        self.run_check.setChecked(bool(self.prefs.get(
            user_dir.USER_PREF.AI_ALLOW_RUNS, False)))
        self.run_check.toggled.connect(self.on_run_toggled)
        for chip in (self.include_check, self.edit_check, self.run_check):
            options.addWidget(chip)
        options.addStretch()
        self.send_button = _button('Send', 'aiSend')
        self.send_button.clicked.connect(self.send_or_stop)
        options.addWidget(self.send_button)
        composer_layout.addLayout(options)
        layout.addWidget(composer)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.render_timer = QtCore.QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(60)
        self.render_timer.timeout.connect(self.render)
        self.refresh_providers()
        self.refresh_chat_list()
        self.update_buttons()

    # Model connections
    def set_stage_model_connections(self, model, connect):
        self.model_signal_connections = [
            (model.selection_changed, self.on_selection_changed),
        ]
        super(AiAssistant, self).set_stage_model_connections(model, connect)

    def set_stage_model(self, stage_model):
        super(AiAssistant, self).set_stage_model(stage_model)
        self.on_selection_changed()

    def on_selection_changed(self, *_args):
        self.update_buttons()

    # Providers
    def provider(self):
        provider_id = self.provider_combo.currentData()
        return providers.get_provider(provider_id, store=self.store,
                                      prefs=self.prefs)

    def refresh_providers(self):
        """Show what is set up. Called again when the settings change."""
        current = (self.provider_combo.currentData() or
                   self.prefs.get(user_dir.USER_PREF.AI_PROVIDER))
        self.provider_combo.blockSignals(True)
        self.provider_combo.clear()
        ready = []
        for provider in providers.get_providers(store=self.store,
                                                prefs=self.prefs):
            set_up = provider.status() != 'Not set up.'
            self.provider_combo.addItem(provider.label, provider.id)
            if set_up:
                ready.append(provider.id)
            else:
                index = self.provider_combo.count() - 1
                self.provider_combo.setItemData(
                    index, '{} is not set up'.format(provider.label),
                    QtCore.Qt.ToolTipRole)
        if current not in ready and ready:
            current = ready[0]
        index = self.provider_combo.findData(current)
        self.provider_combo.setCurrentIndex(max(index, 0))
        self.provider_combo.blockSignals(False)
        if ready:
            self.setup_label.hide()
        else:
            self.setup_label.setText(
                'Sign in or add an API key to start. '
                '<a href="settings">Open the AI Assistant settings</a>.')
            self.setup_label.show()
        self.on_provider_changed()

    def on_provider_changed(self, *_args):
        provider = self.provider()
        if provider is None:
            return
        status = provider.status()
        self.account_label.setText(status)
        if status == 'Not set up.':
            self.set_models(provider.id, [], 'Not set up')
        else:
            models = provider.cached_models()
            if models is None:
                self.set_models(provider.id, [], 'Loading models...')
                self.load_models(provider)
            else:
                self.set_models(provider.id, models)
        self.update_buttons()

    def load_models(self, provider, refresh=False):
        thread = TaskThread(
            lambda cancelled: provider.models(refresh=refresh), parent=self)
        thread.done.connect(
            lambda models: self.set_models(provider.id, models))
        thread.failed.connect(
            lambda message: self.on_models_failed(provider, message))
        # Kept until it ends; a newer one may start for another provider.
        self.models_threads.append(thread)
        thread.finished.connect(lambda: self.models_threads.remove(thread))
        thread.start()

    def on_models_failed(self, provider, message):
        if provider.id != self.provider_combo.currentData():
            return
        self.set_models(provider.id, [], 'No models')
        self.show_error('Could not get the {} models: {}'.format(
            provider.label, message))

    def set_models(self, provider_id, models, empty_text='No models'):
        """Offer only the models the provider has, with one chosen."""
        if provider_id != self.provider_combo.currentData():
            return
        provider = self.provider()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(models)
        self.model_combo.setPlaceholderText(empty_text)
        chosen = provider.choose_model(models)
        if chosen:
            self.model_combo.setCurrentText(chosen)
        else:
            self.model_combo.setCurrentIndex(-1)
        self.model_combo.setEnabled(bool(models))
        self.model_combo.blockSignals(False)
        if chosen and chosen != provider.model:
            provider.model = chosen
        self.update_buttons()

    def on_model_changed(self, text):
        provider = self.provider()
        if provider is not None and text:
            provider.model = text
        self.update_buttons()

    def on_include_toggled(self, state):
        self.prefs[user_dir.USER_PREF.AI_INCLUDE_SELECTION] = bool(state)

    def on_edit_toggled(self, state):
        self.prefs[user_dir.USER_PREF.AI_ALLOW_EDITS] = bool(state)

    def on_run_toggled(self, state):
        self.prefs[user_dir.USER_PREF.AI_ALLOW_RUNS] = bool(state)

    @property
    def can_edit(self):
        return self.edit_check.isChecked() and self.stage_model is not None

    @property
    def can_run(self):
        return self.run_check.isChecked() and self.stage_model is not None

    # Chat
    @property
    def busy(self):
        return bool(self.thread and self.thread.isRunning())

    def eventFilter(self, widget, event):
        if (widget is self.chat_list and
                event.type() == QtCore.QEvent.KeyPress and
                event.key() == QtCore.Qt.Key_Delete):
            item = self.chat_list.currentItem()
            if item and item.data(QtCore.Qt.UserRole):
                self.delete_chat(item.data(QtCore.Qt.UserRole))
            return True
        if (widget is self.input and
                event.type() == QtCore.QEvent.KeyPress and
                event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and
                event.modifiers() & QtCore.Qt.ControlModifier):
            self.send_or_stop()
            return True
        return super(AiAssistant, self).eventFilter(widget, event)

    def send_or_stop(self):
        if self.busy:
            self.stop()
        else:
            self.send()

    def send(self, text=None):
        text = (text if text is not None else
                self.input.toPlainText()).strip()
        if not text or self.busy:
            return
        provider = self.provider()
        model = self.model_combo.currentText()
        if not model:
            self.show_error('{} has no model to use. Check its sign in in '
                            'the AI Assistant settings.'.format(
                                provider.label))
            return
        content = text
        if self.include_check.isChecked():
            selection = context.describe_selection(self.stage_model)
            if selection:
                content = '{}\n\nThe selected nodes:\n\n{}'.format(
                    text, selection)
        self.messages.append({'role': 'user', 'content': content,
                              'shown': text, 'time': time.time()})
        self.save_chat()
        self.input.clear()
        self.reply = ''
        self.reply_time = time.time()
        self.clear_error()
        self.status_label.setText('{} is answering...'.format(
            provider.label))
        sent = [{'role': m['role'], 'content': m['content']}
                for m in self.messages]
        # Without tools the model is told about the graph, and changes it
        # with a block of actions in its answer.
        fallback = context.system_prompt()
        if self.can_edit:
            fallback += '\n\n' + graph_actions.instructions()
            fallback += '\n\nThe graph as it is now:\n\n{}'.format(
                graph_actions.describe_graph(self.stage_model))
        remembered = self.memory.describe()
        if remembered:
            fallback += '\n\n' + remembered
        self.reply_tools = []
        self.toolbox = tools.Toolbox(self.stage_model,
                                     can_edit=self.can_edit,
                                     can_run=self.can_run, parent=self,
                                     memory=self.memory,
                                     chat_folders=self.chat_folders,
                                     ask_access=self.ask_access)
        self.toolbox.activity.connect(self.on_tool_activity)
        system = context.system_prompt() + '\n\n' + tools.instructions()
        if remembered:
            system += '\n\n' + remembered
        self.speaker = '{} \u00b7 {}'.format(provider.label, model)
        self.thread = ChatThread(provider, sent, system, model, parent=self,
                                 tools=self.toolbox,
                                 fallback_system=fallback)
        self.thread.chunk.connect(self.on_chunk)
        self.thread.failed.connect(self.on_failed)
        self.thread.tools_dropped.connect(self.on_tools_dropped)
        self.thread.finished.connect(self.on_finished)
        self.thread.start()
        self.render()
        self.update_buttons()

    def stop(self):
        if self.thread:
            self.thread.cancel()
        self.answer_access(tools.DENY)

    def on_chunk(self, text):
        self.reply += text
        if not self.render_timer.isActive():
            self.render_timer.start()

    def on_failed(self, message):
        self.show_error(message)

    def on_tool_activity(self, event):
        for i, known in enumerate(self.reply_tools):
            if known['id'] == event['id']:
                self.reply_tools[i] = dict(event)
                break
        else:
            self.reply_tools.append(dict(event))
        if not self.render_timer.isActive():
            self.render_timer.start()

    def on_tools_dropped(self):
        self.reply_tools.append({
            'id': -1, 'name': '', 'kind': tools.READ, 'state': 'note',
            'label': 'This model can not use tools, so it answered without '
                     'them', 'detail': ''})

    # Reading somewhere new
    def ask_access(self, folder, reason):
        """Ask the user to let the assistant read folder. Waits for the
        answer, which is ONCE, ALWAYS or DENY."""
        toolbox = self.toolbox
        if toolbox is None or toolbox.cancelled.is_set():
            return tools.DENY
        provider = self.provider()
        who = provider.label if provider else 'The assistant'
        self.ask_title.setText('{} wants to read files in'.format(who))
        self.ask_path.setText(folder)
        self.ask_reason.setText(reason or '')
        self.ask_reason.setVisible(bool(reason))
        self.ask_frame.show()
        # The answer is needed here, so bring the panel forward.
        self.show()
        self.raise_()
        self.allow_button.setFocus()
        self.access_answer = tools.DENY
        loop = QtCore.QEventLoop()
        self.access_loop = loop
        # A stopped reply gets no answer.
        watch = QtCore.QTimer()
        watch.timeout.connect(lambda: toolbox.cancelled.is_set() and
                              loop.quit())
        watch.start(100)
        try:
            loop.exec_()
        finally:
            watch.stop()
            self.access_loop = None
            self.ask_frame.hide()
        if toolbox.cancelled.is_set():
            return tools.DENY
        return self.access_answer

    def answer_access(self, answer):
        self.access_answer = answer
        if self.access_loop is not None:
            self.access_loop.quit()

    def end_tools(self):
        """The changes the reply made become one undo step."""
        toolbox, self.toolbox = self.toolbox, None
        if toolbox is not None:
            toolbox.finish()
        return toolbox

    @staticmethod
    def tools_record(events):
        return [{'label': e['label'], 'kind': e['kind'],
                 'state': e['state'], 'detail': e.get('detail', '')}
                for e in events]

    def on_finished(self):
        toolbox = self.end_tools()
        if self.reply or (toolbox and toolbox.done):
            message = {'role': 'assistant', 'content': self.reply,
                       'who': self.speaker,
                       'time': self.reply_time or time.time()}
            if self.reply_tools:
                message['tools'] = self.tools_record(self.reply_tools)
            if toolbox is not None and (toolbox.done or toolbox.failed):
                message['done'] = list(toolbox.done)
                message['failed'] = list(toolbox.failed)
            self.messages.append(message)
            self.apply_changes(message)
        elif self.messages and self.messages[-1]['role'] == 'user':
            # Nothing came back, so let the question be asked again.
            failed = self.messages.pop()
            if not self.input.toPlainText():
                self.input.setPlainText(failed['shown'])
        self.save_chat()
        self.reply = ''
        self.reply_tools = []
        if not self.status_label.property('error'):
            self.status_label.setText('')
        self.render()
        self.update_buttons()

    def show_error(self, message):
        self.status_label.setProperty('error', True)
        self.status_label.setStyleSheet('color: #e07070')
        self.status_label.setText(message)

    def clear_error(self):
        self.status_label.setProperty('error', False)
        self.status_label.setStyleSheet('')

    def render(self):
        parts = []
        days = []

        def day_line(when):
            # The day, wherever it changes, as chat apps show it.
            if not when:
                return
            day = chat_render.day_name(when)
            if not days or days[-1] != day:
                days.append(day)
                parts.append(chat_render.day_html(when))

        for message in self.messages:
            when = message.get('time')
            day_line(when)
            if message['role'] == 'user':
                parts.append(chat_render.user_html(
                    message.get('shown', message['content']), when))
            else:
                parts.append(chat_render.reply_html(
                    message.get('who', 'Assistant'),
                    graph_actions.without_actions(message['content']),
                    chat_render.changes_html(message), when,
                    activity=message.get('tools')))
        if self.busy and (self.reply or self.reply_tools):
            # The changes are not shown as they arrive, only what they did.
            shown = self.reply.split('```' + graph_actions.FENCE)[0]
            if shown != self.reply:
                shown += '\n\n*Getting the changes ready...*'
            day_line(self.reply_time)
            parts.append(chat_render.reply_html(
                self.speaker, shown, when=self.reply_time,
                activity=self.tools_record(self.reply_tools)))
        elif self.busy:
            parts.append(chat_render.thinking_html(self.speaker))
        bar = self.transcript.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        self.transcript.setHtml(''.join(parts))
        if at_end:
            bar.setValue(bar.maximum())

    def apply_changes(self, message):
        """Make the changes a reply asks for, if it may."""
        actions, problems = graph_actions.find_actions(message['content'])
        if not actions and not problems:
            return
        if not self.edit_check.isChecked():
            message['note'] = ('It suggested changes to the graph. Turn '
                               'on "Edit graph" to allow them.')
            return
        if self.stage_model is None:
            message['note'] = 'Open a graph for it to change.'
            return
        done, failed = graph_actions.Applier(self.stage_model).apply(actions)
        failed = problems + failed
        message['done'] = message.get('done', []) + done
        message['failed'] = message.get('failed', []) + failed
        if failed:
            self.show_error('{} of the changes could not be made.'.format(
                len(failed)))

    # Chats
    def save_chat(self):
        """Keep the chat as it is now. A chat is only kept once it has a
        message, and one left with none is removed."""
        if not self.messages:
            if self.chat_id:
                self.chat_store.delete(self.chat_id)
                self.chat_id = None
                self.refresh_chat_list()
            return
        if not self.chat_id:
            self.chat_id = self.chat_store.new_id()
            self.chat_created = time.time()
        self.chat_store.save({'id': self.chat_id, 'messages': self.messages,
                              'created': self.chat_created})
        self.refresh_chat_list()

    def refresh_chat_list(self):
        """Pinned chats first, then the rest, most recent first."""
        listed = self.chat_list
        listed.blockSignals(True)
        listed.clear()
        saved = self.chat_store.list()
        pinned = [c for c in saved if c['pinned']]
        recent = [c for c in saved if not c['pinned']]
        for heading, group in (('Pinned', pinned), ('Recent', recent)):
            if not group:
                continue
            if pinned:
                header = QtWidgets.QListWidgetItem(heading)
                header.setFlags(QtCore.Qt.NoItemFlags)
                font = header.font()
                font.setBold(True)
                header.setFont(font)
                listed.addItem(header)
            for chat in group:
                item = QtWidgets.QListWidgetItem('{}  \u00b7  {}'.format(
                    chat['title'], chat_render.short_when(chat['updated'])))
                item.setData(QtCore.Qt.UserRole, chat['id'])
                item.setData(QtCore.Qt.UserRole + 1, chat['pinned'])
                item.setToolTip('{}\n{} at {}'.format(
                    chat['title'], chat_render.day_name(chat['updated']),
                    chat_render.clock(chat['updated'])))
                listed.addItem(item)
                if chat['id'] == self.chat_id:
                    listed.setCurrentItem(item)
        if not self.chat_id:
            listed.setCurrentItem(None)
            listed.clearSelection()
        listed.blockSignals(False)

    def chat_item(self, chat_id):
        for row in range(self.chat_list.count()):
            item = self.chat_list.item(row)
            if item.data(QtCore.Qt.UserRole) == chat_id:
                return item
        return None

    def chat_menu(self, pos):
        item = self.chat_list.itemAt(pos)
        chat_id = item.data(QtCore.Qt.UserRole) if item else None
        if not chat_id:
            return
        pinned = bool(item.data(QtCore.Qt.UserRole + 1))
        menu = QtWidgets.QMenu(self)
        pin = menu.addAction('Unpin' if pinned else 'Pin')
        pin.triggered.connect(
            lambda *_: self.pin_chat(chat_id, not pinned))
        delete = menu.addAction('Delete')
        delete.triggered.connect(lambda *_: self.delete_chat(chat_id))
        menu.exec_(self.chat_list.viewport().mapToGlobal(pos))

    def pin_chat(self, chat_id, pinned=True):
        self.chat_store.set_pinned(chat_id, pinned)
        self.refresh_chat_list()

    def leave_chat(self):
        """Stop a reply still coming, and keep what came of it in the chat
        it belongs to."""
        thread = self.thread
        self.thread = None
        if not (thread and thread.isRunning()):
            return
        thread.cancel()
        for signal in (thread.chunk, thread.failed, thread.finished):
            try:
                signal.disconnect()
            except (RuntimeError, TypeError):
                pass
        toolbox = self.end_tools()
        if self.reply or self.reply_tools:
            message = {
                'role': 'assistant', 'content': self.reply,
                'who': self.speaker, 'time': self.reply_time or time.time(),
                'note': 'Stopped when you left the chat.'}
            if self.reply_tools:
                message['tools'] = self.tools_record(self.reply_tools)
            if toolbox is not None and (toolbox.done or toolbox.failed):
                message['done'] = list(toolbox.done)
                message['failed'] = list(toolbox.failed)
            self.messages.append(message)
        elif self.messages and self.messages[-1]['role'] == 'user':
            self.messages.pop()
        self.reply = ''
        self.reply_tools = []
        self.save_chat()
        self.left_threads.append(thread)
        thread.finished.connect(
            functools.partial(self.left_threads.remove, thread))

    def show_chat(self, chat_id, messages, created=None):
        if chat_id != self.chat_id:
            self.chat_folders = set()
        self.chat_id = chat_id
        self.chat_created = created
        self.messages = messages
        self.reply = ''
        self.clear_error()
        self.status_label.setText('')
        self.refresh_chat_list()
        self.render()
        bar = self.transcript.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.update_buttons()

    def new_chat(self):
        """Start a new chat. The one before is kept in the list."""
        self.leave_chat()
        self.show_chat(None, [])

    def on_chat_clicked(self, item):
        chat_id = item.data(QtCore.Qt.UserRole)
        if chat_id and chat_id != self.chat_id:
            self.open_chat(chat_id)

    def open_chat(self, chat_id):
        self.leave_chat()
        record = self.chat_store.load(chat_id)
        if record is None:
            self.refresh_chat_list()
            self.show_error('That chat could not be opened.')
            return
        self.show_chat(chat_id, record['messages'], record.get('created'))

    def delete_chat(self, chat_id, confirm=True):
        if confirm:
            record = self.chat_store.load(chat_id) or {}
            answer = QtWidgets.QMessageBox.question(
                self, 'Delete Chat',
                'Delete "{}"? It cannot be brought back.'.format(
                    record.get('title') or 'this chat'))
            if answer != QtWidgets.QMessageBox.Yes:
                return
        if chat_id == self.chat_id:
            self.leave_chat()
            self.chat_store.delete(chat_id)
            self.show_chat(None, [])
        else:
            self.chat_store.delete(chat_id)
            self.refresh_chat_list()

    # Code
    def last_reply(self):
        for message in reversed(self.messages):
            if message['role'] == 'assistant':
                return message['content']
        return ''

    def target_node(self):
        model = self.stage_model
        if not model:
            return None
        selection = list(model.selection or [])
        if len(selection) == 1:
            return selection[0]
        return None

    def apply_code(self):
        code = context.last_code_block(self.last_reply())
        path = self.target_node()
        if code is None or not path:
            return
        self.stage_model.set_node_code_lines(path, code.split('\n'))
        self.clear_error()
        self.status_label.setText('Applied to {}. Undo puts the old code '
                                  'back.'.format(path))

    def copy_code(self):
        code = context.last_code_block(self.last_reply())
        if code is not None:
            QtWidgets.QApplication.clipboard().setText(code)
            self.clear_error()
            self.status_label.setText('Copied.')

    def update_buttons(self):
        busy = self.busy
        has_code = context.last_code_block(self.last_reply()) is not None
        self.send_button.setText('Stop' if busy else 'Send')
        if bool(self.send_button.property('stop')) != busy:
            self.send_button.setProperty('stop', busy)
            self.send_button.style().unpolish(self.send_button)
            self.send_button.style().polish(self.send_button)
        self.send_button.setEnabled(busy or bool(
            self.model_combo.currentText()))
        self.copy_button.setEnabled(has_code and not busy)
        self.copy_button.setVisible(has_code)
        self.apply_button.setVisible(has_code)
        self.apply_button.setEnabled(has_code and not busy and
                                     bool(self.target_node()))
        if not busy and self.status_label.text().endswith('answering...'):
            self.status_label.setText('')

    def showEvent(self, event):
        super(AiAssistant, self).showEvent(event)
        # Pick up a sign in made since, here or in Claude Code.
        claude_code.forget_status(older_than=5)
        if not self.busy:
            self.refresh_providers()

    def closeEvent(self, event):
        self.stop()
        self.end_tools()
        super(AiAssistant, self).closeEvent(event)
