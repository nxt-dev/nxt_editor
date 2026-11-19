"""Edit > Preferences: every setting a user can set, by section.

Preferences are kept in the user's prefs.json, and many are only set from
a menu toggle somewhere, or not at all, so the only way to find them was
to read the source. This lists the sections on the left, and shows the
chosen one's preferences on the right with what each does, and sets them
straight away.

A preference with a toggle in a menu is set by triggering that toggle, so
the menu shows it and the editor does whatever the toggle does when it
changes. Others are written to the file, and read from there the next
time they are needed. Hotkeys are a section of their own, and the AI
Assistant, Environment Variables and Optional Components are pages, the
windows they were before shown in place, see MainWindow.settings_page.
"""
# Builtin
import html
import logging
import os
import re
from collections import namedtuple

# External
from Qt import QtCore, QtGui, QtWidgets

# Internal
from nxt_editor import theme, user_dir
from nxt_editor.dockwidgets import code_completion
from nxt_editor.stage_model import EXEC_FRAMING

logger = logging.getLogger(__name__)

PREF = user_dir.USER_PREF
BOOL, INT, FLOAT, TEXT, CHOICE = 'bool', 'int', 'float', 'text', 'choice'

#: key: the prefs.json key. kind: one of BOOL, INT, FLOAT, TEXT, CHOICE.
#: choices: (value, label) pairs for a CHOICE. action: for a toggle that
#: is not a BoolUserPrefAction, where it is on the main window, as
#: 'attr.attr'. A BoolUserPrefAction is found by its pref key.
Preference = namedtuple('Preference', ('key', 'section', 'label', 'kind',
                                       'default', 'description', 'choices',
                                       'action', 'low', 'high'))


def preference(key, section, label, kind, default, description,
               choices=(), action=None, low=0, high=100):
    return Preference(key, section, label, kind, default, description,
                      choices, action, low, high)


