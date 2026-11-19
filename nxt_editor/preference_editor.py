"""Options > Preferences: every preference a user can set, in one table.

Preferences are kept in the user's prefs.json, and many are only set from
a menu toggle somewhere, or not at all, so the only way to find them was
to read the source. This lists them by section with what each does, and
sets them straight away.

A preference with a toggle in a menu is set by triggering that toggle, so
the menu shows it and the editor does whatever the toggle does when it
changes. Others are written to the file, and read from there the next
time they are needed. The AI Assistant, Layer Color View and Environment
Variables have their own dialogs in Options and are not repeated here.
"""
# Builtin
import logging
import os
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

PREF_COL, VALUE_COL, ABOUT_COL = range(3)
KEY_ROLE = QtCore.Qt.UserRole + 1


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


class PreferenceEditor(QtWidgets.QDialog):
    """Every preference a user can set, by section, set as it is changed."""

    def __init__(self, main_window=None, parent=None):
        super(PreferenceEditor, self).__init__(parent or main_window)
        self.main_window = main_window
        self.setWindowTitle('Preferences')
        self.resize(980, 600)
        self.editors = {}  # key: widget
        self._filling = False

        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            'Changes are made straight away. Your preferences are kept in '
            '{}.'.format(user_dir.USER_PREFS_PATH))
        intro.setWordWrap(True)
        intro.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        intro.setStyleSheet(theme.fill('color: {TEXT_DIM};'))
        layout.addWidget(intro)

        self.filter = QtWidgets.QLineEdit()
        self.filter.setPlaceholderText('Filter preferences')
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self.apply_filter)
        layout.addWidget(self.filter)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(['Preference', 'Value', 'What it does'])
        self.tree.setRootIsDecorated(False)
        header = self.tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(PREF_COL,
                                    QtWidgets.QHeaderView.ResizeToContents)
        self.tree.setColumnWidth(VALUE_COL, 200)
        layout.addWidget(self.tree)

        row = QtWidgets.QHBoxLayout()
        self.reset_button = QtWidgets.QPushButton('Reset to Default')
        self.reset_button.setToolTip('Set the selected preference back to '
                                     'what it is before you change it.')
        self.reset_button.clicked.connect(self.reset_selected)
        row.addWidget(self.reset_button)
        row.addStretch(1)
        close = QtWidgets.QPushButton('Close')
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)

        self.fill()

    # Rows ----------------------------------------------------------------

    def fill(self):
        self._filling = True
        self.tree.clear()
        self.editors = {}
        sections = {}
        bold = QtGui.QFont(self.font())
        bold.setBold(True)
        for pref in PREFERENCES:
            section = sections.get(pref.section)
            if section is None:
                section = QtWidgets.QTreeWidgetItem(self.tree,
                                                    [pref.section])
                section.setFont(PREF_COL, bold)
                section.setFlags(QtCore.Qt.ItemIsEnabled)
                section.setFirstColumnSpanned(True)
                sections[pref.section] = section
            item = QtWidgets.QTreeWidgetItem(section, [pref.label, '',
                                                       pref.description])
            item.setData(PREF_COL, KEY_ROLE, pref.key)
            tip = '{}\n\n{} in prefs.json'.format(pref.description, pref.key)
            for col in (PREF_COL, ABOUT_COL):
                item.setToolTip(col, tip)
            item.setForeground(ABOUT_COL, theme.color(theme.TEXT_DIM))
            editor = self.make_editor(pref)
            self.editors[pref.key] = editor
            # Tall enough for its box, which a row is not by itself.
            hint = editor.sizeHint()
            item.setSizeHint(VALUE_COL, QtCore.QSize(hint.width(),
                                                     hint.height() + 4))
            self.tree.setItemWidget(item, VALUE_COL, editor)
        self.tree.expandAll()
        self._filling = False

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
        return editor

    def changed(self, pref, value):
        if self._filling:
            return
        if pref.kind == TEXT and not value.strip():
            value = pref.default
        set_preference(self.main_window, pref, value)

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

    def selected_pref(self):
        item = self.tree.currentItem()
        key = item.data(PREF_COL, KEY_ROLE) if item else None
        for pref in PREFERENCES:
            if pref.key == key:
                return pref
        return None

    def reset_selected(self):
        pref = self.selected_pref()
        if pref is None:
            return
        set_preference(self.main_window, pref, pref.default)
        self.show_value(pref)

    # Filter --------------------------------------------------------------

    def apply_filter(self, text):
        words = text.lower().split()
        for s in range(self.tree.topLevelItemCount()):
            section = self.tree.topLevelItem(s)
            shown = 0
            for r in range(section.childCount()):
                item = section.child(r)
                haystack = ' '.join((section.text(PREF_COL),
                                     item.text(PREF_COL),
                                     item.text(ABOUT_COL),
                                     str(item.data(PREF_COL, KEY_ROLE))
                                     )).lower()
                hide = not all(word in haystack for word in words)
                item.setHidden(hide)
                shown += not hide
            section.setHidden(not shown)
