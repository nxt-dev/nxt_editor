"""Options > AI Assistant: turn the assistant on and sign in to providers."""
# Builtin
import logging
import os
import sys
import webbrowser

# External
from Qt import QtCore, QtGui, QtWidgets

# Internal
import nxt_editor
from nxt_editor import theme, user_dir
from nxt_editor.constants import FONTS
from nxt_editor.ai import claude_code, codex, providers, secret_store
from nxt_editor.ai.memory_page import MemoryPage
from nxt_editor.ai.workers import TaskThread

logger = logging.getLogger(nxt_editor.LOGGER_NAME)


def open_url(url):
    webbrowser.open(url)


class WaitDialog(QtWidgets.QDialog):
    """Shown while a sign in waits on the browser."""
    def __init__(self, title, text, parent=None):
        super(WaitDialog, self).__init__(parent)
        self.setWindowTitle(title)
        layout = QtWidgets.QVBoxLayout(self)
        self.label = QtWidgets.QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self.label)
        self.code_label = QtWidgets.QLabel()
        font = FONTS.default_font(FONTS.DEFAULT_SIZE * 2)
        font.setBold(True)
        self.code_label.setFont(font)
        self.code_label.setAlignment(QtCore.Qt.AlignCenter)
        self.code_label.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse)
        self.code_label.hide()
        layout.addWidget(self.code_label)
        # For a sign in page that gives a code to paste back.
        self.paste_widget = QtWidgets.QWidget()
        paste_row = QtWidgets.QHBoxLayout(self.paste_widget)
        paste_row.setContentsMargins(0, 0, 0, 0)
        self.paste_edit = QtWidgets.QLineEdit()
        self.paste_edit.setPlaceholderText('If the page shows a code, paste '
                                           'it here')
        paste_row.addWidget(self.paste_edit, 1)
        self.paste_button = QtWidgets.QPushButton('Send Code')
        paste_row.addWidget(self.paste_button)
        self.paste_widget.hide()
        layout.addWidget(self.paste_widget)
        buttons = QtWidgets.QHBoxLayout()
        layout.addLayout(buttons)
        self.browser_button = QtWidgets.QPushButton('Open the Browser Again')
        self.browser_button.hide()
        buttons.addWidget(self.browser_button)
        self.copy_button = QtWidgets.QPushButton('Copy Code')
        self.copy_button.hide()
        buttons.addWidget(self.copy_button)
        self.other_account_button = QtWidgets.QPushButton(
            'Use Another Account or Workspace')
        self.other_account_button.hide()
        buttons.addWidget(self.other_account_button)
        buttons.addStretch()
        cancel = QtWidgets.QPushButton('Cancel')
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.url = None
        self.browser_button.clicked.connect(lambda: open_url(self.url))
        self.copy_button.clicked.connect(self.copy_code)

    def show_code(self, code, url):
        self.url = url
        self.code_label.setText(code)
        self.code_label.show()
        self.copy_button.show()
        self.browser_button.show()

    def copy_code(self):
        QtWidgets.QApplication.clipboard().setText(self.code_label.text())

    def show_page_link(self, url):
        self.url = url
        self.browser_button.setText('Open the Sign In Page Again')
        self.browser_button.setVisible(bool(url))


#: One width for the buttons beside the fields, so they line up in every
#: provider's section.
BUTTON_WIDTH = 88


def link_html(url, text):
    """A link a QLabel shows in the link color: labels ignore style
    sheets for links."""
    return '<a href="{}" style="color: {}; text-decoration: none">{}</a>'\
        .format(url, theme.LINK, text)