PREFERENCES = (
    # Graph --------------------------------------------------------------
    preference(PREF.SHOW_GRID, 'Graph', 'Show Grid', BOOL, True,
               'Draw the grid behind the graph, in every tab.'),
    preference(PREF.GRID_SNAP, 'Graph', 'Snap to Grid', BOOL, False,
               'Nodes moved in the graph land on the nearest grid line.',
               action='alignment_actions.snap_action'),
    preference(PREF.SHOW_MINI_MAP, 'Graph', 'Mini Map', BOOL, True,
               'Show the mini map in the corner of the graph.'),
    preference(PREF.FRAME_ON_OPEN, 'Graph', 'Frame All on Open', BOOL, True,
               'Frame all of a graph when it is first shown, rather than '
               'showing the origin.'),
    preference(PREF.ANIMATION, 'Graph', 'Animate Nodes', BOOL, False,
               'Nodes glide to where they go when they are moved for you, '
               'say by a layout.'),
    preference(PREF.NODE_TOOLTIPS, 'Graph', 'Node Tooltips', BOOL, True,
               'Show a node\'s details when the mouse rests on it.',
               action='view_actions.tooltip_action'),
    preference(PREF.CONNECTION_STYLE, 'Graph', 'Lines', CHOICE, 'straight',
               'How lines between nodes are drawn in a graph that has not '
               'saved its own choice.',
               choices=(('straight', 'Straight'), ('curved', 'Curved'))),
    preference(PREF.ZOOM_MULT, 'Graph', 'Drag Zoom Speed', FLOAT, 1.0,
               'How fast dragging to zoom zooms. 1 is normal, 2 twice as '
               'fast.', low=0.1, high=10),
    preference(PREF.LOD, 'Graph', 'Simple Drawing Below', FLOAT, 0.4,
               'Zoomed out past this, 0.4 being 40%, nodes are drawn without '
               'their details, to keep big graphs quick. After a restart.',
               low=0, high=2),
    preference(PREF.FPS, 'Graph', 'Frame Rate', BOOL, True,
               'Show how fast the graph is drawing, in its corner. For '
               'graphs opened afterwards.'),
    # Running ------------------------------------------------------------
    preference(PREF.IGNORE_BREAKS, 'Running', 'Ignore Breakpoints', BOOL,
               False, 'Run straight through breakpoints, keeping them.'),
    preference(PREF.SKIP_INITIAL_BREAK, 'Running',
               'Skip Breakpoint on First Node', BOOL, True,
               'A run started from a node with a breakpoint does not stop '
               'on it before it has begun.'),
    preference(PREF.EXEC_FRAMING, 'Running', 'Follow the Run', CHOICE,
               EXEC_FRAMING.STEPPING,
               'Whether the graph frames each node as it runs.',
               choices=((EXEC_FRAMING.NEVER, 'Never'),
                        (EXEC_FRAMING.STEPPING, 'When Stepping'),
                        (EXEC_FRAMING.ALWAYS, 'Always'))),
    preference(PREF.DING, 'Running', 'Error Sound', BOOL, True,
               'Play a sound when a build fails or nxt warns you, and flash '
               'nxt when it is behind other windows.',
               action='app_actions.toggle_ding_action'),
    preference(PREF.RECOMP_PREF, 'Running', 'Workflow Tools Always Recomp',
               BOOL, True,
               'Workflow tools recomposite the graph each time they run.',
               action='execute_actions.wt_recomp_action'),
    # Editing ------------------------------------------------------------
    preference(PREF.CHECK_DISK_CHANGES, 'Editing',
               'Notice Files Changed on Disk', BOOL, True,
               'When the editor comes back to the front, offer to reload '
               'files something else changed.'),
    preference(PREF.REFACTOR_ATTR_RENAME, 'Editing',
               'Update Tokens on Attr Rename', BOOL, True,
               'Renaming an attribute renames the tokens in its layer that '
               'use it.'),
    preference(PREF.REFACTOR_INSTANCE_PATHS, 'Editing',
               'Update Instance Paths on Parent', BOOL, True,
               'Parenting nodes updates the instance paths in the layer '
               'that point at them.'),
    # Panels -------------------------------------------------------------
    preference(PREF.LOOK, 'Panels', 'Look', CHOICE, theme.LOOK_MODERN,
               'Modern is the editor\'s own look, the same everywhere. '
               'Classic is how it looked before. Host application looks '
               "like the host the editor is in: Maya's own widgets, or "
               "Blender's or Unreal's colors and font. On its own, the "
               'editor is Modern. '
               'Shown when the editor reopens, which it offers to do.',
               choices=theme.LOOK_NAMES),
    preference(PREF.LOOK_STYLESHEET, 'Panels', 'Stylesheet', TEXT, '',
               'A .qss file of your own, laid over the look, to restyle '
               'what you like. It can use the look\'s colors by name, such '
               'as {BASE} and {TEXT}. Shown when the editor reopens, '
               'which it offers to do.'),
    preference(PREF.NEUTRAL_PROPERTY_TEXT, 'Panels',
               'Neutral Property Text', BOOL, False,
               'Property Editor rows in plain text with their layer\'s '
               'color beside them, rather than in that color.',
               action='view_actions.neutral_property_text_action'),
    preference(PREF.HISTORICAL_LABEL_FORMAT, 'Panels',
               'History Menu Labels', TEXT, '{source}.{attr_name}  {value}',
               'How earlier values are labeled in the Property Editor\'s '
               'history menu. {source}, {attr_name} and {value} are filled '
               'in.'),
    preference(PREF.LAYER_TABLE, 'Panels', 'Layer Manager as Table', BOOL,
               False, 'List layers flat, rather than each under the one '
               'that references it.'),
    preference(PREF.TREE_INDENT, 'Panels', 'Layer Indent', INT, 20,
               'Pixels each layer is set in under the one that references '
               'it, in the Layer Manager. After a restart.', low=0,
               high=100),
    preference(PREF.OUTPUT_LOG_WRAP, 'Panels', 'Wrap Output Log Lines', BOOL,
               True, 'Wrap long lines in the Output Log to its width.',
               action='output_log.wrap_action'),
    # Code Editor --------------------------------------------------------
    preference(PREF.CE_AUTOCOMPLETE, 'Code Editor', 'Autocomplete', BOOL,
               True, 'Offer completions as you type, without asking.',
               action='code_editor_actions.autocomplete_action'),
    preference(PREF.CE_COMPLETE_PYTHON, 'Code Editor', 'Complete Python',
               BOOL, True, 'Complete Python\'s keywords and builtins.'),
    preference(PREF.CE_COMPLETE_MODULES, 'Code Editor', 'Complete Modules',
               BOOL, True, 'Complete modules that can be imported.'),
    preference(PREF.CE_COMPLETE_NODE, 'Code Editor', 'Complete From Nodes',
               BOOL, True, 'Complete node paths, attributes and tokens.'),
    preference(PREF.CE_COMPLETE_DOCUMENT, 'Code Editor',
               'Complete From the Code', BOOL, True,
               'Complete names already in the code being edited.'),
    preference(PREF.CE_COMPLETE_HOST, 'Code Editor', 'Complete From Host',
               BOOL, True,
               'Complete from what the host application has loaded.'),
    preference(PREF.CE_COMPLETE_JEDI, 'Code Editor', 'Python Analysis',
               BOOL, True, 'Work out what names hold with jedi, to complete '
               'after a dot. Kept for when jedi is installed, see Optional '
               'Components.'),
    preference(PREF.SHOW_CE_DATA_STATE, 'Code Editor', 'Data State Overlay',
               BOOL, True, 'Show which view of the code, raw or resolved, '
               'the Code Editor is showing.',
               action='code_editor_actions.show_data_state_action'),
    preference(PREF.SHOW_DBL_CLICK_MSG, 'Code Editor',
               'Double Click Message', BOOL, True,
               'Show the hint to double click the code to edit it.',
               action='code_editor_actions.overlay_message_action'),
)

