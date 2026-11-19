# Builtin
import builtins
import importlib
import io
import keyword
import logging
import os
import re
import sys
import threading
from collections import OrderedDict
from functools import partial

# External
from Qt import QtWidgets
from Qt import QtGui
from Qt import QtCore

# Internal
from nxt_editor.dockwidgets.dock_widget_base import DockWidgetBase
from nxt_editor.pixmap_button import PixmapButton
from nxt_editor.label_edit import LabelEdit
from nxt_editor import colors, theme, user_dir
from nxt_editor.decorator_widgets import OpinionDots
from nxt import DATA_STATE, nxt_path, tokens
from nxt.tokens import TOKENTYPE
from nxt.nxt_node import INTERNAL_ATTRS
from nxt_editor.dockwidgets import syntax
from nxt_editor.dockwidgets import code_completion
from nxt_editor.dockwidgets.code_overlays import (FindOverlay,
                                                  GotoLineOverlay)
from nxt_editor.constants import FONTS, points_to_px
import nxt_editor

logger = logging.getLogger(nxt_editor.LOGGER_NAME)


class CodeEditor(DockWidgetBase):

    def __init__(self, title='Code Editor', parent=None, minimum_width=500):
        super(CodeEditor, self).__init__(title=title, parent=parent,
                                         minimum_width=minimum_width)
        self.setObjectName('Code Editor')
        self.main_window = parent
        self.ce_actions = self.main_window.code_editor_actions
        self.exec_actions = self.main_window.execute_actions
        # local attributes
        self.editing_active = False
        self.code_is_local = False
        self.locked = False
        self.node_path = None
        self.node_name = ''
        self.actual_display_state = ''
        self.cached_code_lines = []
        self.cached_code = ''
        self.code_layer_colors = []
        # main layout
        self.main = QtWidgets.QWidget(parent=self)
        self.setWidget(self.main)

        self.layout = QtWidgets.QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.main.setLayout(self.layout)

        self.background_frame = QtWidgets.QFrame(self)
        self.background_frame.setStyleSheet(theme.fill('background-color: {RAISED}; border-radius: 0px;'))
        self.layout.addWidget(self.background_frame)

        # details
        self.details_frame = QtWidgets.QFrame(self)
        self.details_frame.setStyleSheet(theme.fill('background-color: {RAISED}; border-radius: 0px;'))
        self.topLevelChanged.connect(self.display_details)
        self.dockLocationChanged.connect(self.display_details)
        self.layout.addWidget(self.details_frame)

        self.details_layout = QtWidgets.QVBoxLayout()
        self.details_layout.setContentsMargins(0, 0, 0, 0)
        self.details_layout.setSpacing(0)
        self.details_frame.setLayout(self.details_layout)

        # name
        self.name_layout = QtWidgets.QHBoxLayout()
        self.name_layout.setContentsMargins(0, 0, 0, 0)
        self.name_layout.setAlignment(QtCore.Qt.AlignLeft)
        self.details_layout.addLayout(self.name_layout)

        self.name_label = LabelEdit(parent=self.details_frame)
        self.name_label.setFont(FONTS.default_font(14))
        self.name_label.nameChangeRequested.connect(self.edit_name)
        self.name_layout.addWidget(self.name_label, 0, QtCore.Qt.AlignLeft)

        self.name_edit_button = PixmapButton(pixmap=':icons/icons/pencil.png',
                                             pixmap_hover=':icons/icons/pencil_hover.png',
                                             pixmap_pressed=':icons/icons/pencil.png',
                                             size=16,
                                             parent=self.details_frame,
                                             resize_signal=self.main_window.font_size_changed)
        self.name_edit_button.pressed.connect(self.name_label.edit_text)
        self.name_layout.addWidget(self.name_edit_button, 0, QtCore.Qt.AlignLeft)

        self.path_label = QtWidgets.QLabel(parent=self.details_frame)
        self.path_label.setFont(FONTS.monospace_font(8))
        self.path_label.setStyleSheet('color: grey')
        self.details_layout.addWidget(self.path_label)

        # code editor
        self.code_frame = QtWidgets.QFrame(self)
        self.code_frame.setStyleSheet(theme.fill('background-color: {RAISED}; border-radius: 0px'))
        self.layout.addWidget(self.code_frame)

        self.frame_layout = QtWidgets.QVBoxLayout()
        self.frame_layout.setContentsMargins(4, 0, 4, 0)
        self.frame_layout.setSpacing(0)
        self.code_frame.setLayout(self.frame_layout)

        self.code_widget = QtWidgets.QWidget(self)
        # Nothing painted here, so the strip the editor gives up when it
        # shrinks kept whatever was drawn there last, which is how dragging
        # the splitter smeared the editor's border across the top.
        self.code_widget.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.code_widget.setStyleSheet(theme.fill('background-color: {RAISED};'))
        self.frame_layout.addWidget(self.code_widget)

        self.code_layout = QtWidgets.QVBoxLayout()
        self.code_layout.setContentsMargins(0, 0, 0, 0)
        self.code_widget.setLayout(self.code_layout)

        self.syntax_highlighter = syntax.PythonHighlighter
        self.editor = NxtCodeEditor(syntax_highlighter=self.syntax_highlighter, parent=self)
        self.editor.setObjectName('Code Editor')
        self.editor.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard)
        self.editor.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.editor.cancel.connect(self.exit_editing)
        self.editor.accept.connect(self.accept_edit)
        self.code_layout.addWidget(self.editor)

        # Panels that float over the code rather than taking a strip of the
        # dock, so opening one never reflows what is being read. Children of
        # the editor, so they follow it wherever the dock ends up.
        self.find_widget = FindOverlay(self.editor, ce_widget=self)
        self.goto_widget = GotoLineOverlay(self.editor, ce_widget=self)
        self.editor.find_widget = self.find_widget
        self.editor.goto_widget = self.goto_widget
        self.editor.textChanged.connect(
            self.find_widget.on_editor_text_changed)

        self.viewport = self.editor.viewport()

        # overlay widget for dimming
        self.overlay_widget = OverlayWidget(self.editor)

        # buttons layout
        self.buttons_layout = QtWidgets.QGridLayout()
        self.buttons_layout.setContentsMargins(10, 0, 10, 10)
        self.buttons_layout.setSpacing(8)
        self.buttons_layout.setColumnStretch(4, 1)
        self.code_layout.addLayout(self.buttons_layout)

        # copy resolved code button
        self.copy_resolved_button = PixmapButton(
            pixmap=':icons/icons/copy_resolved_12.png',
            pixmap_hover=':icons/icons/copy_resolved_hover_12.png',
            pixmap_pressed=':icons/icons/copy_resolved_hover_12.png',
            size=12,
            parent=self.code_frame,
            resize_signal=self.main_window.font_size_changed)
        self.copy_resolved_button.setToolTip('Copy Resolved')
        self.copy_resolved_button.setStyleSheet(theme.fill('QToolTip {color: white; border: 1px solid {BORDER}}'))
        self.copy_resolved_button.clicked.connect(self.copy_resolved)
        self.buttons_layout.addWidget(self.copy_resolved_button, 0, 0)

        # TODO: Add copy cached button?

        # display format characters
        self.format_button = PixmapButton(
            pixmap=':icons/icons/paragraph_off_12.png',
            pixmap_hover=':icons/icons/paragraph_off_hover_12.png',
            pixmap_pressed=':icons/icons/paragraph_on_hover_12.png',
            pixmap_checked=':icons/icons/paragraph_on_12.png',
            pixmap_checked_hover=':icons/icons/paragraph_on_hover_12.png',
            pixmap_checked_pressed=':icons/icons/paragraph_off_hover_12.png',
            checkable=True,
            size=12,
            parent=self.code_frame,
            resize_signal=self.main_window.font_size_changed)
        self.format_button.setToolTip('Show Non-Printing Characters')
        self.format_button.setStyleSheet(theme.fill('QToolTip {color: white; border: 1px solid {BORDER}}'))
        self.format_button.toggled.connect(lambda: self.edit_format_characters(not self.editor.format_characters_on))
        self.buttons_layout.addWidget(self.format_button, 0, 3)

        self.code_opinions = OpinionDots(self, 'Code Opinions')
        self.buttons_layout.addWidget(self.code_opinions, 0, 4,
                                      QtCore.Qt.AlignRight)

        # accept button
        self.accept_button = PixmapButton(pixmap=':icons/icons/accept.png',
                                          pixmap_hover=':icons/icons/accept_hover.png',
                                          pixmap_pressed=':icons/icons/accept_pressed.png',
                                          size=12,
                                          parent=self.code_frame,
                                          resize_signal=self.main_window.font_size_changed)
        self.accept_button.setToolTip('Accept Edit')
        self.accept_button.setStyleSheet(theme.fill('QToolTip {color: white; border: 1px solid {BORDER}}'))
        self.accept_button.clicked.connect(self.accept_edit)
        self.buttons_layout.addWidget(self.accept_button, 0, 5,
                                      QtCore.Qt.AlignRight)

        # cancel button
        self.cancel_button = PixmapButton(pixmap=':icons/icons/cancel.png',
                                          pixmap_hover=':icons/icons/cancel_hover.png',
                                          pixmap_pressed=':icons/icons/cancel_pressed.png',
                                          size=12,
                                          parent=self.code_frame,
                                          resize_signal=self.main_window.font_size_changed)
        self.cancel_button.setToolTip('Cancel Edit')
        self.cancel_button.setStyleSheet(theme.fill('QToolTip {color: white; border: 1px solid {BORDER}}'))
        self.cancel_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.cancel_button.clicked.connect(self.exit_editing)
        self.buttons_layout.addWidget(self.cancel_button, 0, 6,
                                      QtCore.Qt.AlignRight)

        # remove code button
        self.revert_code_button = PixmapButton(
            pixmap=':icons/icons/delete.png',
            pixmap_hover=':icons/icons/delete_hover.png',
            pixmap_pressed=':icons/icons/delete_pressed.png',
            size=12,
            parent=self.code_frame,
            resize_signal=self.main_window.font_size_changed)
        self.revert_code_button.setToolTip('Remove Compute')
        self.revert_code_button.setStyleSheet(theme.fill('QToolTip {color: white; border: 1px solid {BORDER}}'))
        self.revert_code_button.clicked.connect(self.revert_code)
        self.buttons_layout.addWidget(self.revert_code_button, 0, 7,
                                      QtCore.Qt.AlignRight)
        if not self.main_window.in_startup:
            # default state
            self.update_border_color()
            self.update_format_characters()
            self.display_details()
            self.display_editor()

    def update_background(self):
        if self.editor.isReadOnly():
            style = theme.fill('''
            background-color: {BASE};
            background-image: url(:icons/icons/BDiagPattern.png);
            background-repeat: repeat-xy;
            background-attachment: fixed;''')
        else:
            style = theme.fill('background-color: {BASE};')
        self.code_widget.setStyleSheet(style)

    def sync_overlay_geometry(self):
        """Keep the overlay sitting exactly on the editor.

        It is a child of the editor and paints with no background of its
        own, so any moment where it is larger than the editor leaves what
        it drew behind. Driven only from this dock's resize it lagged the
        editor for a frame on every step of a splitter drag, which is what
        smeared the border across the top.
        """
        rect = self.editor.rect().marginsRemoved(QtCore.QMargins(3, 2, 2, 2))
        if self.overlay_widget.geometry() != rect:
            self.overlay_widget.setGeometry(rect)
            self.overlay_widget.update()

    def resizeEvent(self, event):
        self.sync_overlay_geometry()
        # The editor draws its border with a stylesheet, and the strip it
        # gives up when it shrinks belongs to this frame, which has nothing
        # to paint there unless asked.
        self.code_frame.update()
        return super(CodeEditor, self).resizeEvent(event)

    def set_stage_model(self, stage):
        super(CodeEditor, self).set_stage_model(stage_model=stage)
        if self.stage_model:
            self.set_represented_node()
            self.editor.show()

    def set_stage_model_connections(self, model, connect):
        self.accept_edit()
        self.model_signal_connections = [
            (model.node_focus_changed, self.accept_edit),
            (model.node_focus_changed, self.set_represented_node),
            (model.layer_lock_changed, self.handle_lock_changed),
            (model.nodes_changed, self.update_editor),
            (model.attrs_changed, self.update_editor),
            (model.data_state_changed, self.update_editor),
            (model.comp_layer_changed, self.update_editor),
            (model.target_layer_changed, self.set_represented_node),
            (model.attrs_changed, self.set_represented_node),
            (model.about_to_execute, self.accept_edit),
            (model.about_to_rename, self.accept_edit)
        ]
        super(CodeEditor, self).set_stage_model_connections(model, connect)

    def on_stage_model_destroyed(self):
        super(CodeEditor, self).on_stage_model_destroyed()
        self.editor.clearFocus()
        self.editor.hide()
        self.update_background()

    def handle_lock_changed(self, *args):
        # TODO: Make it a user pref to lock the code editor when node is locked?
        # self.locked = self.stage_model.get_node_locked(self.node_path)
        self.name_label.setReadOnly(self.locked)
        # Enable/Disable
        self.accept_button.setEnabled(not self.locked)
        self.cancel_button.setEnabled(not self.locked)
        self.revert_code_button.setEnabled(not self.locked)
        keep_active = [self.ce_actions.copy_resolved_action]
        for action in self.ce_actions.actions() + self.exec_actions.actions():
            if action in keep_active:
                continue
            action.setEnabled(not self.locked)

    def set_represented_node(self):
        previous_path = self.node_path
        self.node_path = self.stage_model.node_focus
        if not self.node_path:
            self.clear()
            return

        self.node_name = nxt_path.node_name_from_node_path(self.node_path)
        if not self.node_name:
            self.clear()
        else:
            # Changing the target layer, accepting an edit or editing an
            # attribute all land here with the same node still showing.
            # Only a different node starts at the top; the same one stays
            # where it was scrolled to.
            if self.node_path != previous_path:
                self.editor.verticalScrollBar().setValue(0)
            self.update_editor()
            self.update_border_color()
            self.update_format_characters()
            self.update_name()

        self.display_editor()
        self.display_details()
        self.handle_lock_changed()

    def copy_resolved(self):
        if not self.stage_model:
            return
        raw_code = self.editor.toPlainText()
        resolved_code = self.stage_model.resolve(self.node_path, raw_code)
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(resolved_code)

    def display_editor(self):
        if not self.node_path:
            self.code_frame.hide()
        elif self.code_frame.isHidden():
            self.code_frame.show()
            self.sync_overlay_geometry()

    def display_details(self):
        if self.isTopLevel() and self.node_path:
            self.details_frame.show()
        else:
            self.details_frame.hide()

    def update_editor(self, node_list=()):
        try:
            iter(node_list)
        except TypeError:
            node_list = ()
        safe_node_paths = []
        for attr_path in node_list:  # Because the attrs changed signal
            safe_node_paths += [nxt_path.node_path_from_attr_path(attr_path)]
        if node_list and self.node_path not in safe_node_paths:
            return
        code_layers = self.stage_model.get_layers_with_opinion(self.node_path,
                                                               INTERNAL_ATTRS.COMPUTE)
        self.code_layer_colors = self.stage_model.get_layer_colors(code_layers)
        self.setEnabled(False)
        self.editor.changed_lines = []
        self.cached_code_lines = []
        self.cached_code = ''
        self.code_opinions.layer_colors = self.code_layer_colors
        if self.stage_model:
            self.setEnabled(True)
            if self.editing_active:
                return
            if not self.stage_model.node_exists(self.node_path):
                self.editor.clear()
                return
            self.update_code_is_local()
            # TODO: We should break the code update out into its own function
            #  for faster updates. And avoid that early exit check at the top.
            get_code = self.stage_model.get_node_code_string
            code_string = get_code(self.node_path,
                                   self.stage_model.data_state,
                                   self.stage_model.comp_layer)
            cached_state = self.stage_model.data_state == DATA_STATE.CACHED
            self.actual_display_state = DATA_STATE.RAW
            if code_string and cached_state:
                self.actual_display_state = DATA_STATE.CACHED
            elif not code_string and cached_state:
                self.actual_display_state = DATA_STATE.RAW
                code_string = get_code(self.node_path, DATA_STATE.RAW,
                                       self.stage_model.comp_layer)
            else:
                self.actual_display_state = self.stage_model.data_state
            if self.editing_active:
                self.overlay_widget.hide()
            elif self.code_is_local:
                self.overlay_widget.main_color = None
                self.overlay_widget.show()
            else:
                self.overlay_widget.main_color = self.overlay_widget.ext_color
                self.overlay_widget.show()
            self.overlay_widget.update()
            self.editor.verticalScrollBar().blockSignals(True)
            self.cached_code_lines = code_string.split('\n')
            self.cached_code = code_string
            self.editor.setPlainText(code_string)
            self.editor.verticalScrollBar().blockSignals(False)
            prev_v_scroll = self.editor.prev_v_scroll_value
            prev_h_scroll = self.editor.prev_h_scroll_value
            self.editor.verticalScrollBar().setValue(prev_v_scroll)
            self.editor.horizontalScrollBar().setValue(prev_h_scroll)

    def update_border_color(self):
        color = None
        if self.stage_model and self.node_path:
            source = self.stage_model.get_node_code_source(self.node_path)
            if source:
                s_layer = self.stage_model.get_node_source_layer(self.node_path)
                color = self.stage_model.get_layer_color(s_layer)
        self.editor.update_border(color)

    def edit_name(self, new_name):
        self.stage_model.set_node_name(self.node_path, new_name,
                                       self.stage_model.target_layer)
        self.node_name = nxt_path.node_name_from_node_path(self.node_path)
        self.update_name()

    def update_name(self):
        self.name_label.setText(self.node_name)
        self.path_label.setText(self.node_path)

    def clear(self):
        # clear data
        self.node_path = None
        self.node_name = str()
        self.editor.changed_lines = []
        self.cached_code_lines = []
        self.cached_code = ''
        self.code_layer_colors = []

        # update
        self.update_editor()
        self.update_name()
        self.display_editor()

    def update_code_is_local(self):
        """Determine if the node at self.node_path has a local compute and
        update the UI accordingly.
        """
        if not self.node_path:
            return
        if not self.stage_model:
            return
        target_layer = self.stage_model.target_layer
        comp_layer = self.stage_model.comp_layer
        exists = self.stage_model.node_exists(self.node_path, target_layer)
        local_code = self.stage_model.node_has_code(self.node_path,
                                                    target_layer)
        comp_code = self.stage_model.node_has_code(self.node_path, comp_layer)
        is_local = False
        if local_code or not comp_code and not local_code:
            is_local = exists
        # lock the editor
        self.editor.current_line_highlight = not is_local
        self.overlay_widget.main_color = self.overlay_widget.base_color
        self.update_background()
        self.code_is_local = is_local

    def localize_code(self):
        self.stage_model.localize_node_code(self.node_path)
        self.update_editor()

    def revert_code(self):
        if not self.stage_model:
            return
        self.exit_editing()
        self.stage_model.revert_node_code(self.node_path,
                                             self.stage_model.target_layer)
        self.update_editor()
        self.editor.clearFocus()

    def update_format_characters(self):
        value = self.editor.format_characters_on
        self.format_button.setChecked(value)

    def edit_format_characters(self, value=None):
        value = value if value is not None else self.format_button.isChecked()
        self.editor.display_format_characters(value)

    def enter_editing(self):
        # prevent re-activating when the mouse is clicked inside the editor
        if self.editing_active or self.locked:
            return
        self.cached_code = self.editor.toPlainText()
        self.cached_code_lines = self.cached_code.split('\n')
        self.editor.setReadOnly(False)
        self.overlay_widget.hide()
        self.update_background()
        # set the editor text to the unresolved compute string value
        comp_layer = self.stage_model.comp_layer
        code = self.stage_model.get_node_code_string(self.node_path,
                                                        DATA_STATE.RAW,
                                                        comp_layer)
        self.editor.verticalScrollBar().blockSignals(True)
        self.cached_code_lines = code.split('\n')
        self.cached_code = code
        self.editor.setPlainText(code)
        self.editor.verticalScrollBar().blockSignals(False)
        self.editor.verticalScrollBar().setValue(self.editor.prev_v_scroll_value)
        self.editing_active = True
        self.find_widget.update_replace_enabled()

    def exit_editing(self):
        self.editor.setReadOnly(True)
        self.editing_active = False
        self.editor.hide_completions()
        self.find_widget.update_replace_enabled()
        self.cached_code_lines = []
        self.cached_code = ''
        self.set_represented_node()
        self.editor.clearFocus()
        self.update_background()

    def accept_edit(self):
        # prevent attempts to accept edits if the editor isn't active
        if not self.editing_active:
            return

        # if nothing was changed do nothing
        comp_layer = self.stage_model.comp_layer
        raw = self.stage_model.get_node_code_string(self.node_path,
                                                       DATA_STATE.RAW,
                                                       comp_layer)
        resolved = self.stage_model.get_node_code_string(self.node_path,
                                                            DATA_STATE.RESOLVED,
                                                            comp_layer)
        current_text = str(self.editor.toPlainText().encode())
        if current_text in [raw, resolved]:
            self.exit_editing()
            return

        # set compute lines on the model
        code_lines = self.editor.get_lines()
        self.stage_model.set_node_code_lines(self.node_path, code_lines,
                                                self.stage_model.target_layer)

        self.exit_editing()