class SectionHeader(QtWidgets.QAbstractButton):
    """The row a provider's section opens and closes from: a chevron, its
    name, Default when it is asked first, and how it is set up. Drawn here
    rather than by the style, so it looks the same in every host."""
    HEIGHT = 32

    def __init__(self, name, parent=None):
        super(SectionHeader, self).__init__(parent)
        self.name = name
        self.summary = ''
        self.problem = False
        self.is_default = False
        self.setCheckable(True)
        # Reached with Tab, not taken by a click: the editor's style sheet
        # draws a square border round whatever has focus, over the rounded
        # header. Its own ring shows keyboard focus instead.
        self.setFocusPolicy(QtCore.Qt.TabFocus)
        self.setAttribute(QtCore.Qt.WA_StyledBackground, False)
        self.setStyleSheet('border: none; background: transparent;')
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFixedHeight(self.HEIGHT)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Fixed)
        self.toggled.connect(self.update_name)
        self.update_name()

    def set_summary(self, text, problem=False, tip=''):
        self.summary = text
        self.problem = problem
        self.setToolTip(tip)
        self.update_name()

    def set_default(self, is_default):
        self.is_default = is_default
        self.update_name()

    def update_name(self, *_args):
        self.setAccessibleName('{}, {}, {}'.format(
            self.name, self.summary or 'Not set up',
            'expanded' if self.isChecked() else 'collapsed'))
        self.update()

    def sizeHint(self):
        return QtCore.QSize(200, self.HEIGHT)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.click()
        elif key == QtCore.Qt.Key_Left and self.isChecked():
            self.click()
        elif key == QtCore.Qt.Key_Right and not self.isChecked():
            self.click()
        else:
            super(SectionHeader, self).keyPressEvent(event)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = theme.HOVER if self.underMouse() else theme.RAISED
        painter.setPen(QtGui.QPen(theme.color(theme.ACCENT), 1)
                       if self.hasFocus() else QtCore.Qt.NoPen)
        painter.setBrush(theme.color(fill))
        painter.drawRoundedRect(rect, theme.RADIUS, theme.RADIUS)
        x = 10
        # Chevron
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(theme.color(theme.TEXT_DIM))
        mid = self.height() / 2.0
        if self.isChecked():
            points = [QtCore.QPointF(x, mid - 2),
                      QtCore.QPointF(x + 8, mid - 2),
                      QtCore.QPointF(x + 4, mid + 3)]
        else:
            points = [QtCore.QPointF(x + 2, mid - 4),
                      QtCore.QPointF(x + 7, mid),
                      QtCore.QPointF(x + 2, mid + 4)]
        painter.drawPolygon(QtGui.QPolygonF(points))
        x += 18
        # Name
        name_font = theme.font(theme.TEXT_PX,
                               weight=QtGui.QFont.Medium)
        painter.setFont(name_font)
        painter.setPen(theme.color(theme.TEXT))
        name_width = QtGui.QFontMetrics(name_font).horizontalAdvance(
            self.name)
        painter.drawText(QtCore.QRectF(x, 0, name_width + 2, self.height()),
                         QtCore.Qt.AlignVCenter, self.name)
        x += name_width + 10
        small = theme.font(theme.SMALL_PX)
        metrics = QtGui.QFontMetrics(small)
        painter.setFont(small)
        # Default
        if self.is_default:
            text = 'Default'
            pill = QtCore.QRectF(x, mid - 9,
                                 metrics.horizontalAdvance(text) + 12, 18)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(theme.color(theme.ACCENT_DIM))
            painter.drawRoundedRect(pill, 9, 9)
            painter.setPen(theme.color(theme.TEXT))
            painter.drawText(pill, QtCore.Qt.AlignCenter, text)
            x = pill.right() + 10
        # How it is set up
        room = self.width() - 12 - x
        if self.summary and room > 20:
            painter.setPen(theme.color(theme.ERROR if self.problem
                                       else theme.TEXT_DIM))
            text = metrics.elidedText(self.summary, QtCore.Qt.ElideRight,
                                      int(room))
            painter.drawText(QtCore.QRectF(x, 0, room, self.height()),
                             QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight,
                             text)
        painter.end()

    def enterEvent(self, event):
        super(SectionHeader, self).enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super(SectionHeader, self).leaveEvent(event)
        self.update()