#: The width of a value's box, the same on every page so they line up.
EDITOR_WIDTH = 220
#: How long typing in the search box pauses before it searches, as in the
#: Outliner. Enter searches at once.
SEARCH_DELAY_MS = 300


def current(pref):
    """The value of a preference, its default if it is not set."""
    value = user_dir.user_prefs.get(pref.key, pref.default)
    try:
        if pref.kind == BOOL:
            return bool(value)
        if pref.kind == INT:
            return int(value)
        if pref.kind == FLOAT:
            return float(value)
        if pref.kind == TEXT:
            return str(value)
    except (TypeError, ValueError):
        return pref.default
    return value


def find_action(main_window, pref):
    """The menu toggle that sets a preference, or None."""
    if pref.action:
        obj = main_window
        for name in pref.action.split('.'):
            obj = getattr(obj, name, None)
            if obj is None:
                return None
        return obj
    for action in main_window.findChildren(QtWidgets.QAction):
        if getattr(action, 'pref_key', None) == pref.key:
            return action
    sources = getattr(getattr(main_window, 'code_editor_actions', None),
                      'completion_source_actions', ())
    for action, key, _default in sources:
        if key == pref.key:
            return action
    return None


def set_preference(main_window, pref, value):
    """Set a preference, through its menu toggle if it has one."""
    action = find_action(main_window, pref) if main_window else None
    if (pref.key == PREF.CE_COMPLETE_JEDI and
            not code_completion.JEDI.installed()):
        # Its toggle would offer to install jedi. The choice is kept for
        # when jedi is there, as the toggle keeps it.
        action = None
    if action is not None and action.isCheckable():
        if action.isChecked() != bool(value):
            action.trigger()
        # A toggle that writes on triggered alone, or one already showing
        # the value with the file saying otherwise, still leaves it saved.
        user_dir.user_prefs[pref.key] = bool(value)
        return
    user_dir.user_prefs[pref.key] = value


def sections():
    """The sections, in the order their preferences are listed."""
    names = []
    for pref in PREFERENCES:
        if pref.section not in names:
            names.append(pref.section)
    return names


def about_style():
    global ABOUT_STYLE
    if not ABOUT_STYLE:
        ABOUT_STYLE = theme.fill('color: {TEXT_DIM};')
    return ABOUT_STYLE


