"""The AI Assistant panel: chat with Claude, OpenAI or Grok about the graph.

Only in the Window menu once the assistant is turned on in
Options > AI Assistant.
"""
# Builtin
import logging

# External
from Qt import QtCore, QtWidgets

# Internal
import nxt_editor
from nxt_editor import user_dir
from nxt_editor.ai import (chat_render, claude_code, context,
                           graph_actions, providers)
from nxt_editor.ai.workers import ChatThread, TaskThread
from nxt_editor.dockwidgets.dock_widget_base import DockWidgetBase

logger = logging.getLogger(nxt_editor.LOGGER_NAME)


class AiAssistant(DockWidgetBase):

    open_settings = QtCore.Signal()

    def __init__(self, title='AI Assistant', parent=None, minimum_width=300,
                 store=None, prefs=None):
        super(AiAssistant, self).__init__(title=title, parent=parent,
                                          minimum_width=minimum_width)
        self.store = store
        self.prefs = prefs if prefs is not None else user_dir.user_prefs
        self.messages = []
        self.reply = ''
        self.thread = None
        self.speaker = ''
        self.models_threads = []

        self.main_widget = QtWidgets.QWidget(parent=self)
        self.setWidget(self.main_widget)
        layout = QtWidgets.QVBoxLayout(self.main_widget)
        layout.setContentsMargins(4, 4, 4, 4)

        top = QtWidgets.QHBoxLayout()
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
        self.settings_button = QtWidgets.QPushButton('Settings')
        self.settings_button.setToolTip('Sign in, API keys and models')
        self.settings_button.clicked.connect(self.open_settings.emit)
        top.addWidget(self.settings_button)
        layout.addLayout(top)

        self.account_label = QtWidgets.QLabel()
        self.account_label.setWordWrap(True)
        self.account_label.setStyleSheet('color: grey')
        layout.addWidget(self.account_label)

        self.setup_label = QtWidgets.QLabel()
        self.setup_label.setWordWrap(True)
        self.setup_label.linkActivated.connect(
            lambda _link: self.open_settings.emit())
        layout.addWidget(self.setup_label)

        self.transcript = QtWidgets.QTextBrowser()
        self.transcript.setOpenExternalLinks(True)
        layout.addWidget(self.transcript, 1)

        tools = QtWidgets.QHBoxLayout()
        self.include_check = QtWidgets.QCheckBox('Include selected nodes')
        self.include_check.setToolTip(
            'Send the selected nodes, their attributes and code with your '
            'message.')
        self.include_check.setChecked(bool(self.prefs.get(
            user_dir.USER_PREF.AI_INCLUDE_SELECTION, True)))
        self.include_check.toggled.connect(self.on_include_toggled)
        self.edit_check = QtWidgets.QCheckBox('Let it change the graph')
        self.edit_check.setToolTip(
            'The assistant can make, change and delete nodes, hierarchies, '
            'code, attributes and layers. Its changes are made straight '
            'away, as one undo step, so Ctrl+Z takes them back.')
        self.edit_check.setChecked(bool(self.prefs.get(
            user_dir.USER_PREF.AI_ALLOW_EDITS, True)))
        self.edit_check.toggled.connect(self.on_edit_toggled)
        options = QtWidgets.QHBoxLayout()
        options.addWidget(self.include_check)
        options.addWidget(self.edit_check)
        options.addStretch()
        layout.addLayout(options)
        tools.addStretch()
        self.apply_button = QtWidgets.QPushButton('Apply Code')
        self.apply_button.setToolTip(
            'Replace the selected node\'s code with the last code block in '
            'the reply. Undo puts it back.')
        self.apply_button.clicked.connect(self.apply_code)
        tools.addWidget(self.apply_button)
        self.copy_button = QtWidgets.QPushButton('Copy Code')
        self.copy_button.setToolTip('Copy the last code block in the reply.')
        self.copy_button.clicked.connect(self.copy_code)
        tools.addWidget(self.copy_button)
        self.new_button = QtWidgets.QPushButton('New Chat')
        self.new_button.clicked.connect(self.new_chat)
        tools.addWidget(self.new_button)
        layout.addLayout(tools)

        self.input = QtWidgets.QPlainTextEdit()
        self.input.setPlaceholderText('Ask about the graph, or ask for '
                                      'changes. Ctrl+Enter sends.')
        self.input.setMaximumHeight(90)
        self.input.installEventFilter(self)
        send_row = QtWidgets.QHBoxLayout()
        send_row.addWidget(self.input, 1)
        self.send_button = QtWidgets.QPushButton('Send')
        self.send_button.clicked.connect(self.send_or_stop)
        send_row.addWidget(self.send_button)
        layout.addLayout(send_row)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.render_timer = QtCore.QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(60)
        self.render_timer.timeout.connect(self.render)
        self.refresh_providers()
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

    @property
    def can_edit(self):
        return self.edit_check.isChecked() and self.stage_model is not None

    # Chat
    @property
    def busy(self):
        return bool(self.thread and self.thread.isRunning())

    def eventFilter(self, widget, event):
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
        if self.can_edit:
            content = '{}\n\nThe graph as it is now:\n\n{}'.format(
                content, graph_actions.describe_graph(self.stage_model))
        self.messages.append({'role': 'user', 'content': content,
                              'shown': text})
        self.input.clear()
        self.reply = ''
        self.clear_error()
        self.status_label.setText('{} is answering...'.format(
            provider.label))
        sent = [{'role': m['role'], 'content': m['content']}
                for m in self.messages]
        system = context.system_prompt()
        if self.can_edit:
            system += '\n\n' + graph_actions.instructions()
        self.speaker = '{} \u00b7 {}'.format(provider.label, model)
        self.thread = ChatThread(provider, sent, system, model, parent=self)
        self.thread.chunk.connect(self.on_chunk)
        self.thread.failed.connect(self.on_failed)
        self.thread.finished.connect(self.on_finished)
        self.thread.start()
        self.render()
        self.update_buttons()

    def stop(self):
        if self.thread:
            self.thread.cancel()

    def on_chunk(self, text):
        self.reply += text
        if not self.render_timer.isActive():
            self.render_timer.start()

    def on_failed(self, message):
        self.show_error(message)

    def on_finished(self):
        if self.reply:
            message = {'role': 'assistant', 'content': self.reply,
                       'who': self.speaker}
            self.messages.append(message)
            self.apply_changes(message)
        elif self.messages and self.messages[-1]['role'] == 'user':
            # Nothing came back, so let the question be asked again.
            failed = self.messages.pop()
            if not self.input.toPlainText():
                self.input.setPlainText(failed['shown'])
        self.reply = ''
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
        for message in self.messages:
            if message['role'] == 'user':
                parts.append(chat_render.user_html(
                    message.get('shown', message['content'])))
            else:
                parts.append(chat_render.reply_html(
                    message.get('who', 'Assistant'),
                    graph_actions.without_actions(message['content']),
                    chat_render.changes_html(message)))
        if self.reply:
            # The changes are not shown as they arrive, only what they did.
            shown = self.reply.split('```' + graph_actions.FENCE)[0]
            if shown != self.reply:
                shown += '\n\n*Getting the changes ready...*'
            parts.append(chat_render.reply_html(self.speaker, shown))
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
            message['note'] = ('It suggested changes to the graph. Tick '
                               '"Let it change the graph" to allow them.')
            return
        if self.stage_model is None:
            message['note'] = 'Open a graph for it to change.'
            return
        done, failed = graph_actions.Applier(self.stage_model).apply(actions)
        failed = problems + failed
        message['done'] = done
        message['failed'] = failed
        if failed:
            self.show_error('{} of the changes could not be made.'.format(
                len(failed)))

    def new_chat(self):
        self.stop()
        self.messages = []
        self.reply = ''
        self.clear_error()
        self.status_label.setText('')
        self.render()
        self.update_buttons()

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
        self.send_button.setEnabled(busy or bool(
            self.model_combo.currentText()))
        self.copy_button.setEnabled(has_code and not busy)
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
        super(AiAssistant, self).closeEvent(event)