class ProviderBox(QtWidgets.QWidget):
    """Sign in, API key and model for one provider, under a header that
    opens and closes it."""
    changed = QtCore.Signal()
    # Something was saved in the secure store.
    stored = QtCore.Signal()

    def __init__(self, provider, parent=None):
        super(ProviderBox, self).__init__(parent)
        self.provider = provider
        self.thread = None
        self.wait_dialog = None
        self.problem = ''
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)
        self.header = SectionHeader(provider.label)
        self.header.toggled.connect(self.set_expanded)
        outer.addWidget(self.header)
        self.body = QtWidgets.QWidget()
        outer.addWidget(self.body)
        layout = QtWidgets.QGridLayout(self.body)
        # Set in under the chevron, so it reads as this section's.
        layout.setContentsMargins(12, 2, 6, 8)
        self.status_label = QtWidgets.QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label, 0, 0, 1, 5)

        # Web
        self.web_button = QtWidgets.QPushButton()
        self.web_button.clicked.connect(lambda _=False: self.sign_in())
        layout.addWidget(self.web_button, 1, 0, 1, 2)
        self.sign_out_button = QtWidgets.QPushButton('Sign Out')
        self.sign_out_button.clicked.connect(self.sign_out)
        layout.addWidget(self.sign_out_button, 1, 2)
        self.web_button.setVisible(provider.web_sign_in)
        self.sign_out_button.setVisible(provider.web_sign_in)
        self.locate_button = QtWidgets.QPushButton('Locate...')
        self.locate_button.setToolTip('Show nxt where {} is installed.'.format(
            provider.app_name))
        self.locate_button.clicked.connect(self.locate_app)
        self.locate_button.hide()
        layout.addWidget(self.locate_button, 1, 3)

        # Local server
        self.url_edit = None
        if self.is_local:
            layout.addWidget(QtWidgets.QLabel('Server'), 1, 0)
            self.url_edit = QtWidgets.QLineEdit(provider.base_url)
            self.url_edit.setPlaceholderText('http://localhost:11434/v1')
            self.url_edit.setToolTip(
                'The address of Ollama, LM Studio, llama.cpp, vLLM, Jan or '
                'any server with an OpenAI style API.')
            self.url_edit.editingFinished.connect(self.on_url_edited)
            layout.addWidget(self.url_edit, 1, 1)
            self.find_button = QtWidgets.QPushButton('Find')
            self.find_button.setToolTip(
                'Look for Ollama, LM Studio, llama.cpp, vLLM or Jan running '
                'on this computer.')
            self.find_button.clicked.connect(self.find_servers)
            layout.addWidget(self.find_button, 1, 2)

        # API key
        key_label = QtWidgets.QLabel('API key')
        layout.addWidget(key_label, 2, 0)
        self.key_edit = QtWidgets.QLineEdit()
        self.key_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.key_edit.returnPressed.connect(self.save_key)
        layout.addWidget(self.key_edit, 2, 1)
        self.save_key_button = QtWidgets.QPushButton('Save Key')
        self.save_key_button.clicked.connect(self.save_key)
        layout.addWidget(self.save_key_button, 2, 2)
        self.remove_key_button = QtWidgets.QPushButton('Remove Key')
        self.remove_key_button.clicked.connect(self.remove_key)
        layout.addWidget(self.remove_key_button, 2, 3)
        if provider.keys_url:
            self.keys_link = QtWidgets.QLabel(
                link_html(provider.keys_url, 'Get a key'))
            self.keys_link.setFont(theme.font(theme.SMALL_PX))
            self.keys_link.setOpenExternalLinks(True)
            self.keys_link.setVisible(provider.takes_api_key)
            layout.addWidget(self.keys_link, 2, 4)
        for widget in (key_label, self.key_edit, self.save_key_button,
                       self.remove_key_button):
            widget.setVisible(provider.takes_api_key)

        # Which one
        self.use_web = QtWidgets.QRadioButton('Use the sign in')
        self.use_key = QtWidgets.QRadioButton('Use the API key')
        use_group = QtWidgets.QButtonGroup(self)
        use_group.addButton(self.use_web)
        use_group.addButton(self.use_key)
        self.use_web.toggled.connect(self.on_use_toggled)
        use_row = QtWidgets.QHBoxLayout()
        use_row.addWidget(self.use_web)
        use_row.addWidget(self.use_key)
        use_row.addStretch()
        self.use_widget = QtWidgets.QWidget()
        self.use_widget.setLayout(use_row)
        use_row.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.use_widget, 4, 1, 1, 3)

        # Model
        layout.addWidget(QtWidgets.QLabel('Model'), 5, 0)
        self.model_combo = QtWidgets.QComboBox()
        # Short enough for the section to fit beside the scroll bar; it
        # stretches to fill the row when there is room.
        self.model_combo.setMinimumContentsLength(10)
        self.model_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.models_thread = None
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        layout.addWidget(self.model_combo, 5, 1)
        self.check_button = QtWidgets.QPushButton('Check')
        self.check_button.setToolTip('Check the sign in or key works, and '
                                     'load the models it can use.')
        self.check_button.clicked.connect(self.check)
        layout.addWidget(self.check_button, 5, 2)
        layout.setColumnStretch(1, 1)
        for button in (self.sign_out_button, self.locate_button,
                       self.save_key_button, self.remove_key_button,
                       self.check_button,
                       getattr(self, 'find_button', None)):
            if button is not None:
                button.setFixedWidth(BUTTON_WIDTH)
        # The same columns in every section, used or not, so they line up.
        for column in (2, 3):
            layout.setColumnMinimumWidth(column, BUTTON_WIDTH)
        probe = QtWidgets.QLabel(link_html('', 'Get a key'))
        probe.setFont(theme.font(theme.SMALL_PX))
        link_width = probe.sizeHint().width() + 2
        if provider.keys_url:
            self.keys_link.setFixedWidth(link_width)
        layout.setColumnMinimumWidth(4, link_width)
        label_width = max(self.fontMetrics().horizontalAdvance(text)
                          for text in ('API key', 'Server', 'Model')) + 8
        layout.setColumnMinimumWidth(0, label_width)
        # A grid leaves out the spacing of a column with nothing in it, and
        # which are empty differs by provider, so these keep them filled.
        for column, width in ((3, BUTTON_WIDTH), (4, link_width)):
            spacer = QtWidgets.QWidget()
            spacer.setFixedSize(width, 0)
            layout.addWidget(spacer, 5, column)
        self.body.setVisible(False)
        self.refresh()

    def set_expanded(self, expanded):
        if self.header.isChecked() != expanded:
            self.header.setChecked(expanded)
            return
        # Opens downward where it is. Nothing scrolls, so the header stays
        # under the mouse.
        self.body.setVisible(expanded)

    def is_expanded(self):
        return self.header.isChecked()

    def set_status(self, text, error=False):
        style = 'color: {}'.format(theme.ERROR) if error else ''
        self.status_label.setStyleSheet(style)
        self.status_label.setText(text)
        self.problem = text if error else ''
        self.update_header()

    def summary(self):
        """A few words on how the provider is set up, for its header."""
        provider = self.provider
        status = provider.status()
        if status == 'Not set up.':
            return 'Not set up'
        if self.is_local:
            text = 'Local server'
        elif provider.method == providers.KEY or not provider.web_record():
            if provider.saved_api_key():
                text = 'API key'
            elif provider.env_api_key():
                text = 'Environment key'
            else:
                text = 'Signed in'
        else:
            text = 'Signed in'
        model = provider.model
        if model:
            text += ' \u00b7 ' + model
        return text

    def update_header(self, busy=''):
        if busy:
            self.header.set_summary(busy)
        elif self.problem:
            self.header.set_summary('Problem', problem=True,
                                    tip=self.problem)
        else:
            try:
                summary = self.summary()
            except Exception:
                logger.debug('No summary for %s', self.provider.label,
                             exc_info=True)
                summary = ''
            self.header.set_summary(summary,
                                    tip=self.status_label.text())

    def set_controls_enabled(self, enabled):
        """Everything but the header, which still opens and closes so the
        settings can be read with the assistant off."""
        self.body.setEnabled(enabled)

    @property
    def uses_app(self):
        """True when signing in runs the provider's own app (Claude Code or
        Codex)."""
        return self.provider.app is not None

    @property
    def is_local(self):
        return isinstance(self.provider, providers.Local)

    def on_url_edited(self):
        url = self.url_edit.text()
        if url.strip().rstrip('/') == self.provider.base_url:
            return
        self.provider.base_url = url
        self.url_edit.setText(self.provider.base_url)
        self.refresh()
        self.changed.emit()
        if self.provider.base_url:
            self.check()

    def find_servers(self):
        self.find_button.setEnabled(False)
        self.set_status('Looking for local servers...')
        self._run(lambda cancelled: providers.Local.find_servers(),
                  self.on_servers)

    def on_servers(self, found):
        self.find_button.setEnabled(True)
        if not found:
            self.set_status('No local server is running. Start Ollama or LM '
                            'Studio, or type the address of your server.',
                            error=True)
            return
        name, url, models = found[0]
        self.provider.base_url = url
        self.url_edit.setText(url)
        self.changed.emit()
        self.on_models(models)
        others = ', '.join(n for n, _u, _m in found[1:])
        text = 'Found {} at {}.'.format(name, url)
        if others:
            text += ' Also running: {}.'.format(others)
        self.set_status(text)

    def refresh_web_button(self, has_web):
        provider = self.provider
        if not provider.web_sign_in:
            return
        missing = self.uses_app and not provider.cli
        self.locate_button.setVisible(missing)
        if missing:
            text = 'Install {} to Sign In'.format(provider.app_name)
            if provider.app is codex:
                tip = ('Codex signs in with your ChatGPT account, and nxt '
                       'uses it the same way. Install Codex, then sign in '
                       'here. If it is installed, press Locate and choose '
                       'it.')
            else:
                tip = ('Anthropic only lets a Claude account be used '
                       'through its own apps. Install Claude Code, then '
                       'sign in here with any Claude account. If it is '
                       'installed, press Locate and choose it.')
        elif has_web:
            text = 'Switch Account'
            tip = 'Sign in with a different {} account.'.format(
                provider.label)
            if isinstance(provider, providers.OpenAI):
                tip = ('Sign in with a different ChatGPT account, or the '
                       'same account in another workspace.')
        elif provider.app is codex:
            text = 'Sign in with Codex'
            tip = ('Opens Codex, which signs in in your browser with your '
                   'ChatGPT account. Chats count against that plan\'s '
                   'Codex limits.')
        elif self.uses_app:
            text = 'Sign in with Claude Code'
            tip = ('Opens Claude Code, which signs in in your browser with '
                   'any Claude account: Pro, Max, Ultra, Team or '
                   'Enterprise. Chats count against that account.')
        else:
            text = 'Sign in with {}'.format(provider.web_plan)
            tip = ('Sign in in the web browser. Chats count against your '
                   '{} plan.'.format(provider.web_plan))
        self.web_button.setText(text)
        self.web_button.setToolTip(tip)
        self.web_button.setMenu(self.accounts_menu(has_web))

    def accounts_menu(self, has_web):
        """For ChatGPT, the accounts signed in here before and a way to add
        another. None when there is nothing to pick from."""
        provider = self.provider
        if not isinstance(provider, providers.OpenAI):
            return None
        accounts = provider.saved_accounts()
        if not accounts:
            return None
        current = None
        if has_web:
            current = (provider.web_record() or {}).get('client_id')
        menu = QtWidgets.QMenu(self)
        for account in accounts:
            label = provider.account_label(account)
            action = menu.addAction(label)
            if account['client_id'] == current:
                action.setText(label + ' (signed in)')
                action.setEnabled(False)
            else:
                action.triggered.connect(
                    lambda _=False, a=account: self.sign_in(account=a))
        menu.addSeparator()
        other = menu.addAction('Another Account or Workspace...')
        other.setToolTip('Each ChatGPT workspace needs its own sign in.')
        other.triggered.connect(
            lambda _=False: self.sign_in(account=providers.NEW_ACCOUNT))
        # The old one is kept by the button until it is replaced.
        self._accounts_menu = menu
        return menu

    def refresh(self):
        provider = self.provider
        store_ok = provider.store.available
        if self.uses_app:
            has_web = bool(provider.web_record())
        else:
            has_web = bool(provider.web_record()) if store_ok else False
        has_key = bool(provider.saved_api_key()) if store_ok else False
        self.set_status(provider.status())
        self.refresh_web_button(has_web)
        self.web_button.setEnabled(store_ok or self.uses_app)
        self.sign_out_button.setEnabled(has_web)
        self.key_edit.setEnabled(store_ok)
        self.save_key_button.setEnabled(store_ok)
        self.remove_key_button.setEnabled(has_key)
        self.key_edit.clear()
        if has_key:
            placeholder = 'A key is saved. Paste a new one to replace it.'
        elif self.is_local:
            placeholder = 'Only if your server needs one'
        elif provider.env_api_key():
            placeholder = 'Using {}. Paste a key to save one.'.format(
                provider.env_var)
        else:
            placeholder = 'Paste an API key'
        self.key_edit.setPlaceholderText(placeholder)
        self.use_widget.setVisible(has_web and has_key and
                                   provider.web_sign_in)
        self.use_web.blockSignals(True)
        self.use_web.setChecked(provider.method != providers.KEY)
        self.use_key.setChecked(provider.method == providers.KEY)
        self.use_web.blockSignals(False)
        if provider.status() == 'Not set up.':
            self.set_models([], 'Sign in or add a key first'
                            if provider.takes_api_key else 'Sign in first')
        else:
            models = provider.cached_models()
            if models is None:
                self.set_models([], 'Loading models...')
                self.load_models()
            else:
                self.set_models(models)

    def on_use_toggled(self, _checked):
        self.provider.method = (providers.WEB if self.use_web.isChecked()
                                else providers.KEY)
        self.refresh()
        self.changed.emit()

    def on_model_changed(self, text):
        if text:
            self.provider.model = text
            self.update_header()
            self.changed.emit()

    def save_key(self):
        api_key = self.key_edit.text().strip()
        if not api_key:
            return
        try:
            self.provider.save_api_key(api_key)
        except secret_store.SecretStoreError as err:
            self.set_status('Could not save the key: {}'.format(err),
                            error=True)
            return
        self.refresh()
        self.changed.emit()
        self.stored.emit()
        self.check()

    def remove_key(self):
        self.provider.remove_api_key()
        self.refresh()
        self.changed.emit()

    def sign_out(self):
        name = self.provider.app_name
        if self.uses_app:
            answer = QtWidgets.QMessageBox.question(
                self, 'Sign Out of {}'.format(name),
                'This signs {} out on this computer, not just in nxt. Sign '
                'out?'.format(name))
            if answer != QtWidgets.QMessageBox.Yes:
                return
        try:
            self.provider.sign_out()
        except Exception as err:
            self.set_status('Could not sign out: {}'.format(err),
                            error=True)
            return
        self.refresh()
        self.changed.emit()

    def _run(self, fn, done, *args):
        self.thread = TaskThread(fn, *args, parent=self)
        self.thread.done.connect(done)
        self.thread.failed.connect(self.on_failed)
        self.thread.start()
        return self.thread

    def on_failed(self, message):
        self.close_wait()
        self.check_button.setEnabled(True)
        self.set_status(message, error=True)

    def close_wait(self):
        if self.wait_dialog:
            self.wait_dialog.done(0)
            self.wait_dialog = None

    def sign_in(self, account=None):
        provider = self.provider
        if self.uses_app:
            self.sign_in_with_app()
            return
        text = 'Finish signing in in your web browser.'
        # Signing in to an account made before, which OpenAI keeps to the
        # workspace it was made in.
        reusing = (isinstance(provider, providers.OpenAI) and
                   account is not providers.NEW_ACCOUNT and
                   bool(account or provider.web_record()))
        if reusing:
            text += ('\n\nIf OpenAI says the app is only for members of '
                     'its workspace, press Use Another Account or '
                     'Workspace.')
        self.wait_dialog = WaitDialog(
            'Sign in with {}'.format(provider.web_plan), text, self)
        self.wait_dialog.rejected.connect(self.cancel_sign_in)
        if reusing:
            self.wait_dialog.other_account_button.show()
            self.wait_dialog.other_account_button.clicked.connect(
                self.sign_in_another_account)
        if isinstance(provider, providers.XAI):
            self._run(lambda cancelled: provider.start_sign_in(),
                      self.on_xai_code)
        elif isinstance(provider, providers.OpenAI):
            def sign_in(cancelled):
                return provider.sign_in(open_url, cancelled=cancelled,
                                        account=account)
            self._run(sign_in, self.on_signed_in)
        else:
            def sign_in(cancelled):
                return provider.sign_in(open_url, cancelled=cancelled)
            self._run(sign_in, self.on_signed_in)
        self.wait_dialog.show()

    def sign_in_another_account(self):
        """Give up on this sign in and add a new account instead."""
        wait = self.wait_dialog
        self.cancel_sign_in()
        if wait:
            wait.done(0)
        self.sign_in(account=providers.NEW_ACCOUNT)

    def locate_app(self):
        provider = self.provider
        program = 'codex' if provider.app is codex else 'claude'
        name = program + '.exe' if sys.platform == 'win32' else program
        path = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Where is {}?'.format(provider.app_name),
            os.path.expanduser('~'),
            '{0} ({0});;All files (*)'.format(name))[0]
        if not path:
            return
        provider.prefs[provider.app_path_pref] = path
        provider.app.forget_status()
        self.refresh()
        self.changed.emit()

    def sign_in_with_app(self):
        provider = self.provider
        name = provider.app_name
        if not provider.cli:
            open_url(provider.app.INSTALL_URL)
            text = ('Install {0} from the page that opened, then press Sign '
                    'in with {0}.'.format(name))
            if provider.takes_api_key:
                text += ' Or paste an API key below.'
            self.set_status(text)
            return
        try:
            login = provider.start_sign_in()
        except (OSError, claude_code.ClaudeCodeError,
                codex.CodexError) as err:
            self.set_status('Could not start {}: {}'.format(name, err),
                            error=True)
            return
        self.login = login
        if provider.app is codex:
            text = ('Your web browser is opening the ChatGPT sign in for '
                    'Codex. This closes by itself once you are signed in.')
        else:
            text = ('Your web browser is opening the Claude sign in. Sign in '
                    'with any Claude account: Pro, Max, Ultra, Team or '
                    'Enterprise. This closes by itself once you are signed '
                    'in.')
        self.wait_dialog = WaitDialog('Sign in with {}'.format(name), text,
                                      self)
        self.wait_dialog.rejected.connect(self.cancel_sign_in)
        if hasattr(login, 'send_code'):
            self.wait_dialog.paste_widget.show()

            def send_code():
                login.send_code(self.wait_dialog.paste_edit.text())
                self.wait_dialog.paste_edit.clear()
                self.wait_dialog.paste_edit.setPlaceholderText(
                    'Code sent. Finishing the sign in...')
            self.wait_dialog.paste_button.clicked.connect(send_code)
            self.wait_dialog.paste_edit.returnPressed.connect(send_code)

        def show_link():
            if self.wait_dialog and login.url:
                self.wait_dialog.show_page_link(login.url)
                link_timer.stop()
        link_timer = QtCore.QTimer(self.wait_dialog)
        link_timer.timeout.connect(show_link)
        link_timer.start(250)

        def finish(cancelled):
            return provider.finish_sign_in(login, cancelled=cancelled)
        self._run(finish, self.on_signed_in)
        self.wait_dialog.show()

    def on_xai_code(self, device):
        if not self.wait_dialog:
            return
        url = (device.get('verification_uri_complete') or
               device['verification_uri'])
        self.wait_dialog.label.setText(
            'Approve this code on accounts.x.ai in your browser. It should '
            'already be filled in.')
        self.wait_dialog.show_code(device.get('user_code', ''), url)
        open_url(url)
        provider = self.provider

        def finish(cancelled):
            return provider.finish_sign_in(device, cancelled=cancelled)
        self._run(finish, self.on_signed_in)

    def cancel_sign_in(self):
        self.wait_dialog = None
        if self.thread:
            self.thread.cancel()
        login = getattr(self, 'login', None)
        if login:
            login.cancel()
            self.login = None

    def on_signed_in(self, _record):
        self.login = None
        self.close_wait()
        self.refresh()
        self.changed.emit()
        self.stored.emit()
        self.check()

    def check(self):
        self.check_button.setEnabled(False)
        self.set_status('Checking...')
        self.load_models(refresh=True, report=True)

    def load_models(self, refresh=False, report=False):
        if self.models_thread and self.models_thread.isRunning():
            # Its answer is dropped; this one is newer.
            self.models_thread.cancel()
        provider = self.provider
        self.models_thread = TaskThread(
            lambda cancelled: provider.models(refresh=refresh), parent=self)
        self.models_thread.done.connect(
            lambda models: self.on_models(models, report))
        self.models_thread.failed.connect(self.on_models_failed)
        self.models_thread.start()

    def on_models_failed(self, message):
        self.check_button.setEnabled(True)
        self.set_models([], 'No models')
        self.set_status('Could not get the models: {}'.format(message),
                        error=True)

    def set_models(self, models, empty_text='No models'):
        """Offer only the models the provider has, with one chosen."""
        provider = self.provider
        chosen = provider.choose_model(models)
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(models)
        self.model_combo.setPlaceholderText(empty_text)
        if chosen:
            self.model_combo.setCurrentText(chosen)
        else:
            self.model_combo.setCurrentIndex(-1)
        self.model_combo.setEnabled(bool(models))
        self.model_combo.blockSignals(False)
        if chosen and chosen != provider.model:
            provider.model = chosen
            self.changed.emit()

    def on_models(self, models, report=True):
        self.check_button.setEnabled(True)
        self.set_models(models)
        if report:
            self.set_status('{} It can use {} models.'.format(
                self.provider.status(), len(models)))

    def stop(self):
        for thread in (self.thread, self.models_thread):
            if thread:
                thread.cancel()
                thread.wait(2000)