class SettingRow(QtWidgets.QFrame):
    """One setting: its name and what it does, its value, and a button
    that puts it back to its default when it is not there already.

    :param title: its name
    :param about: what it does
    :param search_text: everything a search may find it by
    :param editor: the widget that shows and changes the value
    :param tag: a word shown beside the name, such as Global
    """
    RESET_TEXT = 'Reset'

    def __init__(self, title, about, search_text, editor, tag='',
                 tip='', wide_editor=True, parent=None):
        super(SettingRow, self).__init__(parent)
        self.title = title
        self.about_text = about
        self.search_text = search_text.lower()
        self.editor = editor
        # What the labels show marked, so a search only rewrites the rows
        # whose marks change.
        self.marked_words = ()
        # The row's from the start: a widget made visible before it has a
        # parent opens as a window of its own, for a moment.
        editor.setParent(self)
        self.setObjectName('SettingRow')
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 10, 4, 10)
        layout.setSpacing(16)
        words = QtWidgets.QVBoxLayout()
        words.setSpacing(3)
        name_row = QtWidgets.QHBoxLayout()
        name_row.setSpacing(8)
        # Rich text, so a search can mark the words it found.
        self.name = QtWidgets.QLabel(marked(title, []), self)
        self.name.setTextFormat(QtCore.Qt.RichText)
        self.name.setFont(theme.font(theme.TEXT_PX,
                                     weight=QtGui.QFont.Medium))
        name_row.addWidget(self.name)
        self.tag = None
        if tag:
            self.tag = QtWidgets.QLabel(tag, self)
            self.tag.setFont(theme.font(theme.SMALL_PX))
            self.tag.setStyleSheet(theme.fill(
                'color: {TEXT}; background: {ACCENT_DIM}; '
                'border-radius: 4px; padding: 1px 6px;'))
            name_row.addWidget(self.tag)
        name_row.addStretch(1)
        words.addLayout(name_row)
        self.about = QtWidgets.QLabel(marked(about, []), self)
        self.about.setTextFormat(QtCore.Qt.RichText)
        self.about.setWordWrap(True)
        self.about.setFont(theme.font(theme.SMALL_PX))
        self.about.setStyleSheet(about_style())
        self.about.setVisible(bool(about))
        words.addWidget(self.about)
        layout.addLayout(words, 1)
        if tip:
            self.name.setToolTip(tip)
            self.about.setToolTip(tip)
        if wide_editor:
            editor.setFixedWidth(EDITOR_WIDTH)
            layout.addWidget(editor, 0, QtCore.Qt.AlignVCenter)
        else:
            layout.addWidget(editor, 0, QtCore.Qt.AlignRight |
                             QtCore.Qt.AlignVCenter)
        self.extra = QtWidgets.QHBoxLayout()
        self.extra.setSpacing(4)
        layout.addLayout(self.extra)
        self.reset_button = QtWidgets.QToolButton(self)
        self.reset_button.setText(self.RESET_TEXT)
        # Keeps its room when hidden, so values do not move as it shows.
        policy = self.reset_button.sizePolicy()
        policy.setRetainSizeWhenHidden(True)
        self.reset_button.setSizePolicy(policy)
        layout.addWidget(self.reset_button, 0, QtCore.Qt.AlignVCenter)

    def is_default(self):
        return True

    def update_reset(self):
        self.reset_button.setVisible(not self.is_default())

    def matches(self, words):
        return all(word in self.search_text for word in words)

    def mark(self, words):
        """Show the searched for words in the name and what it does."""
        words = tuple(words)
        if words == self.marked_words:
            return
        self.marked_words = words
        self.name.setText(marked(self.title, words))
        if self.about_text:
            self.about.setText(marked(self.about_text, words))


class PreferenceRow(SettingRow):
    """A preference from PREFERENCES."""

    def __init__(self, pref, editor, parent=None):
        self.pref = pref
        tip = '{}\n\n{} in prefs.json'.format(pref.description, pref.key)
        search = ' '.join((pref.section, pref.label, pref.description,
                           pref.key))
        super(PreferenceRow, self).__init__(
            pref.label, pref.description, search, editor, tip=tip,
            wide_editor=pref.kind != BOOL, parent=parent)
        self.section = pref.section
        self.reset_button.setToolTip('Back to the default, {}.'.format(
            describe(pref, pref.default)))
        self.update_reset()

    def is_default(self):
        return current(self.pref) == self.pref.default


def marked(text, words):
    """text as rich text, with each of words in it highlighted."""
    if not words:
        return html.escape(text)
    pattern = re.compile('|'.join(re.escape(word) for word in
                                  sorted(words, key=len, reverse=True)),
                         re.IGNORECASE)
    parts, last = [], 0
    for match in pattern.finditer(text):
        parts.append(html.escape(text[last:match.start()]))
        parts.append('<span style="background-color: {}; color: {};">{}'
                     '</span>'.format(theme.ACCENT_STRONG, theme.TEXT,
                                      html.escape(match.group(0))))
        last = match.end()
    parts.append(html.escape(text[last:]))
    return ''.join(parts)


def describe(pref, value):
    """A value as Preferences shows it, for a tooltip."""
    if pref.kind == BOOL:
        return 'on' if value else 'off'
    if pref.kind == CHOICE:
        for choice, label in pref.choices:
            if choice == value:
                return label
    if pref.kind == TEXT and not value:
        return 'empty'
    return str(value)


ABOUT_STYLE = ''


def heading(text, px=18):
    label = QtWidgets.QLabel(text)
    label.setFont(theme.font(px, weight=QtGui.QFont.Medium))
    return label


def embedded(dialog, keep=()):
    """A dialog shown as a page of Preferences: a widget in place of a
    window, without the buttons that close it, which Close does there.

    :param keep: the standard buttons of its button box to leave, such as
        Apply
    :return: the dialog
    """
    dialog.setWindowFlags(QtCore.Qt.Widget)
    dialog.setSizeGripEnabled(False)
    dialog.setMinimumSize(0, 0)
    for box in dialog.findChildren(QtWidgets.QDialogButtonBox):
        shown = 0
        for button in box.buttons():
            if box.standardButton(button) in keep:
                shown += 1
            else:
                button.hide()
        box.setVisible(bool(shown))
    return dialog