class JediAnswer(QtCore.QObject):
    """Carries word from jedi's worker thread back to the editor's.

    Emitted on the worker, it is delivered on the thread this object lives
    on, so the editor only ever touches its widgets from its own thread.
    """
    answered = QtCore.Signal(object)


class NxtCodeEditor(QtWidgets.QPlainTextEdit):

    """NxtCodeEditor inherited from QPlainTextEdit providing:

        numberBar - set by display_line_numbers flag equals True
        curent line highligthing - set by HIGHLIGHT_CURRENT_LINE flag equals True
        setting up QSyntaxHighlighter

    references:
        https://john.nachtimwald.com/2009/08/19/better-qplaintextedit-with-line-numbers/
        http://doc.qt.io/qt-5/qtwidgets-widgets-codeeditor-example.html
    """

    cancel = QtCore.Signal()
    accept = QtCore.Signal()

    # Opening char -> closing char inserted automatically while editing
    AUTO_PAIRS = {'(': ')', '[': ']', '{': '}', '"': '"', "'": "'"}

    def __init__(self, show_line_numbers=True, highlight_current_line=True,
                 syntax_highlighter=None, indent='    ',
                 comment_character='#', parent=None):
        """
        :param show_line_numbers: switch on/off the presence of the lines number bar (True)
        :type show_line_numbers: bool

        :param highlight_current_line: switch on/off the current line highlighting (True)
        :type highlight_current_line: bool

        :param syntax_highlighter: QSyntaxHighlighter object
        :type syntax_highlighter: QSyntaxHighlighter | PythonHighlighter
        """
        super(NxtCodeEditor, self).__init__(parent=parent)
        self.setReadOnly(True)
        self.setAcceptDrops(True)
        # local attributes
        self.ce_widget = parent
        self.stage_model = parent.stage_model
        self.ce_actions = parent.ce_actions
        # Mapping to hold onto the enabled state of actions while editing code
        self.action_states = {}
        self.format_characters_on = False
        self.standard_menu = None
        # Set by the CodeEditor dock once the overlays exist.
        self.find_widget = None
        self.goto_widget = None
        # Highlights are kept as named layers and recombined, because
        # setExtraSelections replaces the lot. Painted in this order, so
        # later layers sit on top of earlier ones.
        self.extra_selection_order = ('current_line', 'occurrences',
                                      'find_matches', 'find_current',
                                      'brackets')
        self.extra_selection_layers = OrderedDict()
        self.completion_words = None
        # The prefix the open list was built for, so typing more of the
        # same name only filters it. None when it has to be built again.
        self.completion_base = None
        self.completion_width = 0
        # What the compute's import lines ask for, kept while they stay the
        # same, since every key changes the text. See imported_modules.
        self.imports_key = None
        self.imports_found = None
        self.prev_v_scroll_value = 0
        self.prev_h_scroll_value = 0
        self.changed_lines = []
        self.textChanged.connect(self.get_changed_lines)

        # editor attributes
        self.comment_character = comment_character
        self.begin_comment_str = comment_character + ' '
        self.comment_character_len = len(comment_character)
        self.indent = indent
        self.indent_len = len(indent)
        # ACTIONS
        self.addActions(self.ce_actions.actions())

        self.ce_actions.indent_line.triggered.connect(self.indent_code)
        self.ce_actions.unindent_line.triggered.connect(self.unindent_code)
        self.ce_actions.new_line.triggered.connect(self.new_line)
        self.ce_actions.comment_line.triggered.connect(self.comment_code)
        self.ce_actions.font_bigger.triggered.connect(self.increase_font_size)
        self.ce_actions.font_smaller.triggered.connect(self.decrease_font_size)
        self.ce_actions.font_size_revert.triggered.connect(self.reset_font_size)
        # find and replace
        self.ce_actions.find_action.triggered.connect(self.open_find)
        self.ce_actions.replace_action.triggered.connect(self.open_replace)
        self.ce_actions.find_next_action.triggered.connect(self.find_next)
        self.ce_actions.find_prev_action.triggered.connect(self.find_previous)
        # navigation
        self.ce_actions.goto_line_action.triggered.connect(self.goto_line)
        # line editing
        self.ce_actions.duplicate_line.triggered.connect(self.duplicate_lines)
        self.ce_actions.move_line_up.triggered.connect(partial(self.move_lines,
                                                               -1))
        self.ce_actions.move_line_down.triggered.connect(partial(self.move_lines,
                                                                 1))
        self.ce_actions.delete_line.triggered.connect(self.delete_lines)
        self.ce_actions.expand_selection.triggered.connect(self.expand_selection)
        # completion
        func = partial(self.update_completions, True)
        self.ce_actions.complete_action.triggered.connect(func)
        self.run_line_local_act = self.ce_actions.run_line_local_action
        self.run_line_local_act.triggered.connect(partial(self.exec_selection,
                                                          False))
        self.run_line_global_act = self.ce_actions.run_line_global_action
        self.run_line_global_act.triggered.connect(partial(self.exec_selection,
                                                           True))
        # copy resolved
        self.copy_resolved_action = self.ce_actions.copy_resolved_action
        func = self.ce_widget.copy_resolved
        self.copy_resolved_action.triggered.connect(func)
        # localize code
        self.localize_code_action = self.ce_actions.localize_code_action
        func = self.ce_widget.localize_code
        self.localize_code_action.triggered.connect(func)
        # revert code
        self.revert_code_action = self.ce_actions.revert_code_action
        func = self.ce_widget.revert_code
        self.revert_code_action.triggered.connect(func)

        # accept edit
        self.accept_edit_action = self.ce_actions.accept_edit_action
        self.accept_edit_action.triggered.connect(self.ce_widget.accept_edit)
        # reject edit
        self.cancel_edit_action = self.ce_actions.cancel_edit_action
        self.cancel_edit_action.triggered.connect(self.ce_widget.exit_editing)

        # editor settings
        self.setCursor(QtCore.Qt.IBeamCursor)
        self.setStyleSheet('border-radius: 11px')
        self.setFocusPolicy(QtCore.Qt.ClickFocus)

        # font settings
        self.font_size = FONTS.DEFAULT_SIZE
        self.setFont(FONTS.monospace_font(self.font_size))
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)

        # display settings
        self.display_format_characters(False)
        self.display_line_numbers = show_line_numbers

        # line numbers
        if show_line_numbers:
            self.layout = QtWidgets.QVBoxLayout()
            self.layout.setContentsMargins(0, 0, 0, 0)
            self.setLayout(self.layout)

            style = theme.fill('''
                    background-color: {RAISED};
                    border: 1px solid transparent;
                    border-top-left-radius: 8px;
                    border-bottom-left-radius: 8px;
                    border-top-right-radius: 0px;
                    border-bottom-right-radius: 0px;
                    ''')

            self.frame = QtWidgets.QFrame()
            self.frame.setStyleSheet(style)
            self.layout.addWidget(self.frame)

            self.number_bar = NumberBar(editor=self,
                                        color=QtCore.Qt.transparent)
            self.number_bar.width_changed.connect(self.update_width)
            self.frame.setFixedWidth(self.number_bar.get_width())

        # current line highlight settings
        self.current_line_highlight = highlight_current_line
        self.current_line_number = None
        self.current_line_color = QtGui.QColor('#181818')
        self.occurrence_color = QtGui.QColor('#2E4451')
        self.bracket_color = QtGui.QColor('#3F6079')
        self.unmatched_bracket_color = QtGui.QColor('#7A3030')
        self.cursorPositionChanged.connect(self.cursor_moved)

        # completion
        self.completer = QtWidgets.QCompleter([], self)
        self.completer.setWidget(self)
        self.completer.setCompletionMode(QtWidgets.QCompleter.PopupCompletion)
        self.completer.setCaseSensitivity(QtCore.Qt.CaseSensitive)
        self.completer.setMaxVisibleItems(12)
        self.completer.activated.connect(self.insert_completion)
        self.completer.popup().installEventFilter(self)
        # The list opens once typing pauses, so a fast typist is never
        # waiting on it. While it is open, each key only filters it.
        self.completion_timer = QtCore.QTimer(self)
        self.completion_timer.setSingleShot(True)
        self.completion_timer.setInterval(150)
        self.completion_timer.timeout.connect(self.completions_due)
        self.completion_position = None
        # jedi is asked once typing pauses rather than on every key, and
        # on a worker thread, since a fresh question can take seconds.
        self.jedi_timer = QtCore.QTimer(self)
        self.jedi_timer.setSingleShot(True)
        self.jedi_timer.setInterval(300)
        self.jedi_timer.timeout.connect(self.ask_jedi)
        self.jedi_answer = JediAnswer(self)
        self.jedi_answer.answered.connect(self.jedi_answered)
        self.jedi_busy = False
        self.jedi_again = None
        self.jedi_force = False
        # The word list is rebuilt from the document, so it goes stale on
        # every edit. Rebuilding is deferred until a completion is asked for.
        self.textChanged.connect(self.invalidate_completion_words)
        # Setting text does not move the cursor if it was already at the
        # top, so without this a freshly opened node shows no current line
        # highlight until something is clicked.
        self.textChanged.connect(self.cursor_moved)

        # apply syntax highlighting
        self.syntax_highlighter = syntax_highlighter
        self.highlighter = self.syntax_highlighter(self.document())

        # scroll bar memory
        func = self.update_previous_scroll_positions
        self.verticalScrollBar().valueChanged.connect(func)
        self.installEventFilter(self)
        # Needed to swap the cursor while hovering a token with Ctrl held
        self.viewport().setMouseTracking(True)
        self._cursor_before_token = None

        # code folding, see the folding section below
        self.folding = False
        self.document().contentsChange.connect(self.unfold_edited)
        self.cursorPositionChanged.connect(self.unfold_at_cursor)
        self.ce_actions.fold_block_action.triggered.connect(
            self.fold_current)
        self.ce_actions.unfold_block_action.triggered.connect(
            self.unfold_current)
        self.ce_actions.fold_all_action.triggered.connect(self.fold_all)
        self.ce_actions.unfold_all_action.triggered.connect(self.unfold_all)

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasFormat("text/plain") or self.dropped_files(mime):
            event.acceptProposedAction()
            self.setFocus()
            return
        super(NxtCodeEditor, self).dragEnterEvent(event)

    @staticmethod
    def dropped_files(mime):
        """The files, not folders, on this computer that are being dropped.

        :param mime: QMimeData of the drag
        :return: their paths
        :rtype: list
        """
        if not mime.hasUrls():
            return []
        paths = []
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if os.path.isfile(path):
                paths.append(path)
        return paths

    @staticmethod
    def file_drop_text(paths, contents=False):
        """What dropping files into the code writes.

        A ${contents::} token for each file, so the compute reads the file
        when it runs and keeps up with it as it changes. Or, with
        ``contents``, the text in the files as it is now.

        :param paths: the dropped files
        :type paths: list
        :param contents: True to write what is in the files
        :type contents: bool
        :rtype: str
        """
        pieces = []
        for path in paths:
            if not contents:
                path = path.replace(os.path.sep, '/')
                token = tokens.make_token_str(TOKENTYPE.CONTENTS.prefix +
                                              path)
                pieces.append(token)
                continue
            try:
                with io.open(path, 'r', encoding='utf-8',
                             errors='replace') as fp:
                    text = fp.read()
            except (IOError, OSError):
                logger.warning('Could not read {}'.format(path))
                continue
            # The editor's lines end in \n whatever the file used.
            pieces.append(text.replace('\r\n', '\n').replace('\r', '\n'))
        return '\n'.join(pieces)

    def canInsertFromMimeData(self, source):
        # Without this Qt shows files can not be dropped here, since they
        # carry no text of their own.
        if self.dropped_files(source):
            return True
        return super(NxtCodeEditor, self).canInsertFromMimeData(source)

    def dropEvent(self, event):
        """Dropping files writes a ${contents::} token for each where they
        land, or with Ctrl held the text in them. Anything else, such as
        dragged text, drops the usual way.
        """
        paths = self.dropped_files(event.mimeData())
        if not paths or self.isReadOnly():
            super(NxtCodeEditor, self).dropEvent(event)
            return
        # Qt 6 renamed both of these.
        if hasattr(event, 'position'):
            pos = event.position().toPoint()
        else:
            pos = event.pos()
        if hasattr(event, 'modifiers'):
            modifiers = event.modifiers()
        else:
            modifiers = event.keyboardModifiers()
        contents = bool(modifiers & QtCore.Qt.ControlModifier)
        text = self.file_drop_text(paths, contents=contents)
        cursor = self.cursorForPosition(pos)
        cursor.insertText(text)
        self.setTextCursor(cursor)
        event.acceptProposedAction()
        self.setFocus()

    def get_text_changed(self):
        """Check if the text has changed since editing was entered.
        :return: bool
        """
        cached = self.ce_widget.cached_code
        if cached != self.toPlainText():
            return True
        return False

    def get_changed_lines(self):
        """Get list of line number that have changed since editing was entered.
        If there are more lines in the cache than the editor the max line
        number from the cache is added to the list.
        :return: list of ints
        """
        cached = self.ce_widget.cached_code_lines
        changed_lines = []
        if self.get_text_changed():
            active_lines = self.toPlainText().split('\n')
            cached_len = len(cached)
            active_len = len(active_lines)
            line_delta = cached_len - active_len
            i = 0
            offset = 0
            for line in active_lines:
                if i == active_len - 1:
                    if line_delta > 0:
                        offset -= line_delta
                try:
                    cached_line = cached[i-offset]
                except IndexError:
                    cached_line = None
                if cached_line != line:
                    changed_lines += [i]
                    offset += 1
                i += 1
            if i < cached_len:
                changed_lines += [cached_len]
        self.changed_lines = changed_lines
        return changed_lines

    def display_format_characters(self, value):
        option = QtGui.QTextOption()
        option.setWrapMode(QtGui.QTextOption.NoWrap)
        if value:
            option.setFlags(option.flags() |
                            QtGui.QTextOption.ShowTabsAndSpaces |
                            QtGui.QTextOption.ShowLineAndParagraphSeparators)
            self.format_characters_on = True
        else:
            self.format_characters_on = False
        self.document().setDefaultTextOption(option)

    def get_lines(self):
        # Every block, folded away or not. The document's line count only
        # counts the lines on show, so reading by line number would leave
        # folded code out of what is saved.
        lines = []
        block = self.document().firstBlock()
        while block.isValid():
            lines.append(str(block.text()))
            block = block.next()
        return lines

    def setPlainText(self, text):
        # The code is set again on every refresh of the node, entering
        # editing among them. When it is the same code, what was folded
        # stays folded.
        folded = []
        if text == self.toPlainText():
            folded = self.folded_block_numbers()
        super(NxtCodeEditor, self).setPlainText(text)
        document = self.document()
        for number in folded:
            self.fold_block(document.findBlockByNumber(number))

    # -- folding ----------------------------------------------------------
    # Folding hides the lines of an indented block behind the line that
    # opens it. It only hides them from view: they are still in the
    # document, so what is saved and run is the whole code. Nothing about
    # a fold is stored either. A line is folded when it shows and the line
    # after it does not, so the document itself is the only state.

    @staticmethod
    def block_indent(block):
        """How far a line is indented, or None for a blank line, which
        belongs to whichever block is around it."""
        text = block.text().expandtabs(4)
        stripped = text.lstrip()
        if not stripped:
            return None
        return len(text) - len(stripped)

    def fold_end(self, block):
        """The last line of the indented block this line opens.

        :param block: QTextBlock of the opening line
        :return: QTextBlock, or None if the line opens no block
        """
        indent = self.block_indent(block)
        if indent is None:
            return None
        last = None
        following = block.next()
        while following.isValid():
            following_indent = self.block_indent(following)
            if following_indent is not None:
                if following_indent <= indent:
                    break
                # Blank lines after the block stay out of it.
                last = following
            following = following.next()
        return last

    def opens_fold(self, block):
        """Whether the line is followed by lines indented further."""
        indent = self.block_indent(block)
        if indent is None:
            return False
        following = block.next()
        while following.isValid():
            following_indent = self.block_indent(following)
            if following_indent is not None:
                return following_indent > indent
            following = following.next()
        return False

    @staticmethod
    def is_folded(block):
        following = block.next()
        return (block.isVisible() and following.isValid() and
                not following.isVisible())

    def folded_block_numbers(self):
        numbers = []
        block = self.document().firstBlock()
        while block.isValid():
            if self.is_folded(block):
                numbers.append(block.blockNumber())
            block = block.next()
        return numbers

    def set_blocks_visible(self, first, last, visible):
        """Show or hide the lines from first to last, both included."""
        document = self.document()
        block = first
        end = last.blockNumber()
        self.folding = True
        try:
            while block.isValid() and block.blockNumber() <= end:
                block.setVisible(visible)
                block = block.next()
            start = first.position()
            length = last.position() + last.length() - start
            length = min(length, document.characterCount() - start)
            document.markContentsDirty(start, length)
        finally:
            self.folding = False
        self.viewport().update()
        if self.display_line_numbers:
            self.number_bar.update()

    def fold_block(self, block):
        """Fold away the indented block this line opens.

        :return: True if there was one to fold
        :rtype: bool
        """
        if not block.isValid() or not block.isVisible():
            return False
        last = self.fold_end(block)
        if last is None:
            return False
        first = block.next()
        cursor = self.textCursor()
        hidden_start = first.position()
        hidden_end = last.position() + last.length()
        if (hidden_start <= cursor.position() < hidden_end or
                hidden_start <= cursor.anchor() < hidden_end):
            # The cursor would be left in lines that are not on show.
            cursor = QtGui.QTextCursor(block)
            cursor.movePosition(QtGui.QTextCursor.EndOfBlock)
            self.setTextCursor(cursor)
        self.set_blocks_visible(first, last, False)
        return True

    def unfold_block(self, block):
        """Show the lines folded away behind this line.

        :return: True if it was folded
        :rtype: bool
        """
        if not self.is_folded(block):
            return False
        first = block.next()
        last = first
        while last.next().isValid() and not last.next().isVisible():
            last = last.next()
        self.set_blocks_visible(first, last, True)
        return True

    def toggle_fold(self, block):
        if not self.unfold_block(block):
            self.fold_block(block)

    def fold_header(self, block):
        """The line on show that a hidden line is folded behind."""
        while block.isValid() and not block.isVisible():
            block = block.previous()
        return block

    def fold_current(self):
        """Fold the block the cursor is in, or the one its line opens."""
        block = self.textCursor().block()
        if self.opens_fold(block) and not self.is_folded(block):
            self.fold_block(block)
            return
        indent = self.block_indent(block)
        opener = block.previous()
        while opener.isValid():
            opener_indent = self.block_indent(opener)
            if (opener_indent is not None and
                    (indent is None or opener_indent < indent) and
                    self.opens_fold(opener)):
                last = self.fold_end(opener)
                if (last is not None and
                        last.blockNumber() >= block.blockNumber()):
                    self.fold_block(opener)
                    return
                if indent is None:
                    # A blank line past the end of a block is in no block.
                    return
            opener = opener.previous()

    def unfold_current(self):
        self.unfold_block(self.textCursor().block())

    def fold_all(self):
        """Fold every outermost block. The ones inside them go with them."""
        block = self.document().firstBlock()
        while block.isValid():
            if block.isVisible() and self.opens_fold(block):
                last = self.fold_end(block)
                self.fold_block(block)
                block = last.next()
                continue
            block = block.next()

    def unfold_all(self):
        document = self.document()
        self.set_blocks_visible(document.firstBlock(), document.lastBlock(),
                                True)

    def unfold_edited(self, position, removed, added):
        """Show any fold an edit touches.

        Editing the line that opens a fold, or text that lands in or next
        to hidden lines, puts the hidden lines on show rather than leaving
        changes out of sight.
        """
        if self.folding:
            return
        document = self.document()
        edited_first = document.findBlock(position)
        edited_last = document.findBlock(position + added)
        if not edited_last.isValid():
            edited_last = document.lastBlock()
        last = edited_last.blockNumber()
        block = edited_first
        while block.isValid() and block.blockNumber() <= last:
            if not block.isVisible():
                self.unfold_block(self.fold_header(block))
            elif self.is_folded(block):
                # Also catches removing the line that opened a fold, which
                # leaves its hidden lines behind the line before it.
                self.unfold_block(block)
            block = block.next()

    def unfold_at_cursor(self):
        """The cursor never sits in a hidden line: find, go to line and
        the arrow keys can all take it there, so the fold opens."""
        block = self.textCursor().block()
        if not block.isVisible():
            self.unfold_block(self.fold_header(block))

    def paintEvent(self, event):
        super(NxtCodeEditor, self).paintEvent(event)
        self.paint_fold_markers(event)

    def paint_fold_markers(self, event):
        """Draw a small ... box after each line with code folded behind it."""
        block = self.firstVisibleBlock()
        if not block.isValid():
            return
        painter = None
        offset = self.contentOffset()
        bottom = event.rect().bottom()
        metrics = self.fontMetrics()
        while block.isValid():
            geometry = self.blockBoundingGeometry(block).translated(offset)
            if geometry.top() > bottom:
                break
            if block.isVisible() and self.is_folded(block):
                if painter is None:
                    painter = QtGui.QPainter(self.viewport())
                    painter.setRenderHint(QtGui.QPainter.Antialiasing)
                    painter.setFont(self.font())
                line = block.layout().lineAt(0)
                left = (geometry.left() + line.x() +
                        line.naturalTextWidth() +
                        metrics.horizontalAdvance(' '))
                label = '...'
                width = metrics.horizontalAdvance(label) + 8
                rect = QtCore.QRectF(left, geometry.top() + 1, width,
                                     metrics.height() - 2)
                painter.setPen(QtGui.QColor(theme.BORDER_STRONG))
                painter.setBrush(QtGui.QColor(theme.RAISED))
                painter.drawRoundedRect(rect, 3, 3)
                painter.setPen(QtGui.QColor(theme.TEXT_DIM))
                painter.drawText(rect, QtCore.Qt.AlignCenter, label)
            block = block.next()
        if painter is not None:
            painter.end()

    def resizeEvent(self, *e):
        """overload resizeEvent handler"""
        # resize number_bar widget
        if self.display_line_numbers:
            cr = self.contentsRect()
            rec = QtCore.QRect(cr.left(), cr.top(), self.number_bar.get_width(), cr.height())
            self.number_bar.setGeometry(rec)
        for overlay in (self.find_widget, self.goto_widget):
            if overlay is not None:
                overlay.reposition()
        # The dock resizing is not the only way this widget changes size.
        if self.ce_widget is not None:
            self.ce_widget.sync_overlay_geometry()

        QtWidgets.QPlainTextEdit.resizeEvent(self, *e)

    def update_width(self):
        self.frame.setFixedWidth(self.number_bar.get_width())

    def update_border(self, color):
        if self.ce_widget.code_is_local:
            border = 'solid'
            thickness = (2, 2, 2)
        else:
            border = 'dashed'
            thickness = (3.2, 3.2, 3.2)
        qss = code_style_factory(color, border, thickness=thickness)
        self.setStyleSheet(qss)

    # -- highlight layers ---------------------------------------------

    def set_extra_selection_layer(self, name, selections):
        """Replace one named group of highlights and repaint them all.

        setExtraSelections takes the whole list, so the current line, the
        find matches and the bracket match would otherwise each wipe out
        the others.

        :param name: one of self.extra_selection_order
        :type name: str
        :param selections: QTextEdit.ExtraSelection list, may be empty
        :type selections: list
        """
        self.extra_selection_layers[name] = selections or []
        combined = []
        for key in self.extra_selection_order:
            combined += self.extra_selection_layers.get(key, [])
        self.setExtraSelections(combined)

    def cursor_moved(self):
        self.highlight_current_line()
        self.highlight_occurrences()
        self.highlight_brackets()

    def highlight_current_line(self):
        if not self.current_line_highlight:
            self.set_extra_selection_layer('current_line', [])
            return
        self.current_line_number = self.textCursor().blockNumber()
        hi_selection = QtWidgets.QTextEdit.ExtraSelection()
        hi_selection.format.setBackground(self.current_line_color)
        hi_selection.format.setProperty(QtGui.QTextFormat.FullWidthSelection,
                                        True)
        hi_selection.cursor = self.textCursor()
        hi_selection.cursor.clearSelection()
        self.set_extra_selection_layer('current_line', [hi_selection])

    def word_under_cursor(self):
        """The identifier the cursor is inside or touching.

        :return: (word, start position), or ('', -1)
        :rtype: tuple
        """
        cursor = self.textCursor()
        block_text = cursor.block().text()
        column = cursor.positionInBlock()
        start = column
        while start > 0 and (block_text[start - 1].isalnum()
                             or block_text[start - 1] == '_'):
            start -= 1
        end = column
        while end < len(block_text) and (block_text[end].isalnum()
                                         or block_text[end] == '_'):
            end += 1
        if end <= start:
            return '', -1
        return block_text[start:end], cursor.block().position() + start

    def highlight_occurrences(self):
        """Mark every other use of the word the cursor is on."""
        word, _ = self.word_under_cursor()
        if len(word) < 2 or word in keyword.kwlist:
            self.set_extra_selection_layer('occurrences', [])
            return
        document = self.document()
        text = self.toPlainText()
        selections = []
        pattern = r'\b' + re.escape(word) + r'\b'
        for match in re.finditer(pattern, text):
            selection = QtWidgets.QTextEdit.ExtraSelection()
            selection.format.setBackground(self.occurrence_color)
            cursor = QtGui.QTextCursor(document)
            cursor.setPosition(match.start())
            cursor.setPosition(match.end(), QtGui.QTextCursor.KeepAnchor)
            selection.cursor = cursor
            selections.append(selection)
        if len(selections) < 2:
            # The only use is the one being looked at, so there is nothing
            # to point out.
            selections = []
        self.set_extra_selection_layer('occurrences', selections)

    OPENING_BRACKETS = '([{'
    CLOSING_BRACKETS = ')]}'

    def highlight_brackets(self):
        """Mark the bracket beside the cursor and its partner."""
        text = self.toPlainText()
        position = self.textCursor().position()
        found = None
        # Prefer the bracket the cursor sits just after, the way most
        # editors behave, then the one it sits just before.
        for probe in (position - 1, position):
            if 0 <= probe < len(text) and text[probe] in (
                    self.OPENING_BRACKETS + self.CLOSING_BRACKETS):
                found = probe
                break
        if found is None:
            self.set_extra_selection_layer('brackets', [])
            return
        partner = self.match_bracket(text, found)
        positions = [found] if partner is None else [found, partner]
        color = (self.unmatched_bracket_color if partner is None
                 else self.bracket_color)
        document = self.document()
        selections = []
        for pos in positions:
            selection = QtWidgets.QTextEdit.ExtraSelection()
            selection.format.setBackground(color)
            cursor = QtGui.QTextCursor(document)
            cursor.setPosition(pos)
            cursor.setPosition(pos + 1, QtGui.QTextCursor.KeepAnchor)
            selection.cursor = cursor
            selections.append(selection)
        self.set_extra_selection_layer('brackets', selections)

    def match_bracket(self, text, position):
        """Walk out from a bracket to find the one that closes it.

        :param text: the whole document
        :type text: str
        :param position: index of the bracket to match
        :type position: int
        :return: index of the partner, or None if it is unbalanced
        :rtype: int | None
        """
        char = text[position]
        if char in self.OPENING_BRACKETS:
            partner = self.CLOSING_BRACKETS[self.OPENING_BRACKETS.index(char)]
            step, opening, closing = 1, char, partner
        else:
            partner = self.OPENING_BRACKETS[self.CLOSING_BRACKETS.index(char)]
            step, opening, closing = -1, partner, char
        depth = 0
        index = position
        while 0 <= index < len(text):
            if text[index] == opening:
                depth += 1 if step == 1 else -1
            elif text[index] == closing:
                depth -= 1 if step == 1 else -1
            if depth == 0:
                return index
            index += step
        return None

    # -- find and replace ----------------------------------------------

    def open_find(self):
        if self.find_widget:
            self.find_widget.open_find()

    def open_replace(self):
        if self.find_widget:
            self.find_widget.open_find(replace=True)

    def find_next(self):
        if self.find_widget:
            self.find_widget.find_next()

    def find_previous(self):
        if self.find_widget:
            self.find_widget.find_previous()

    # -- navigation -----------------------------------------------------

    def goto_line(self):
        """Drop the line number panel from the top of the editor."""
        if self.goto_widget:
            self.goto_widget.open_goto()

    def expand_selection(self):
        """Grow the selection: word, then line, then everything."""
        cursor = self.textCursor()
        selected = cursor.selectedText()
        if not selected:
            word, start = self.word_under_cursor()
            if word:
                cursor.setPosition(start)
                cursor.setPosition(start + len(word),
                                   QtGui.QTextCursor.KeepAnchor)
                self.setTextCursor(cursor)
                return
        line = cursor.block().text()
        if selected and selected != line:
            cursor.movePosition(QtGui.QTextCursor.StartOfBlock)
            cursor.movePosition(QtGui.QTextCursor.EndOfBlock,
                                QtGui.QTextCursor.KeepAnchor)
            self.setTextCursor(cursor)
            return
        self.selectAll()

    # -- line editing ----------------------------------------------------

    def selected_block_range(self, cursor):
        """First and last block numbers the given cursor covers.

        :param cursor: QTextCursor to measure
        :return: (first, last) block numbers
        :rtype: tuple
        """
        document = self.document()
        first = document.findBlock(cursor.selectionStart()).blockNumber()
        last = document.findBlock(cursor.selectionEnd()).blockNumber()
        return first, last

    def duplicate_lines(self):
        """Copy the selected line(s) in below themselves."""
        if self.isReadOnly():
            return
        cursor = self.textCursor()
        first, last = self.selected_block_range(cursor)
        document = self.document()
        lines = [document.findBlockByNumber(n).text()
                 for n in range(first, last + 1)]
        end_block = document.findBlockByNumber(last)
        edit = QtGui.QTextCursor(document)
        edit.beginEditBlock()
        try:
            edit.setPosition(end_block.position() + end_block.length() - 1)
            edit.insertText('\n' + '\n'.join(lines))
        finally:
            edit.endEditBlock()

    def move_lines(self, direction):
        """Swap the selected line(s) with the line above or below.

        :param direction: -1 for up, 1 for down
        :type direction: int
        """
        if self.isReadOnly():
            return
        cursor = self.textCursor()
        first, last = self.selected_block_range(cursor)
        document = self.document()
        target = first - 1 if direction < 0 else last + 1
        if target < 0 or target >= document.blockCount():
            return
        moving = [document.findBlockByNumber(n).text()
                  for n in range(first, last + 1)]
        neighbour = document.findBlockByNumber(target).text()
        if direction < 0:
            new_lines = moving + [neighbour]
            span_first, span_last = target, last
        else:
            new_lines = [neighbour] + moving
            span_first, span_last = first, target
        column = cursor.positionInBlock()
        start_block = document.findBlockByNumber(span_first)
        end_block = document.findBlockByNumber(span_last)
        edit = QtGui.QTextCursor(document)
        edit.beginEditBlock()
        try:
            edit.setPosition(start_block.position())
            edit.setPosition(end_block.position() + end_block.length() - 1,
                             QtGui.QTextCursor.KeepAnchor)
            edit.insertText('\n'.join(new_lines))
        finally:
            edit.endEditBlock()
        # Follow the lines to where they landed, so the shortcut can be
        # held down to walk a block up or down the compute.
        moved_first = first + direction
        moved_last = last + direction
        new_cursor = QtGui.QTextCursor(document)
        landed = document.findBlockByNumber(moved_first)
        new_cursor.setPosition(landed.position()
                               + min(column, len(landed.text())))
        if moved_last != moved_first:
            end = document.findBlockByNumber(moved_last)
            new_cursor.setPosition(end.position() + len(end.text()),
                                   QtGui.QTextCursor.KeepAnchor)
        self.setTextCursor(new_cursor)

    def delete_lines(self):
        """Remove the selected line(s) entirely."""
        if self.isReadOnly():
            return
        cursor = self.textCursor()
        first, last = self.selected_block_range(cursor)
        document = self.document()
        start_block = document.findBlockByNumber(first)
        end_block = document.findBlockByNumber(last)
        start = start_block.position()
        end = end_block.position() + end_block.length()
        limit = document.characterCount() - 1
        if end > limit:
            # The last line has no trailing newline of its own to remove,
            # so take the one in front of it instead.
            end = limit
            start = max(0, start - 1)
        edit = QtGui.QTextCursor(document)
        edit.beginEditBlock()
        try:
            edit.setPosition(start)
            edit.setPosition(end, QtGui.QTextCursor.KeepAnchor)
            edit.removeSelectedText()
        finally:
            edit.endEditBlock()
        self.setTextCursor(edit)

    # -- completion -------------------------------------------------------

    def invalidate_completion_words(self):
        self.completion_words = None

    # An import line, either shape, capturing the name the compute will
    # actually use: "import os", "import os.path as p", "from os import x".
    IMPORT_RE = re.compile(
        r'^\s*(?:import\s+(?P<mod>[A-Za-z_][\w.]*)'
        r'(?:\s+as\s+(?P<alias>[A-Za-z_]\w*))?'
        r'|from\s+(?P<from>[A-Za-z_][\w.]*)\s+import\s+(?P<names>[^#\n]+))',
        re.MULTILINE)

    def completion_source_enabled(self, action_name):
        """Whether one source of completions is switched on.

        :param action_name: attribute on the code editor's actions
        :type action_name: str
        :rtype: bool
        """
        action = getattr(self.ce_actions, action_name, None)
        return True if action is None else action.isChecked()

    def imported_modules(self):
        """The modules this compute imports, by the name it calls them.

        Only what the compute asks for, and only if it can be imported
        without complaint. Importing runs module level code, so this stays
        with what the compute was going to import anyway when it runs.

        :return: {name used in the code: module}
        :rtype: dict
        """
        source = self.import_source()
        # Every key changes the text, but rarely its import lines, so what
        # they ask for, and what would not import, is kept while they stay
        # the same. The modules themselves are looked up each time, so one
        # reloaded since is the one offered and the old one is not kept.
        key = tuple(line for line in source.splitlines() if 'import' in line)
        if key != self.imports_key:
            self.imports_key = key
            self.imports_found = {'wanted': self.imports_wanted(source),
                                  'failed': set()}
        failed = self.imports_found['failed']
        found = {}
        for local_name, module_name in self.imports_found['wanted']:
            if local_name in found or module_name in failed:
                continue
            module = sys.modules.get(module_name)
            if module is None:
                try:
                    module = importlib.import_module(module_name)
                except Exception:
                    logger.debug('No completions for %s, it would not import'
                                 % module_name)
                    failed.add(module_name)
                    continue
            found[local_name] = module
        return found

    def imports_wanted(self, source):
        """(name used in the code, module name) for each import line."""
        wanted = []
        for match in self.IMPORT_RE.finditer(source):
            module_name = match.group('mod') or match.group('from')
            if not module_name:
                continue
            local_name = match.group('alias') or module_name.split('.')[0]
            if match.group('mod') and not match.group('alias'):
                # "import os.path" binds os, not os.path
                module_name = module_name.split('.')[0]
            wanted.append((local_name, module_name))
        return wanted

    def world_source(self):
        """The world node's code, when this is another node.

        The world node runs first, into the same globals every compute runs
        with, so what it imports every node can use without importing again.
        """
        model = self.ce_widget.stage_model
        node_path = self.ce_widget.node_path
        if not model or not node_path or node_path == nxt_path.WORLD:
            return ''
        try:
            return model.get_node_code_string(nxt_path.WORLD) or ''
        except Exception:
            return ''

    def import_source(self):
        """This compute, after the world node's."""
        world = self.world_source()
        code = self.toPlainText()
        return world + '\n' + code if world else code

    def completion_namespace(self, live=True):
        """Names the compute can use without importing them itself.

        :param live: include STAGE and self as the last build left them.
            jedi is never given those: it would call their __getattr__ and
            read them from wherever it runs, while a build may be using them.
        :return: {name: object}, from each source that is switched on
        :rtype: dict
        """
        namespace = {}
        if self.completion_source_enabled('complete_node_action'):
            model = self.ce_widget.stage_model
            rt_layer = (getattr(model, 'current_rt_layer', None)
                        if live else None)
            namespace.update(code_completion.runtime_namespace(
                rt_layer, self.ce_widget.node_path))
        if self.completion_source_enabled('complete_host_action'):
            namespace.update(code_completion.host_modules())
        if self.completion_source_enabled('complete_modules_action'):
            namespace.update(self.imported_modules())
        return namespace

    def module_completions(self, prefix):
        """Names reachable through a dotted prefix, like os.pa.

        :param prefix: the partial word being typed
        :type prefix: str
        :rtype: list
        """
        if '.' not in prefix or prefix.startswith(tokens.TOKEN_PREFIX):
            return []
        root, _, rest = prefix.partition('.')
        if root in code_completion.LIVE_GLOBALS:
            return self.live_completions(prefix)
        module = self.completion_namespace(live=False).get(root)
        if module is None:
            return []
        walked = root
        # Follow the dots that are already complete, so os.path.jo looks
        # inside os.path rather than os.
        parts = rest.split('.')
        for part in parts[:-1]:
            module = code_completion.attr_for_completion(module, part)
            if module is None:
                return []
            walked += '.' + part
        return ['%s.%s' % (walked, name) for name in dir(module)
                if not name.startswith('_')]

    def live_completions(self, prefix):
        """Names after STAGE. or self., from what the last build left there.

        Read fresh on every key, so a build that has moved on since is what
        completes, and read without running any of the graph's code. Not
        while a node is running, since the build is using these right then.

        :param prefix: the partial word being typed, like STAGE.rig.bu
        :type prefix: str
        :rtype: list
        """
        root, dot, rest = prefix.partition('.')
        if not dot or root not in code_completion.LIVE_GLOBALS:
            return []
        if not self.completion_source_enabled('complete_node_action'):
            return []
        model = self.ce_widget.stage_model
        if getattr(model, '_running_node', False):
            return []
        obj = code_completion.runtime_namespace(
            getattr(model, 'current_rt_layer', None),
            self.ce_widget.node_path).get(root)
        if obj is None:
            return []
        return [root + dot + name
                for name in code_completion.live_completions(obj, rest)]

    @staticmethod
    def node_attr_names(model, node_path):
        """Every attribute a node's compute can use, see
        code_completion.node_attr_names.

        :rtype: list
        """
        return code_completion.node_attr_names(model, node_path)

    def build_completion_words(self):
        """Everything worth offering as a completion for this node.

        Each source can be switched off on its own, because they are not
        equally welcome: python's own names are noise to someone writing
        mostly tokens, and the words already in a long compute are noise
        to everyone.

        :rtype: list
        """
        words = set()
        if self.completion_source_enabled('complete_python_action'):
            words.update(keyword.kwlist)
            words.update(dir(builtins))
        if self.completion_source_enabled('complete_node_action'):
            words.update(code_completion.RUNTIME_GLOBALS)
            model = self.ce_widget.stage_model
            node_path = self.ce_widget.node_path
            if model and node_path:
                try:
                    for name in self.node_attr_names(model, node_path):
                        words.add(name)
                        words.add('self.' + name)
                except Exception:
                    logger.debug('Could not read attrs for completion on '
                                 + str(node_path), exc_info=True)
            # How an attribute is written in a compute, and the token
            # prefixes, as the Property Editor's values offer them too.
            try:
                words.update(code_completion.token_words(model, node_path))
            except Exception:
                logger.debug('Could not read tokens for completion on '
                             + str(node_path), exc_info=True)
                words.update(code_completion.token_words(None, None))
        if self.completion_source_enabled('complete_modules_action'):
            # The bare module names. What is inside them is resolved per
            # prefix, since dir() on everything imported would be huge.
            words.update(self.imported_modules())
        if self.completion_source_enabled('complete_host_action'):
            words.update(code_completion.host_modules())
        if self.completion_source_enabled('complete_document_action'):
            # A name can be in any language: \w is any letter or digit.
            words.update(re.findall(r'[^\W\d]\w{2,}',
                                    self.toPlainText()))
        return sorted(words)

    # What a partial word can be made of. Dots, so self.na completes
    # against attribute names rather than starting over at na. Dollars,
    # braces and colons, because a token is a word too: stopping at the $
    # meant ${fi offered the prefix "fi", which matches no token, which is
    # why only python builtins ever appeared.
    # Slashes too, but only inside a token, where they are a node path:
    # anywhere else a slash is division and starts a new word.
    PREFIX_CHARS = r'[\w.:${}/]*$'

    def completion_prefix(self):
        """The partial word in front of the cursor.

        :rtype: str
        """
        cursor = self.textCursor()
        text = cursor.block().text()[:cursor.positionInBlock()]
        match = re.search(self.PREFIX_CHARS, text)
        prefix = match.group(0) if match else ''
        if not prefix.startswith(tokens.TOKEN_PREFIX):
            prefix = prefix.rpartition('/')[2]
        return prefix

    def token_completions(self, prefix):
        """Node paths inside ${/, and a node's attributes after its dot.

        ${/ offers every node path, and ${/some/node. offers that node's
        attributes as whole tokens.

        :param prefix: the partial word being typed
        :type prefix: str
        :rtype: list
        """
        start = tokens.TOKEN_PREFIX + nxt_path.WORLD
        if (not prefix.startswith(start) or
                not self.completion_source_enabled('complete_node_action')):
            return []
        model = self.ce_widget.stage_model
        if not model:
            return []
        try:
            return code_completion.token_completions(model, prefix)
        except Exception:
            logger.debug('No token completions for ' + prefix, exc_info=True)
            return []

    def jedi_question(self, prefix):
        """Where jedi would be asked, and what its answer depends on.

        Only after a dot, which is where jedi knows something the other
        sources cannot: what a call returns, what a variable holds. Bare
        names come from the sources that can each be switched off.

        Asked at the start of the name being typed, so the answer is every
        name that can go there and typing more of it only filters. The
        answer depends on the code around that point, not on the name.

        :return: (source, line, column, cache key, what goes before each
            name), or None when jedi is not wanted here
        """
        if ('.' not in prefix or prefix.startswith(tokens.TOKEN_PREFIX) or
                not self.completion_source_enabled('complete_jedi_action') or
                not code_completion.JEDI.installed()):
            return None
        cursor = self.textCursor()
        root, dot, name = prefix.rpartition('.')
        position = cursor.position() - len(name)
        text = self.toPlainText()
        source = text[:position] + text[cursor.position():]
        line = cursor.blockNumber() + 1
        column = cursor.positionInBlock() - len(name)
        key = (source, position, self.world_source())
        return source, line, column, key, root + dot

    def jedi_completions(self, prefix, ask=False, fresh=False):
        """What jedi offers for the name being typed.

        :param ask: work it out now if it is not already known, which is
            what pausing or Ctrl+Space does. Otherwise only what is known.
        :param fresh: ask again even if this spot was asked before. Ctrl+Space
            does, so a library reloaded since shows what it has now.
        :rtype: list
        """
        question = self.jedi_question(prefix)
        if question is None:
            return []
        # jedi never sees STAGE or self as the build left them, so what
        # follows them comes from the build instead. That is read fresh on
        # every key and never kept, so a build that moves on is seen.
        live = self.live_completions(prefix)
        source, line, column, key, before = question
        names = None if fresh else code_completion.JEDI.cached(key)
        if names is None:
            if not ask:
                self.jedi_timer.start()
                return live
            names = code_completion.JEDI.complete(
                source, line, column, self.completion_namespace(live=False),
                key, fresh=fresh)
        return live + [before + name for name in names]

    def ask_jedi(self, fresh=False, force=False):
        """Typing paused: ask jedi on a worker thread, and show what it
        says when it answers, if the cursor is still where it was asked.

        :param fresh: ask again even if this spot was asked before
        :param force: show the answer even with auto-complete off, which
            is what Ctrl+Space does
        """
        if self.isReadOnly() or not self.hasFocus():
            return
        question = self.jedi_question(self.completion_prefix())
        if question is None:
            return
        source, line, column, key, _ = question
        if not fresh and code_completion.JEDI.cached(key) is not None:
            return
        if self.jedi_busy:
            # One at a time. When this one answers, ask about wherever the
            # cursor is then.
            self.jedi_again = (fresh, force)
            return
        self.jedi_busy = True
        self.jedi_force = force
        # The names are gathered here, on the main thread; jedi only reads
        # them on the worker. STAGE and self are left out, see
        # completion_namespace.
        namespace = self.completion_namespace(live=False)
        answer = self.jedi_answer

        def work():
            try:
                code_completion.JEDI.complete(source, line, column,
                                              namespace, key, fresh=fresh)
            finally:
                try:
                    answer.answered.emit(key)
                except RuntimeError:
                    # The editor closed while jedi was thinking.
                    pass

        threading.Thread(target=work, name='nxt-jedi', daemon=True).start()

    def jedi_answered(self, key):
        """jedi has an answer: show it if it is still about this spot."""
        self.jedi_busy = False
        force = self.jedi_force
        again, self.jedi_again = self.jedi_again, None
        question = self.jedi_question(self.completion_prefix())
        if question is not None and question[3] == key:
            if not self.isReadOnly() and self.hasFocus():
                self.update_completions(force=force, from_jedi=True)
        elif again is not None:
            self.ask_jedi(*again)

    def update_completions(self, force=False, from_jedi=False):
        """Offer completions for the word being typed.

        While the list is open and the same name is still being typed, the
        list is only filtered, which is what keeps typing quick. It is
        built again when the part before the last dot changes.

        :param force: show them even when the prefix is short or the
            auto-complete preference is off, which is what Ctrl+Space does.
            It also asks jedi again, in the background.
        :type force: bool
        :param from_jedi: jedi has just answered, so the list is built again
            with what it said, and jedi is not asked again
        :type from_jedi: bool
        """
        self.completion_timer.stop()
        if self.isReadOnly():
            self.hide_completions()
            return
        auto_on = self.ce_actions.autocomplete_action.isChecked()
        if not force and not auto_on:
            self.hide_completions()
            return
        prefix = self.completion_prefix()
        if not force and len(prefix) < 2:
            self.hide_completions()
            return
        if not force and not from_jedi and self.can_filter(prefix):
            self.show_completions(prefix)
            return
        if force and not from_jedi:
            # Ctrl+Space is how a module imported since is picked up.
            self.imports_key = None
        if self.completion_words is None:
            self.completion_words = self.build_completion_words()
        # Module contents, node paths and what jedi says depend on what is
        # being typed, so they are worked out per prefix rather than kept in
        # the cached list. jedi only adds what it already knows here; a new
        # question goes to the worker and the list is built again when it
        # answers.
        words = (self.completion_words + self.module_completions(prefix)
                 + self.token_completions(prefix)
                 + self.jedi_completions(prefix))
        if force and not from_jedi:
            self.ask_jedi(fresh=True, force=True)
        model = QtCore.QStringListModel(sorted(set(words)), self.completer)
        self.completer.setModel(model)
        self.completion_base = prefix
        self.completion_width = 0
        self.show_completions(prefix)

    def can_filter(self, prefix):
        """Whether the open list still holds every answer for prefix.

        It does while more of the same name is typed: the list was built
        for the start of it, and what comes before the last dot decides
        what is in it.
        """
        base = self.completion_base
        return (base is not None and self.completer.popup().isVisible()
                and prefix.startswith(base)
                and prefix.rpartition('.')[0] == base.rpartition('.')[0])

    def show_completions(self, prefix):
        """Filter the list to prefix and put it up at the cursor."""
        self.completer.setCompletionPrefix(prefix)
        if not self.completer.completionCount():
            self.hide_completions()
            return
        if (self.completer.completionCount() == 1
                and self.completer.currentCompletion() == prefix):
            # Already typed out in full, so there is nothing to offer.
            self.hide_completions()
            return
        popup = self.completer.popup()
        popup.setFont(self.font())
        popup.setCurrentIndex(self.completer.completionModel().index(0, 0))
        if not self.completion_width:
            # Measured once per list rather than on every key, since it
            # looks at every row.
            self.completion_width = (
                popup.sizeHintForColumn(0)
                + popup.verticalScrollBar().sizeHint().width() + 12)
        self.set_completion_shortcuts(False)
        self.completer.complete(self.completion_rect(prefix))

    def completion_rect(self, prefix):
        """Where the list opens: under the line being typed, with its names
        starting where the word being completed starts, so a row reads on
        from what is already there and covers none of it.

        :param prefix: the partial word in front of the cursor
        :type prefix: str
        :return: rect in this widget's coordinates, as QCompleter wants it
        :rtype: QtCore.QRect
        """
        at_cursor = self.cursorRect()
        start = self.textCursor()
        start.setPosition(max(start.position() - len(prefix),
                              start.block().position()))
        rect = self.cursorRect(start)
        if rect.top() != at_cursor.top():
            # The word wrapped, so its start is on the row above.
            rect = at_cursor
        popup = self.completer.popup()
        margin = popup.style().pixelMetric(
            QtWidgets.QStyle.PM_FocusFrameHMargin, None, popup) + 1
        rect.translate(-(popup.frameWidth() + margin), 0)
        rect.moveLeft(max(rect.left(), 0))
        # cursorRect is in the viewport, which the line numbers push in
        # from the widget's edge, and QCompleter places from the widget.
        rect.translate(self.viewport().pos())
        rect.setWidth(self.completion_width)
        return rect

    def request_completions(self, typed):
        """A key was typed: filter the open list now, or open one once
        typing pauses.

        A dot, and a slash inside a token, open it at once, since that is
        where someone stops to see what comes next.
        """
        prefix = self.completion_prefix()
        now = (self.completer.popup().isVisible() or typed == '.'
               or (typed == '/' and prefix.startswith(tokens.TOKEN_PREFIX)))
        if now:
            self.update_completions()
            return
        self.completion_position = self.textCursor().position()
        self.completion_timer.start()

    def completions_due(self):
        """Typing paused. Open the list, unless the cursor has gone."""
        if (not self.hasFocus() or
                self.textCursor().position() != self.completion_position):
            return
        self.update_completions()

    def hide_completions(self):
        self.completion_timer.stop()
        self.completion_base = None
        if self.completer.popup().isVisible():
            self.completer.popup().hide()
        self.set_completion_shortcuts(True)

    def set_completion_shortcuts(self, enabled):
        """Free up the keys the completion popup needs, and give them back.

        Return, Tab and Esc are bound to editor actions, and a QAction
        shortcut is consumed before the completer ever sees the key. While
        the popup is up those actions stand down, so it can be driven the
        way every other completion popup is.

        :param enabled: True to give the keys back to the editor
        :type enabled: bool
        """
        for action in (self.ce_actions.new_line,
                       self.ce_actions.indent_line,
                       self.ce_actions.unindent_line,
                       self.ce_actions.accept_edit_action,
                       self.ce_actions.cancel_edit_action):
            action.setEnabled(enabled)

    def insert_completion(self, completion):
        """Swap the typed prefix for the completion that was chosen."""
        prefix = self.completion_prefix()
        cursor = self.textCursor()
        cursor.setPosition(cursor.position() - len(prefix),
                           QtGui.QTextCursor.KeepAnchor)
        cursor.insertText(completion)
        # ${ auto-paired a } that the completion brings its own of.
        closer = completion[-1:]
        if closer in ')]}' and self.char_after_cursor(cursor) == closer:
            cursor.deleteChar()
        self.setTextCursor(cursor)
        self.set_completion_shortcuts(True)

    # Keys that belong to the completion popup while it is up. Return and
    # Tab take what is highlighted, Escape and Shift+Tab put the list
    # away. See keyPressEvent for why they have to be handed over.
    COMPLETION_KEYS = (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter,
                       QtCore.Qt.Key_Tab, QtCore.Qt.Key_Backtab,
                       QtCore.Qt.Key_Escape)

    def keyPressEvent(self, event):
        if (self.completer.popup().isVisible()
                and event.key() in self.COMPLETION_KEYS):
            # Qt offers each key to this widget before the completer gets
            # to act on it, and takes the widget accepting it as the whole
            # answer. A plain text edit accepts Return, so pressing it on
            # a highlighted completion put a new line in the code and the
            # completer never heard about it: the list vanished and what
            # was chosen was never written. Ignoring it is what says the
            # popup should have it.
            event.ignore()
            return
        if not self.isReadOnly() and self.handle_auto_pair(event):
            event.accept()
            self.hide_completions()
            return
        super(NxtCodeEditor, self).keyPressEvent(event)
        if self.isReadOnly():
            return
        typed = event.text()
        if typed and (typed.isalnum() or typed in '_./'):
            self.request_completions(typed)
        else:
            self.hide_completions()

    def char_after_cursor(self, cursor=None):
        cursor = cursor or self.textCursor()
        text = cursor.block().text()
        col = cursor.positionInBlock()
        return text[col] if col < len(text) else ''

    def char_before_cursor(self, cursor=None):
        cursor = cursor or self.textCursor()
        text = cursor.block().text()
        col = cursor.positionInBlock()
        return text[col - 1] if col > 0 else ''

    def handle_auto_pair(self, event):
        """Insert the matching closer for a bracket/quote, wrap the selection
        in the pair, or step over a closer that is already there.
        :param event: QKeyEvent
        :return: True if the key was handled.
        """
        mods = event.modifiers()
        # AltGr arrives as Ctrl+Alt on Windows, and is how [ and { are typed
        # on many layouts, so only a lone Ctrl or Alt means a shortcut.
        ctrl = bool(mods & QtCore.Qt.ControlModifier)
        alt = bool(mods & QtCore.Qt.AltModifier)
        if ctrl != alt:
            return False
        text = event.text()
        if not text:
            return False
        cursor = self.textCursor()
        close = self.AUTO_PAIRS.get(text)
        # Wrap a selection first, quotes included.
        if close is not None and cursor.hasSelection():
            start, end = cursor.selectionStart(), cursor.selectionEnd()
            inner = cursor.selection().toPlainText()
            cursor.beginEditBlock()
            cursor.insertText(text + inner + close)
            cursor.endEditBlock()
            cursor.setPosition(start + 1)
            cursor.setPosition(end + 1, QtGui.QTextCursor.KeepAnchor)
            self.setTextCursor(cursor)
            return True
        # Step over a closer that is already there instead of doubling it
        if text in self.AUTO_PAIRS.values() and self.char_after_cursor() == text:
            cursor.movePosition(QtGui.QTextCursor.Right)
            self.setTextCursor(cursor)
            return True
        if close is None:
            return False
        if text in ("'", '"'):
            before = self.char_before_cursor()
            # Mid word (apostrophes, string prefixes) or the third quote of
            # a triple quote: just type it.
            if (before.isalnum() or before == text or
                    self.char_after_cursor().isalnum()):
                return False
        cursor.insertText(text + close)
        cursor.movePosition(QtGui.QTextCursor.Left)
        self.setTextCursor(cursor)
        return True

    def set_font_size(self, delta=0.0, default=False):
        if default:
            self.font_size = 10
        else:
            self.font_size += delta
        font = self.font()
        font.setPixelSize(points_to_px(self.font_size))
        self.setFont(font)

    def update_previous_scroll_positions(self):
        self.prev_v_scroll_value = self.verticalScrollBar().value()
        self.prev_h_scroll_value = self.horizontalScrollBar().value()

    def suspend_global_actions(self):
        """Stand the main window's actions down while typing goes on here.

        The event filter does not stop them, so they are disabled outright.
        Suspending twice would record the already disabled states as if
        they were the real ones, and restoring would then leave the whole
        main window greyed out: Save Layer among them, with no way back
        short of restarting. The find and go to line fields suspend on
        their own focus as well, so that second call is a normal thing to
        happen, not a bug to guard against elsewhere.
        """
        if self.action_states:
            return
        for a in self.ce_widget.main_window.get_global_actions():
            self.action_states[a] = a.isEnabled()
            a.setEnabled(False)

    def restore_global_actions(self):
        for a, state in self.action_states.items():
            a.setEnabled(state)
        self.action_states = {}

    def hideEvent(self, event):
        # Losing focus is not the only way to stop typing here. Being
        # hidden, by selecting a node with no code or closing the tab,
        # leaves the actions disabled with nothing left to re-enable them.
        self.restore_global_actions()
        super(NxtCodeEditor, self).hideEvent(event)

    def focusInEvent(self, event):
        self.suspend_global_actions()
        super(NxtCodeEditor, self).focusInEvent(event)

    def focusOutEvent(self, event):
        self.restore_global_actions()
        if self.standard_menu:
            if self.standard_menu.isVisible():
                return QtWidgets.QPlainTextEdit.focusOutEvent(self, event)
        return QtWidgets.QPlainTextEdit.focusOutEvent(self, event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y() / 8
        if event.modifiers() == QtCore.Qt.ControlModifier:
            if delta > 0:
                self.set_font_size(delta=0.5)
            elif delta < 0:
                self.set_font_size(delta=-0.5)
        else:
            QtWidgets.QPlainTextEdit.wheelEvent(self, event)

    def contextMenuEvent(self, event):
        # Place the cursor under the mouse if nothing is selected
        if not self.textCursor().selection().toPlainText():
            self.setTextCursor(self.cursorForPosition(event.pos()))
        block_localize = (self.ce_widget.editing_active or
                          self.ce_widget.code_is_local)
        self.standard_menu = self.createStandardContextMenu()
        self.standard_menu.addAction(self.ce_actions.run_line_global_action)
        self.standard_menu.addAction(self.ce_actions.run_line_local_action)
        index = 1 if self.isReadOnly() else 5
        self.standard_menu.insertAction(self.standard_menu.actions()[index],
                                        self.ce_actions.copy_resolved_action)

        self.standard_menu.insertSeparator(self.standard_menu.actions()[0])
        if not block_localize:
            action = self.ce_actions.localize_code_action
            self.standard_menu.insertAction(self.standard_menu.actions()[0],
                                            action)

        self.standard_menu.insertAction(self.standard_menu.actions()[1],
                                        self.ce_actions.revert_code_action)

        self.standard_menu.addSeparator()
        self.standard_menu.addAction(self.ce_actions.find_action)
        self.standard_menu.addAction(self.ce_actions.replace_action)
        self.standard_menu.addAction(self.ce_actions.goto_line_action)
        edit_menu = self.standard_menu.addMenu('Line')
        edit_menu.addAction(self.ce_actions.duplicate_line)
        edit_menu.addAction(self.ce_actions.move_line_up)
        edit_menu.addAction(self.ce_actions.move_line_down)
        edit_menu.addAction(self.ce_actions.delete_line)
        edit_menu.addAction(self.ce_actions.expand_selection)
        edit_menu.setEnabled(not self.isReadOnly())
        # Folding only changes what is on show, so it works read only too.
        fold_menu = self.standard_menu.addMenu('Folding')
        fold_menu.addAction(self.ce_actions.fold_block_action)
        fold_menu.addAction(self.ce_actions.unfold_block_action)
        fold_menu.addAction(self.ce_actions.fold_all_action)
        fold_menu.addAction(self.ce_actions.unfold_all_action)

        self.standard_menu.exec_(event.globalPos())

    def eventFilter(self, widget, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        # QAbstractScrollArea filters its own viewport, so this runs during
        # construction as well, before there is a completer to ask about.
        completer = getattr(self, 'completer', None)
        if completer is not None and widget is completer.popup():
            # The popup can go away without us: Escape and clicking outside
            # are both handled inside QCompleter. Whatever closed it, the
            # editor wants Return, Tab and Esc back.
            if event.type() == QtCore.QEvent.Type.Hide:
                self.set_completion_shortcuts(True)
            return False
        if event.type() == QtCore.QEvent.Type.ShortcutOverride:
            return True
        return False

    def new_line(self):
        # get cursor and position
        cursor = self.textCursor()
        pos = cursor.position()
        anchor = cursor.anchor()

        # get current line text
        cursor.movePosition(QtGui.QTextCursor.StartOfLine)
        start_of_line = cursor.position()
        cursor.movePosition(QtGui.QTextCursor.EndOfLine,
                            QtGui.QTextCursor.KeepAnchor)
        end = cursor.position()
        self.setTextCursor(cursor)
        line_text = cursor.selection().toPlainText()

        # build indent text
        indent_text = ''

        # add indent for statements
        if line_text.endswith(':') and pos != start_of_line:
            indent_text += self.indent

        # add whitespace to match current line
        indent_text += ' ' * (len(line_text) - len(line_text.lstrip()))

        # add comment character
        if line_text.lstrip().startswith(
                self.comment_character) and pos > 0 and pos != end:
            indent_text += self.comment_character + ' '

        # reset cursor
        cursor.setPosition(pos)
        self.setTextCursor(cursor)

        # add return and indent
        cursor.setPosition(pos)
        cursor.setPosition(anchor, QtGui.QTextCursor.KeepAnchor)
        self.setTextCursor(cursor)
        indent_text = '\n' + indent_text
        self.insertPlainText(indent_text)

    def indent_code(self):
        # get cursor
        cursor = self.textCursor()

        # get positions
        pos = cursor.position()
        anchor = cursor.anchor()
        start = pos if pos < anchor else anchor
        end = anchor if anchor > pos else pos

        # insert tab
        if cursor.selection().isEmpty():
            self.insertPlainText(self.indent)

        # indent
        else:
            # get selected text
            selected_text = cursor.selection().toPlainText()

            # multiple lines
            if selected_text.count('\n'):
                # expand the selection to full lines
                # get start position
                cursor.setPosition(start)
                cursor.movePosition(QtGui.QTextCursor.StartOfLine)
                start_pos = cursor.position()

                # get end position
                cursor.setPosition(end)
                cursor.movePosition(QtGui.QTextCursor.EndOfLine)
                end_pos = cursor.position()

                # select full lines
                cursor.setPosition(start_pos)
                cursor.setPosition(end_pos, QtGui.QTextCursor.KeepAnchor)
                self.setTextCursor(cursor)
                lines_text = cursor.selection().toPlainText()

                # get indented text
                indented_lines = []
                for line in lines_text.split('\n'):
                    indented_lines.append(self.indent + line)

                # write indented lines
                indented_text = '\n'.join(indented_lines)
                self.insertPlainText(indented_text)

                # reset cursor
                diff = len(lines_text) - len(indented_text)
                cursor.setPosition(start + self.indent_len)
                cursor.setPosition(end - diff, QtGui.QTextCursor.KeepAnchor)
                self.setTextCursor(cursor)

            # single line
            else:
                # select full line
                cursor.movePosition(QtGui.QTextCursor.StartOfLine)
                cursor.movePosition(QtGui.QTextCursor.EndOfLine,
                                    QtGui.QTextCursor.KeepAnchor)
                self.setTextCursor(cursor)
                line_text = cursor.selection().toPlainText()

                # indent single line
                indented_text = self.indent + line_text
                self.insertPlainText(indented_text)

                # reset cursor
                cursor.setPosition(start + self.indent_len)
                cursor.setPosition(end + self.indent_len,
                                   QtGui.QTextCursor.KeepAnchor)
                self.setTextCursor(cursor)

    def unindent_code(self):
        # get cursor
        cursor = self.textCursor()

        # get positions
        pos = cursor.position()
        anchor = cursor.anchor()
        start = pos if pos < anchor else anchor
        end = anchor if anchor > pos else pos

        # get selected text
        if cursor.selection().isEmpty():
            cursor.movePosition(QtGui.QTextCursor.StartOfLine)
            cursor.movePosition(QtGui.QTextCursor.EndOfLine,
                                QtGui.QTextCursor.KeepAnchor)
        selected_text = cursor.selection().toPlainText()

        # multiple lines
        if selected_text.count('\n'):
            # expand the selection to full lines
            # get start position
            cursor.setPosition(start)
            cursor.movePosition(QtGui.QTextCursor.StartOfLine)
            start_pos = cursor.position()

            # get end position
            cursor.setPosition(end)
            cursor.movePosition(QtGui.QTextCursor.EndOfLine)
            end_pos = cursor.position()

            # select full lines
            cursor.setPosition(start_pos)
            cursor.setPosition(end_pos, QtGui.QTextCursor.KeepAnchor)
            self.setTextCursor(cursor)
            lines_text = cursor.selection().toPlainText()

            # get unindented text
            unindented_lines = list()
            start_changed = True
            for index, line in enumerate(lines_text.split('\n')):
                if line.startswith(self.indent):
                    unindented_lines.append(line[self.indent_len:])
                elif line.startswith(' '):
                    unindented_lines.append(line.lstrip())
                else:
                    unindented_lines.append(line)
                    if index == 0:
                        start_changed = False

            # write indented lines
            unindented_text = '\n'.join(unindented_lines)
            self.insertPlainText(unindented_text)

            # reset cursor
            diff = len(lines_text) - len(unindented_text)
            cursor.setPosition(start - self.indent_len)
            if start_changed:
                cursor.setPosition(start - self.indent_len)
            else:
                cursor.setPosition(start)
            cursor.setPosition(end - diff, QtGui.QTextCursor.KeepAnchor)

            self.setTextCursor(cursor)

        # single line
        else:
            # select full line
            cursor.movePosition(QtGui.QTextCursor.StartOfLine)
            cursor.movePosition(QtGui.QTextCursor.EndOfLine,
                                QtGui.QTextCursor.KeepAnchor)
            self.setTextCursor(cursor)
            line_text = cursor.selection().toPlainText()

            # unindent single line
            unindented_text = str()
            changed = True
            if line_text.startswith(self.indent):
                unindented_text = line_text[self.indent_len:]
            elif line_text.startswith(' '):
                unindented_text = line_text.lstrip()
            else:
                changed = False

            # write indented line
            if changed:
                self.insertPlainText(unindented_text)

            # reset cursor
            diff = self.indent_len if changed else 0
            cursor.setPosition(start - diff)
            cursor.setPosition(end - diff, QtGui.QTextCursor.KeepAnchor)
            self.setTextCursor(cursor)

    def increase_font_size(self):
        self.set_font_size(delta=0.5)

    def decrease_font_size(self):
        self.set_font_size(delta=-0.5)

    def reset_font_size(self):
        self.set_font_size(default=True)

    def comment_code(self):
        # Fixme: DRY this whole function up
        # get cursor
        cursor = self.textCursor()

        # get positions
        pos = cursor.position()
        anchor = cursor.anchor()
        start = pos if pos < anchor else anchor
        end = anchor if anchor > pos else pos

        # get selected text
        selected_text = cursor.selection().toPlainText()

        # multiple lines
        if selected_text.count('\n'):
            # expand the selection to full lines
            # get start position
            cursor.setPosition(start)
            cursor.movePosition(QtGui.QTextCursor.StartOfLine)
            start_pos = cursor.position()

            # get end position
            cursor.setPosition(end)
            cursor.movePosition(QtGui.QTextCursor.EndOfLine)
            end_pos = cursor.position()

            # select full lines
            cursor.setPosition(start_pos)
            cursor.setPosition(end_pos, QtGui.QTextCursor.KeepAnchor)
            self.setTextCursor(cursor)
            lines_text = cursor.selection().toPlainText()

            # inspect lines looking for existing comment characters and
            # leading white space
            # length
            lines = lines_text.split('\n')
            existing_comment_lines_count = 0
            leading_line_lengths = []
            for line in lines:
                line_lstrip = line.lstrip()
                leading_line_lengths.append(len(line) - len(line_lstrip))
                if line_lstrip.startswith(self.comment_character):
                    existing_comment_lines_count += 1
            leading_len = min(leading_line_lengths)

            # comment / uncomment mode
            if len(lines) == existing_comment_lines_count:
                uncomment = True
            else:
                uncomment = False

            # get commented / uncommented lines
            new_lines = []
            if lines[0].lstrip().startswith(self.begin_comment_str):
                start_line_padding = 2
            else:
                start_line_padding = 1
            for line in lines:
                line_l_split = line[:leading_len]
                line_r_split = line[leading_len:]
                padding = 2
                if uncomment:
                    if not line_r_split.startswith(self.begin_comment_str):
                        padding = 1
                    new_line = line_l_split + line_r_split[padding:]
                else:
                    new_line = line_l_split
                    new_line += self.begin_comment_str
                    new_line += line_r_split
                new_lines += [new_line]

            # write text
            new_lines_text = '\n'.join(new_lines)
            self.insertPlainText(new_lines_text)

            # reset cursor
            diff = len(lines_text) - len(new_lines_text)
            if uncomment:
                offset = start_line_padding * -1
            else:
                offset = self.comment_character_len + 1
            cursor.setPosition(start + offset)
            cursor.setPosition(end - diff, QtGui.QTextCursor.KeepAnchor)
            self.setTextCursor(cursor)

        # single line
        else:
            # select full line
            cursor.movePosition(QtGui.QTextCursor.StartOfLine)
            cursor.movePosition(QtGui.QTextCursor.EndOfLine,
                                QtGui.QTextCursor.KeepAnchor)
            self.setTextCursor(cursor)
            line_text = cursor.selection().toPlainText()

            # get commented / uncommented single line
            leading_len = len(line_text) - len(line_text.lstrip())
            line_l_split = line_text[:leading_len]
            line_r_split = line_text[leading_len:]
            if line_r_split.startswith(self.comment_character):
                uncomment = True
            else:
                uncomment = False
            padding = 2
            if uncomment:
                if not line_r_split.startswith(self.begin_comment_str):
                    padding = 1
                new_line = line_l_split + line_r_split[padding:]
            else:
                new_line = line_l_split
                new_line += self.begin_comment_str
                new_line += line_r_split

            # write new line
            self.insertPlainText(new_line)

            # reset cursor
            diff = len(line_text) - len(new_line)
            if uncomment:
                offset = padding * -1
            else:
                offset = self.comment_character_len + 1
            cursor.setPosition(start + offset)
            cursor.setPosition(end - diff, QtGui.QTextCursor.KeepAnchor)
            self.setTextCursor(cursor)

    def get_selected_lines(self, rm_single_line_indent=True):
        """Convert full/partial selection to full lines. By default single
        line selection will have its leading whitespace trimmed.
        :param rm_single_line_indent: If false single lines will keep their
        leading whitespace.
        :return: string
        """
        cursor = self.textCursor()
        # Find min and max of selection
        position = cursor.position()
        anchor = cursor.anchor()
        start = min(position, anchor)
        end = max(position, anchor)
        # Determine multi line
        multi_line = bool(cursor.selection().toPlainText().count('\n'))
        # Move to start
        cursor.setPosition(start, QtGui.QTextCursor.MoveAnchor)
        cursor.movePosition(QtGui.QTextCursor.StartOfLine)
        select_begin = cursor.position()
        # Move to end
        cursor.setPosition(end)
        cursor.movePosition(QtGui.QTextCursor.EndOfLine)
        select_end = cursor.position()
        # Select full lines
        cursor.setPosition(select_begin)
        cursor.setPosition(select_end, QtGui.QTextCursor.KeepAnchor)
        selection_string = cursor.selection().toPlainText()
        if not multi_line and rm_single_line_indent:  # Remove indent
            selection_string = selection_string.lstrip()
        return selection_string

    def exec_selection(self, globally=False):
        """Execute the selected line(s) of code. If there is no selection or
        only a partial selection the full line(s) will be selected and used.
        :param globally: If True the code will run in the global context of
        the runtime layer.
        :return: None
        """
        code_string = self.get_selected_lines()
        if not code_string:
            logger.warning('No code selected!')
            return
        self.ce_widget.stage_model.execute_snippet(code_string,
                                                   self.ce_widget.node_path,
                                                   globally=globally)

    def get_token_at(self, pos):
        """Find the (non-nested) ${...} token under a viewport position.
        :param pos: QPoint in viewport coordinates
        :return: tuple of (full_token_str, token_body) or (None, None)
        """
        cursor = self.cursorForPosition(pos)
        line = cursor.block().text()
        col = cursor.positionInBlock()
        for match in re.finditer(r'\$\{[^{}]*\}', line):
            if match.start() <= col <= match.end():
                full = match.group(0)
                return full, tokens.get_token_content(full)
        return None, None

    def node_path_from_token_body(self, body):
        """Resolve a token body to an absolute node path if it names one.
        A bare ``${attr}`` (no '.' and no '/') is a local attribute, so it
        resolves to the current node.
        :param body: string content of a ${} token
        :return: node path string or None
        """
        body = body.strip()
        if not body:
            return None
        # file:: path:: contents:: and plugin tokens are not node refs
        all_tokens = tuple(tokens.TOKENTYPE.ALL) + tuple(tokens.plugin_tokens)
        for token_type in all_tokens:
            if token_type.prefix and body.startswith(token_type.prefix):
                return None
        current = self.ce_widget.node_path
        start = current or nxt_path.WORLD
        if '.' in body:
            node_part = body.rpartition('.')[0]
            if not node_part:
                return current  # '.attr' is the current node
            return nxt_path.expand_relative_node_path(node_part, start)
        if nxt_path.NODE_SEP in body:
            return nxt_path.expand_relative_node_path(body, start)
        return current

    def goto_token_definition(self, pos):
        """Ctrl+click handler: select and frame the node a token references.
        :param pos: QPoint in viewport coordinates
        :return: True if a node was selected
        """
        if self.ce_widget.editing_active:
            # Going to another node would accept the edit on the way out.
            return False
        full, body = self.get_token_at(pos)
        if not full:
            return False
        model = self.ce_widget.stage_model
        node_path = self.node_path_from_token_body(body)
        if not node_path or model is None:
            return False
        if node_path == self.ce_widget.node_path:
            return False  # local attr, nowhere to go
        if not model.node_exists(node_path):
            logger.warning("Cannot navigate: '{}' not found".format(node_path))
            return False
        model.select_and_frame(node_path)
        return True

    def show_token_tooltip(self, help_event):
        """Show the resolved value of the token under the mouse as a tooltip.

        Only for tokens that read an attribute. Resolving file::, contents::
        or a plugin token reads files or runs plugin code, which hovering
        should not do.
        :param help_event: QHelpEvent, in viewport coordinates
        :return: True if a tooltip was shown
        """
        full, body = self.get_token_at(help_event.pos())
        model = self.ce_widget.stage_model
        node_path = self.node_path_from_token_body(body) if full else None
        if not node_path or model is None:
            QtWidgets.QToolTip.hideText()
            return False
        if not model.node_exists(node_path):
            QtWidgets.QToolTip.showText(
                help_event.globalPos(),
                '{}  ->  <no node at {}>'.format(full, node_path), self)
            return True
        try:
            resolved = model.resolve(self.ce_widget.node_path, full)
        except Exception:
            logger.exception('Token resolve failed for tooltip')
            QtWidgets.QToolTip.hideText()
            return False
        if resolved is None:
            resolved = '<unresolved>'
        QtWidgets.QToolTip.showText(help_event.globalPos(),
                                    '{}  ->  {}'.format(full, resolved), self)
        return True

    def viewportEvent(self, event):
        # Here rather than in event(): tooltip positions that reach the
        # editor itself are in its own coordinates, which the line number
        # gutter offsets from the text.
        if event.type() == QtCore.QEvent.ToolTip:
            if self.show_token_tooltip(event):
                return True
        return super(NxtCodeEditor, self).viewportEvent(event)

    def mousePressEvent(self, event):
        if (event.modifiers() & QtCore.Qt.ControlModifier and
                event.button() == QtCore.Qt.LeftButton):
            if self.goto_token_definition(event.pos()):
                event.accept()
                return
        super(NxtCodeEditor, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        over_token = False
        if (event.modifiers() & QtCore.Qt.ControlModifier and
                not self.ce_widget.editing_active):
            full, body = self.get_token_at(event.pos())
            over_token = bool(full and self.node_path_from_token_body(body))
        viewport = self.viewport()
        if over_token and self._cursor_before_token is None:
            self._cursor_before_token = viewport.cursor().shape()
            viewport.setCursor(QtCore.Qt.PointingHandCursor)
        elif not over_token and self._cursor_before_token is not None:
            # Put back whatever was showing, which is not always the
            # I-beam: the editor shows an arrow until it is edited.
            viewport.setCursor(self._cursor_before_token)
            self._cursor_before_token = None
        super(NxtCodeEditor, self).mouseMoveEvent(event)


class NumberBar(QtWidgets.QWidget):
    """class that defines textEditor numberBar

    Also holds the fold markers, in a column on the right of the numbers:
    one on each line that opens an indented block, pointing down while the
    block shows and right while it is folded. Clicking a line with a
    marker folds or unfolds it.
    """

    width_changed = QtCore.Signal()

    def __init__(self, editor, color):
        QtWidgets.QWidget.__init__(self, editor)

        self.editor = editor
        self.editor.blockCountChanged.connect(self.update_width)
        self.editor.updateRequest.connect(self.update_contents)
        self.color = QtGui.QColor(color)
        # Tracked so the pointer can show which lines can be clicked.
        self.setMouseTracking(True)
        self.update_width()

    def fold_width(self):
        """Width of the fold marker column."""
        return self.fontMetrics().height()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(event.rect(), self.color)
        block = self.editor.firstVisibleBlock()
        if self.editor.changed_lines:
            changed_lines = self.editor.changed_lines[:]
        else:
            changed_lines = []
        fold_width = self.fold_width()
        # Iterate over all visible text blocks in the document.
        while block.isValid():
            if not block.isVisible():
                # Folded away, there is no line to number.
                block = block.next()
                continue
            self.font().setBold(False)
            block_number = block.blockNumber()
            block_top = self.editor.blockBoundingGeometry(block).translated(
                self.editor.contentOffset()).top()
            # Check if the position of the block is out side of the visible area
            if block_top >= event.rect().bottom():
                break
            # We want the line number for the selected line to be bold.
            painter.setPen(QtGui.QColor(colors.LIGHTER_TEXT))
            if block_number == self.editor.textCursor().blockNumber():
                self.font().setBold(True)
            else:
                painter.setPen(colors.DEFAULT_TEXT)
            # Draw the line number right justified at the position of the line.
            paint_rect = QtCore.QRect(0, block_top, self.width(),
                                      self.editor.fontMetrics().height())
            # Paint changed lines
            if block_number in changed_lines:
                painter.fillRect(paint_rect, colors.UNSAVED)
                painter.setPen(colors.LIGHTEST_TEXT)
                changed_lines.remove(block_number)
            painter.setFont(self.font())
            text_rect = paint_rect.marginsAdded(
                QtCore.QMargins(0, 0, -fold_width, 0))
            painter.drawText(text_rect, QtCore.Qt.AlignRight,
                             str(block_number + 1))
            if self.editor.opens_fold(block):
                folded = self.editor.is_folded(block)
                marker_rect = QtCore.QRectF(
                    paint_rect.right() - fold_width + 1, paint_rect.top(),
                    fold_width, paint_rect.height())
                self.paint_fold_marker(painter, marker_rect, folded)
            painter.setPen(QtCore.Qt.NoPen)
            block = block.next()
            if not block.isValid() and changed_lines:
                cached_last_line = changed_lines[-1]
                last_line = block_number + 1
                bottom = cached_last_line - last_line
                paint_rect.translate(0, self.editor.fontMetrics().height())
                paint_rect.setHeight(paint_rect.height() * bottom)
                painter.fillRect(paint_rect, colors.UNSAVED)
        painter.end()

        QtWidgets.QWidget.paintEvent(self, event)

    @staticmethod
    def paint_fold_marker(painter, rect, folded):
        """A small triangle, pointing right when folded and down when not."""
        size = min(rect.width(), rect.height()) * 0.45
        center = rect.center()
        if folded:
            points = [QtCore.QPointF(center.x() - size * 0.45,
                                     center.y() - size * 0.6),
                      QtCore.QPointF(center.x() + size * 0.55, center.y()),
                      QtCore.QPointF(center.x() - size * 0.45,
                                     center.y() + size * 0.6)]
            color = QtGui.QColor(theme.TEXT_DIM)
        else:
            points = [QtCore.QPointF(center.x() - size * 0.6,
                                     center.y() - size * 0.4),
                      QtCore.QPointF(center.x() + size * 0.6,
                                     center.y() - size * 0.4),
                      QtCore.QPointF(center.x(), center.y() + size * 0.55)]
            color = QtGui.QColor(colors.DEFAULT_TEXT)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(color)
        painter.drawPolygon(QtGui.QPolygonF(points))
        painter.restore()

    def block_at(self, y):
        """The line on show at a height in this bar, or None."""
        block = self.editor.firstVisibleBlock()
        offset = self.editor.contentOffset()
        while block.isValid():
            if block.isVisible():
                geometry = self.editor.blockBoundingGeometry(
                    block).translated(offset)
                if geometry.top() > y:
                    return None
                if y < geometry.bottom():
                    return block
            block = block.next()
        return None

    def foldable_block_at(self, y):
        block = self.block_at(y)
        if block is not None and self.editor.opens_fold(block):
            return block
        return None

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            block = self.foldable_block_at(event.pos().y())
            if block is not None:
                self.editor.toggle_fold(block)
                event.accept()
                return
        super(NumberBar, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.foldable_block_at(event.pos().y()) is not None:
            self.setCursor(QtCore.Qt.PointingHandCursor)
        else:
            self.unsetCursor()
        super(NumberBar, self).mouseMoveEvent(event)

    def get_width(self):
        count = self.editor.blockCount()
        width = self.fontMetrics().horizontalAdvance(str(count)) + 6
        return width + self.fold_width()

    def update_width(self):
        width = self.get_width()
        self.setFixedWidth(width)
        self.width_changed.emit()
        self.editor.setViewportMargins(width, 0, 0, 0)

    def update_contents(self, rect, scroll):
        if scroll:
            self.scroll(0, scroll)
        else:
            self.update(0, rect.y(), self.width(), rect.height())

        if rect.contains(self.editor.viewport().rect()):
            self.update_width()


class OverlayWidget(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super(OverlayWidget, self).__init__(parent)
        self._parent = parent
        self.ext_color = QtGui.QColor(10, 10, 10, 95)
        self.base_color = QtGui.QColor(62, 62, 62, 0)
        self.main_color = self.base_color
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.data_state = ''
        self.click_msg = 'Double Click To Edit'

    def paintEvent(self, event):
        painter = QtGui.QPainter()
        painter.begin(self)
        points = 14
        painter.setFont(FONTS.monospace_font(points))
        font_metrics = QtGui.QFontMetrics(painter.font())
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        # actual_display_state
        code_editor = self._parent.ce_widget
        model = code_editor.stage_model
        self.data_state = code_editor.actual_display_state
        painter.setPen(QtCore.Qt.white)
        # Draw top right data state text to HUD
        show_data_state = self._parent.ce_actions.show_data_state_action.isChecked()
        if show_data_state:
            offset = font_metrics.boundingRect(self.data_state).width()
            offset += points * 1.5
            painter.drawText(self.rect().right() - offset,
                             points * 1.5, self.data_state)
        # Draw center message text
        show_msg = self._parent.ce_actions.overlay_message_action.isChecked()
        if show_msg:
            msg_offset = font_metrics.boundingRect(self.click_msg).width()
            msg_offset += points
            painter.drawText(self.rect().center().x() - (msg_offset*.5),
                             self.rect().center().y(), self.click_msg)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_Darken)
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(self.rect()), 9, 9)
        if self.main_color:
            painter.fillPath(path, QtGui.QBrush(self.main_color))
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_Screen)
        display_is_raw = self.data_state == DATA_STATE.RAW
        mode_is_cache = model.data_state == DATA_STATE.CACHED
        if display_is_raw and mode_is_cache:
            color = colors.UNCACHED_RED
            painter.fillPath(path, QtGui.QBrush(color,
                                                QtCore.Qt.BDiagPattern))
        elif self.main_color is self.ext_color:
            painter.fillPath(path, QtGui.QBrush(self.ext_color))
        painter.end()


def code_style_factory(color='', border='solid', thickness=(2, 2, 2)):
    """Silly way to generate qss for the border style of the code editor.
    :param color: string of hex color
    :param border: 'solid', 'dotted', 'dot-dash', ect
    :param thickness: list of [DEFAULT, HOVER, FOCUS] thicknesses
    :return: string of qss
    """
    if not color:
        color = theme.RAISED  # The theme's raised panels
    lines = []
    for thick in thickness:
        line = 'border-radius: 11px; border: {}px {} {}'.format(thick, border, color)
        lines.append(line)
    code_edit_default_style = theme.fill('''
                            QPlainTextEdit{
                                %s;
                            }
        
                            QPlainTextEdit:hover {
                                %s;
                            }
        
                            QPlainTextEdit:focus{
                                %s;
                            }

                            QToolTip {
                                color: {TEXT};
                                background-color: {RAISED};
                                border: 1px solid {BORDER_STRONG};
                                padding: 3px;
                            }
                            ''')
    return code_edit_default_style % tuple(lines)