def scrolling(page):
    """page in a scroll area of its own, so a tab can be taller than the
    window and still be got to the bottom of."""
    area = QtWidgets.QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QtWidgets.QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
    area.setWidget(page)
    area.viewport().setAutoFillBackground(False)
    page.setAutoFillBackground(False)
    return area


class AiSettingsDialog(QtWidgets.QDialog):
    """Options > AI Assistant.

    What turns it on and says what it does stays at the top, and Close at
    the bottom. Between them each tab scrolls, and each provider is a
    section that opens from its header, which says how it is set up. The
    provider asked first starts open.
    """
    enabled_changed = QtCore.Signal(bool)
    settings_changed = QtCore.Signal()
    # The part of the screen it may take, so Close is always on it.
    SCREEN_SHARE = 0.9

    def __init__(self, parent=None, store=None, prefs=None):
        super(AiSettingsDialog, self).__init__(parent)
        self.setWindowTitle('AI Assistant')
        self.prefs = prefs if prefs is not None else user_dir.user_prefs
        self.store = store or secret_store.get_store()
        layout = QtWidgets.QVBoxLayout(self)

        self.enable_check = QtWidgets.QCheckBox('Turn on the AI assistant')
        self.enable_check.setChecked(providers.is_enabled(self.prefs))
        self.enable_check.toggled.connect(self.on_enable_toggled)
        layout.addWidget(self.enable_check)
        self.off_hint = QtWidgets.QLabel('Turn this on to set up sign ins.')
        self.off_hint.setStyleSheet(theme.fill('color: {TEXT_DIM};'))
        layout.addWidget(self.off_hint)
        about = QtWidgets.QLabel(
            'Adds an AI Assistant panel to the Window menu. Nothing is '
            'sent to a provider until you ask it something, and then only '
            'your message and, if you choose, the selected nodes.')
        about.setWordWrap(True)
        layout.addWidget(about)

        self.store_label = QtWidgets.QLabel()
        self.store_label.setWordWrap(True)
        layout.addWidget(self.store_label)
        self.refresh_store_label()

        self.body = QtWidgets.QTabWidget()
        layout.addWidget(self.body, 1)
        providers_tab = QtWidgets.QWidget()
        tab_layout = QtWidgets.QVBoxLayout(providers_tab)
        sections = QtWidgets.QWidget()
        body_layout = QtWidgets.QVBoxLayout(sections)
        body_layout.setContentsMargins(0, 4, 4, 0)
        body_layout.setSpacing(6)
        self.sections = scrolling(sections)
        self.body.addTab(providers_tab, 'Providers')
        self.memory_page = MemoryPage(prefs=self.prefs)
        self.memory_page.changed.connect(self.settings_changed.emit)
        self.body.addTab(scrolling(self.memory_page), 'Memory')
        # Which one is asked first is for all of them, so it stays put
        # above them.
        default_row = QtWidgets.QHBoxLayout()
        default_row.addWidget(QtWidgets.QLabel('Ask'))
        self.provider_combo = QtWidgets.QComboBox()
        self.providers = providers.get_providers(store=self.store,
                                                 prefs=self.prefs)
        for provider in self.providers:
            self.provider_combo.addItem(provider.label, provider.id)
        current = self.prefs.get(user_dir.USER_PREF.AI_PROVIDER)
        index = self.provider_combo.findData(current)
        self.provider_combo.setCurrentIndex(max(index, 0))
        self.provider_combo.currentIndexChanged.connect(
            self.on_provider_changed)
        default_row.addWidget(self.provider_combo)
        default_row.addWidget(QtWidgets.QLabel('first'))
        default_row.addStretch()
        tab_layout.addLayout(default_row)
        tab_layout.addWidget(self.sections, 1)
        self.boxes = []
        for provider in self.providers:
            box = ProviderBox(provider, self)
            box.changed.connect(self.settings_changed.emit)
            box.stored.connect(self.refresh_store_label)
            body_layout.addWidget(box)
            self.boxes.append(box)
        body_layout.addStretch()
        self.mark_default()
        default_box = self.box(self.provider_combo.currentData())
        if default_box is not None:
            default_box.set_expanded(True)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self.set_controls_enabled(self.enable_check.isChecked())
        self.setMinimumSize(560, 420)
        self.resize(600, 720)

    def box(self, provider_id):
        for box in self.boxes:
            if box.provider.id == provider_id:
                return box
        return None

    def mark_default(self):
        current = self.provider_combo.currentData()
        for box in self.boxes:
            box.header.set_default(box.provider.id == current)

    def set_controls_enabled(self, enabled):
        """With the assistant off its settings can be looked at, opening
        and closing sections, but not changed."""
        self.off_hint.setVisible(not enabled)
        self.provider_combo.setEnabled(enabled)
        self.memory_page.setEnabled(enabled)
        for box in self.boxes:
            box.set_controls_enabled(enabled)

    def fit_screen(self):
        """No taller than most of the screen it is on, so Close stays on
        it."""
        screen = self.screen() if hasattr(self, 'screen') else None
        if screen is None:
            return
        room = int(screen.availableGeometry().height() * self.SCREEN_SHARE)
        if self.height() > room:
            self.resize(self.width(), max(room, self.minimumHeight()))

    def refresh_store_label(self):
        if self.store.available:
            where = self.store.describe()
            self.store_label.setFont(theme.font(theme.SMALL_PX))
            self.store_label.setStyleSheet(theme.fill('color: {TEXT_DIM};'))
        else:
            where = ('There is no secure storage on this computer, so keys '
                     'and sign ins can not be saved. Set ANTHROPIC_API_KEY, '
                     'OPENAI_API_KEY or XAI_API_KEY before starting nxt '
                     'instead.')
            self.store_label.setFont(theme.font(theme.TEXT_PX))
            self.store_label.setStyleSheet(
                'color: {};'.format(theme.ERROR))
        self.store_label.setText(where)

    def refresh_sign_ins(self, older_than=0):
        claude_code.forget_status(older_than)
        codex.forget_status(older_than)
        for box in self.boxes:
            if not (box.thread and box.thread.isRunning()):
                box.refresh()
        self.settings_changed.emit()

    def showEvent(self, event):
        super(AiSettingsDialog, self).showEvent(event)
        self.fit_screen()
        self.refresh_sign_ins()

    def changeEvent(self, event):
        super(AiSettingsDialog, self).changeEvent(event)
        if (event.type() == QtCore.QEvent.ActivationChange and
                self.isActiveWindow()):
            self.refresh_sign_ins(older_than=5)

    def on_enable_toggled(self, state):
        self.prefs[user_dir.USER_PREF.AI_ENABLED] = bool(state)
        self.set_controls_enabled(state)
        self.enabled_changed.emit(bool(state))

    def on_provider_changed(self, _index):
        self.prefs[user_dir.USER_PREF.AI_PROVIDER] = \
            self.provider_combo.currentData()
        self.mark_default()
        self.settings_changed.emit()

    def closeEvent(self, event):
        for box in self.boxes:
            box.stop()
        super(AiSettingsDialog, self).closeEvent(event)

    def done(self, result):
        for box in self.boxes:
            box.stop()
        super(AiSettingsDialog, self).done(result)