#: Hotkeys, and the pages of settings that have windows of their own
#: elsewhere, after the sections of PREFERENCES. Each: (name, what it is
#: for, words a search finds it by).
HOTKEYS = 'Hotkeys'
AI_ASSISTANT = 'AI Assistant'
ENV_VARIABLES = 'Environment Variables'
OPTIONAL_COMPONENTS = 'Optional Components'
PAGES = (
    (AI_ASSISTANT, 'Turn the AI Assistant on, sign in to providers, save '
     'API keys and choose what it remembers.',
     'ai assistant claude openai chatgpt codex grok api key sign in login '
     'provider model memory'),
    (ENV_VARIABLES, 'Edit the env files nxt sets environment variables from '
     'when it starts: your own, the site\'s, and project files.',
     'environment variables env file path project site roots'),
    (OPTIONAL_COMPONENTS, 'Install extras the editor can use, such as jedi '
     'for smarter code completion.',
     'optional components install jedi package extras'),
)


class PageLink(QtWidgets.QFrame):
    """In search results, a page whose name or purpose was found, with a
    button that goes there."""
    chosen = QtCore.Signal(str)

    def __init__(self, name, about, keywords, parent=None):
        super(PageLink, self).__init__(parent)
        self.page = name
        self.title = name
        self.about_text = about
        self.search_text = ' '.join((name, about, keywords)).lower()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 18)
        layout.setSpacing(4)
        layout.addWidget(heading(name))
        row = QtWidgets.QHBoxLayout()
        self.about = QtWidgets.QLabel(marked(about, []))
        self.about.setTextFormat(QtCore.Qt.RichText)
        self.about.setWordWrap(True)
        self.about.setStyleSheet(theme.fill('color: {TEXT_DIM};'))
        row.addWidget(self.about, 1)
        self.button = QtWidgets.QPushButton('Show {}'.format(name))
        self.button.clicked.connect(lambda _=False: self.chosen.emit(name))
        row.addWidget(self.button)
        layout.addLayout(row)

    def matches(self, words):
        return all(word in self.search_text for word in words)

    def mark(self, words):
        self.about.setText(marked(self.about_text, words))


class PreferenceEditor(QtWidgets.QDialog):
    """Every preference a user can set, a section at a time, set as it is
    changed.

    The sections are listed on the left, and the chosen one shown on the
    right: the preferences by section, every action's hotkey, and the
    pages for the AI Assistant, environment variables and optional
    components. A search looks through all of them at once, and shows what
    it finds under each section's title with the words found marked, until
    it is cleared and the section chosen before is back.
    """
    SECTION_LIST_WIDTH = 190

    def __init__(self, main_window=None, parent=None):
        super(PreferenceEditor, self).__init__(parent or main_window)
        self.hotkey_list = None
        self.main_window = main_window
        self.setWindowTitle('Preferences')
        self.resize(900, 640)
        self.editors = {}  # key: widget
        self.rows = {}  # key: SettingRow, preferences and hotkeys
        self.blocks = {}  # section: its title and rows
        self.links = {}  # page: PageLink, for search results
        self.pages = {}  # page: its widget, made when first shown
        self.holders = {}  # page: what the stack shows it in
        self.words = []  # what is searched for, empty when nothing is
        self.section_before = None
        self._filling = False

        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            'Changes are made straight away. Your preferences are kept in '
            '{}.'.format(user_dir.USER_PREFS_PATH))
        intro.setWordWrap(True)
        intro.setFont(theme.font(theme.SMALL_PX))
        intro.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        intro.setStyleSheet(theme.fill('color: {TEXT_DIM};'))
        layout.addWidget(intro)

        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText('Search all preferences and hotkeys')
        self.filter.setClearButtonEnabled(True)
        self.filter.setToolTip('Finds a preference, a hotkey or a page by '
                               'its name or what it does. Searches once '
                               'typing stops, or on Enter.')
        self.search_timer = QtCore.QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(SEARCH_DELAY_MS)
        self.search_timer.timeout.connect(self.search_now)
        self.filter.textChanged.connect(self.on_search_edited)
        self.filter.returnPressed.connect(self.search_now)
        layout.addWidget(self.filter)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(12)
        self.section_list = QtWidgets.QListWidget()
        self.section_list.setFixedWidth(self.SECTION_LIST_WIDTH)
        self.section_list.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.section_list.setStyleSheet(theme.fill(
            'QListWidget {background: transparent;}'
            'QListWidget::item {padding: 7px 10px; '
            'border-radius: {RADIUS}px;}'))
        self.section_list.currentRowChanged.connect(self.show_section)
        body.addWidget(self.section_list)

        self.page = QtWidgets.QWidget()
        self.page.setStyleSheet(theme.fill(
            '#SettingRow {border: none; '
            'border-bottom: 1px solid {BORDER};}'))
        self.page_layout = QtWidgets.QVBoxLayout(self.page)
        self.page_layout.setContentsMargins(4, 0, 12, 8)
        self.page_layout.setSpacing(0)
        self.nothing_found = QtWidgets.QLabel()
        self.nothing_found.setStyleSheet(theme.fill('color: {TEXT_DIM};'))
        self.nothing_found.setAlignment(QtCore.Qt.AlignCenter)
        self.nothing_found.hide()
        self.area = QtWidgets.QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.area.setWidget(self.page)
        self.area.verticalScrollBar().valueChanged.connect(
            self.follow_scroll)
        self.stack = QtWidgets.QStackedWidget()
        self.stack.addWidget(self.area)
        body.addWidget(self.stack, 1)
        layout.addLayout(body, 1)

        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        close = QtWidgets.QPushButton('Close')
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addLayout(row)

        self.fill()
        self.section_list.setCurrentRow(0)

    # Sections ------------------------------------------------------------

    def section_names(self):
        """Every section in the list, in order."""
        names = sections()
        if self.main_window is not None:
            names.append(HOTKEYS)
            for name, _about, _keywords in PAGES:
                if self.has_page(name):
                    names.append(name)
        return names

    def has_page(self, name):
        if name == ENV_VARIABLES:
            from nxt_editor import env_dialog
            return env_dialog.available()
        return True

    def fill(self):
        self._filling = True
        self.section_list.clear()
        self.editors, self.rows, self.blocks = {}, {}, {}
        self.links = {}
        self.page_layout.addWidget(self.nothing_found)
        for name in sections():
            block, block_layout = self.new_block(name)
            for pref in PREFERENCES:
                if pref.section != name:
                    continue
                editor = self.make_editor(pref)
                self.editors[pref.key] = editor
                pref_row = PreferenceRow(pref, editor)
                pref_row.reset_button.clicked.connect(
                    lambda _=False, p=pref: self.reset(p))
                self.rows[pref.key] = pref_row
                block_layout.addWidget(pref_row)
        if self.main_window is not None:
            self.fill_hotkeys()
            for name, about, keywords in PAGES:
                if not self.has_page(name):
                    continue
                link = PageLink(name, about, keywords)
                link.chosen.connect(self.go_to_page)
                link.hide()
                self.links[name] = link
                self.page_layout.addWidget(link)
        self.page_layout.addStretch(1)
        for name in self.section_names():
            self.section_list.addItem(name)
        self._filling = False

    def new_block(self, name):
        block = QtWidgets.QWidget()
        block_layout = QtWidgets.QVBoxLayout(block)
        block_layout.setContentsMargins(0, 0, 0, 18)
        block_layout.setSpacing(0)
        title = heading(name)
        title.setContentsMargins(4, 0, 0, 8)
        block_layout.addWidget(title)
        self.page_layout.addWidget(block)
        self.blocks[name] = block
        return block, block_layout

    def fill_hotkeys(self):
        """Every action with a hotkey, by the part of the editor it works
        in, under one Hotkeys section."""
        from nxt_editor import hotkey_settings
        block, block_layout = self.new_block(HOTKEYS)
        note = QtWidgets.QLabel(hotkey_settings.HOW_TO)
        note.setWordWrap(True)
        note.setFont(theme.font(theme.SMALL_PX))
        note.setStyleSheet(theme.fill('color: {TEXT_DIM};'))
        note.setContentsMargins(4, 0, 0, 8)
        block_layout.addWidget(note)
        self.hotkeys = hotkey_settings.Hotkeys(self.main_window)
        self.hotkey_list = hotkey_settings.HotkeyList(self.hotkeys, block)
        block_layout.addWidget(self.hotkey_list)

    def show_section(self, row):
        """The chosen section alone, or, while searching, what was found,
        moved to that section's part of it."""
        if row < 0:
            return
        name = self.section_names()[row]
        if name in self.links:
            if self.words:
                self.scroll_to(self.links[name])
                return
            self.stack.setCurrentWidget(self.page_widget(name))
            return
        self.stack.setCurrentWidget(self.area)
        if self.words:
            self.scroll_to(self.blocks[name])
            return
        for section, block in self.blocks.items():
            block.setVisible(section == name)
        self.area.verticalScrollBar().setValue(0)

    def scroll_to(self, widget):
        # Chosen, it stays chosen, even where the last results can not
        # scroll to the top.
        bar = self.area.verticalScrollBar()
        bar.blockSignals(True)
        bar.setValue(widget.y())
        bar.blockSignals(False)

    def current_section(self):
        item = self.section_list.currentItem()
        return item.text() if item else None

    def select_section(self, name):
        names = self.section_names()
        if name in names:
            self.section_list.setCurrentRow(names.index(name))

    def page_widget(self, name):
        """A page of its own, made the first time it is shown."""
        widget = self.pages.get(name)
        if widget is None:
            widget = self.main_window.settings_page(name, self)
            self.pages[name] = widget
            holder = widget
            if not getattr(widget, 'has_title', False):
                # Titled as the sections are.
                holder = QtWidgets.QWidget()
                holder_layout = QtWidgets.QVBoxLayout(holder)
                holder_layout.setContentsMargins(4, 0, 0, 0)
                title = heading(name)
                title.setContentsMargins(4, 0, 0, 4)
                holder_layout.addWidget(title)
                holder_layout.addWidget(widget, 1)
            self.holders[name] = holder
            self.stack.addWidget(holder)
        return self.holders[name]

    def go_to_page(self, name):
        self.filter.clear()
        self.select_section(name)

    # Preferences ---------------------------------------------------------

    def make_editor(self, pref):
        value = current(pref)
        if pref.kind == BOOL:
            editor = QtWidgets.QCheckBox()
            editor.setChecked(value)
            editor.toggled.connect(lambda v, p=pref: self.changed(p, v))
        elif pref.kind == INT:
            editor = QtWidgets.QSpinBox()
            editor.setRange(int(pref.low), int(pref.high))
            editor.setValue(value)
            editor.valueChanged.connect(lambda v, p=pref: self.changed(p, v))
        elif pref.kind == FLOAT:
            editor = QtWidgets.QDoubleSpinBox()
            editor.setRange(pref.low, pref.high)
            editor.setSingleStep(0.1)
            editor.setDecimals(2)
            editor.setValue(value)
            editor.valueChanged.connect(lambda v, p=pref: self.changed(p, v))
        elif pref.kind == CHOICE:
            editor = QtWidgets.QComboBox()
            for choice, label in pref.choices:
                editor.addItem(label, choice)
            index = editor.findData(value)
            editor.setCurrentIndex(index if index >= 0 else
                                   editor.findData(pref.default))
            editor.currentIndexChanged.connect(
                lambda i, p=pref, e=editor: self.changed(p, e.itemData(i)))
        else:
            editor = QtWidgets.QLineEdit(value)
            editor.editingFinished.connect(
                lambda p=pref, e=editor: self.changed(p, e.text()))
        editor.setToolTip(pref.description)
        if pref.key == PREF.LOOK:
            self.limit_looks(editor)
        return editor

    def limit_looks(self, editor):
        """Host application only means something in a host, so outside
        one it is greyed out, and a pipeline's NXT_EDITOR_LOOK has the
        last word over the preference."""
        index = editor.findData(theme.LOOK_HOST)
        if index >= 0 and not theme.running_host():
            item = editor.model().item(index)
            item.setEnabled(False)
            item.setToolTip('Only in Maya, Blender or Unreal. Chosen there, '
                            'the editor is Modern when it runs on its own.')
            editor.setItemText(index, 'Host application (in a host)')
        asked = os.environ.get(theme.LOOK_ENV_VAR, '').strip().lower()
        if asked in [look for look, _label in theme.LOOK_NAMES]:
            self._filling = True
            editor.setCurrentIndex(editor.findData(asked))
            self._filling = False
            editor.setEnabled(False)
            editor.setToolTip('Set by {} for everyone here.'.format(
                theme.LOOK_ENV_VAR))

    def changed(self, pref, value):
        if self._filling:
            return
        if pref.kind == TEXT and not value.strip():
            value = pref.default
        before = current(pref)
        set_preference(self.main_window, pref, value)
        row = self.rows.get(pref.key)
        if row is not None:
            row.update_reset()
        if (pref.key in (PREF.LOOK, PREF.LOOK_STYLESHEET) and
                value != before and self.main_window is not None):
            # After the box the change came from has finished with it.
            QtCore.QTimer.singleShot(0, self.offer_reopen)

    def offer_reopen(self):
        """Offer to reopen the editor in the look just chosen.

        A look is built into the editor's widgets as they are made, so it
        shows in a new editor. Reopening is that, with the same graphs, and
        no restart of the host the editor runs in.

        :return: the new editor, or None when it was not reopened
        """
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle('Look')
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText('The editor shows its new look when it reopens.')
        box.setInformativeText(
            'Reopen it now, with the graphs you have open? Any unsaved '
            'changes are asked about first.')
        reopen = box.addButton('Reopen Now', QtWidgets.QMessageBox.AcceptRole)
        box.addButton('Later', QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(reopen)
        box.exec_()
        if box.clickedButton() is not reopen:
            return None
        return self.main_window.reopen()

    def show_value(self, pref):
        """Show a preference's value as it is now."""
        editor = self.editors[pref.key]
        value = current(pref)
        self._filling = True
        try:
            if pref.kind == BOOL:
                editor.setChecked(value)
            elif pref.kind in (INT, FLOAT):
                editor.setValue(value)
            elif pref.kind == CHOICE:
                editor.setCurrentIndex(editor.findData(value))
            else:
                editor.setText(value)
        finally:
            self._filling = False
        row = self.rows.get(pref.key)
        if row is not None:
            row.update_reset()

    def reset(self, pref):
        """Put a preference back to its default."""
        set_preference(self.main_window, pref, pref.default)
        self.show_value(pref)

    # Closing -------------------------------------------------------------

    def reject(self):
        """Close, Escape and the window's own close button all come here.
        Environment variables are edited and then applied, so edits not
        applied yet are asked about before they are lost."""
        env_page = self.pages.get(ENV_VARIABLES)
        if env_page is not None and env_page.dirty:
            answer = QtWidgets.QMessageBox.question(
                self, 'Environment Variables',
                'Apply your changes to the environment variables?',
                QtWidgets.QMessageBox.Apply | QtWidgets.QMessageBox.Discard |
                QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Apply)
            if answer == QtWidgets.QMessageBox.Cancel:
                return
            if answer == QtWidgets.QMessageBox.Apply:
                if not env_page.apply():
                    return
            else:
                env_page.load_files()
        super(PreferenceEditor, self).reject()

    # Search --------------------------------------------------------------

    def on_search_edited(self, text):
        if not text.strip():
            # Cleared: the section chosen before comes back straight away.
            self.search_timer.stop()
            self.search_now()
        else:
            self.search_timer.start()

    def search_now(self):
        self.search_timer.stop()
        self.apply_filter(self.filter.text())

    def apply_filter(self, text):
        """Search every section for the words in text.

        What is found is shown together, under each section's title, with
        the words marked, and the sections it is in are left in the list
        to move to. With nothing to search for, the chosen section is shown
        alone again.
        """
        words = text.lower().split()
        if words == self.words:
            return
        if words and not self.words:
            # Where to go back to when the search is cleared.
            self.section_before = self.current_section()
        self.words = words
        # One redraw at the end, rather than one for each row that shows or
        # hides, and only the rows that change are touched.
        self.page.setUpdatesEnabled(False)
        try:
            self._filter_rows(words, text)
        finally:
            self.page.setUpdatesEnabled(True)

    def _filter_rows(self, words, text):
        found = []
        if not words:
            # Back to one section: the results are put away first, so
            # showing every row again does not lay them all out on screen.
            for block in self.blocks.values():
                block.hide()
            for link in self.links.values():
                link.hide()
        for row in self.rows.values():
            hide = not row.matches(words)
            if row.isHidden() != hide:
                row.setHidden(hide)
            if not hide:
                row.mark(words)
        hotkeys_shown = (self.hotkey_list.filter(words)
                         if self.hotkey_list is not None else 0)
        names = self.section_names()
        for index, name in enumerate(names):
            if name in self.links:
                link = self.links[name]
                shown = bool(words) and link.matches(words)
                link.mark(words)
                link.setVisible(shown)
            else:
                if name == HOTKEYS:
                    shown = bool(hotkeys_shown)
                else:
                    shown = any(not row.isHidden()
                                for row in self.rows.values()
                                if row.section == name)
                self.blocks[name].setVisible(shown and bool(words))
            self.section_list.item(index).setHidden(
                bool(words) and not shown)
            if shown:
                found.append(name)
        self.nothing_found.setVisible(bool(words) and not found)
        self.nothing_found.setText('Nothing has "{}" in it.'.format(
            text.strip()))
        if not words:
            for link in self.links.values():
                link.hide()
            before = self.section_before
            if before and before != self.current_section():
                self.select_section(before)
            else:
                self.show_section(self.section_list.currentRow())
            return
        self.stack.setCurrentWidget(self.area)
        self.area.verticalScrollBar().setValue(0)
        if found:
            self.mark_section(found[0])

    def mark_section(self, name):
        """Highlight a section in the list without moving to it."""
        self.section_list.blockSignals(True)
        self.select_section(name)
        self.section_list.blockSignals(False)

    def follow_scroll(self, value):
        """While searching, the list highlights the section whose part of
        what was found is at the top."""
        if not self.words:
            return
        top = None
        for name in self.section_names():
            widget = self.links.get(name) or self.blocks.get(name)
            if widget is None or widget.isHidden():
                continue
            if top is None or widget.y() <= value + 4:
                top = name
        if top and top != self.current_section():
            self.mark_section(top)
