# Builtin
import builtins
import importlib
import keyword
import logging
import re
import sys
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
from nxt_editor import colors, user_dir
from nxt_editor.decorator_widgets import OpinionDots
from nxt import DATA_STATE, nxt_path, tokens
from nxt.nxt_node import INTERNAL_ATTRS
from nxt_editor.dockwidgets import syntax
from nxt_editor.dockwidgets.code_overlays import (FindOverlay,
                                                  GotoLineOverlay)
from nxt_editor.constants import FONTS
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
        self.background_frame.setStyleSheet('background-color: #3E3E3E; border-radius: 0px;')
        self.layout.addWidget(self.background_frame)

        # details
        self.details_frame = QtWidgets.QFrame(self)
        self.details_frame.setStyleSheet('background-color: #3E3E3E; border-radius: 0px;')
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
        self.name_label.setFont(QtGui.QFont(FONTS.DEFAULT_FAMILY, 14))
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
        self.path_label.setFont(QtGui.QFont(FONTS.MONOSPACE, 8))
        self.path_label.setStyleSheet('color: grey')
        self.details_layout.addWidget(self.path_label)

        # code editor
        self.code_frame = QtWidgets.QFrame(self)
        self.code_frame.setStyleSheet('background-color: #3E3E3E; border-radius: 0px')
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
        self.code_widget.setStyleSheet('background-color: #3E3E3E;')
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
        self.copy_resolved_button.setStyleSheet('QToolTip {color: white; border: 1px solid #3E3E3E}')
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
        self.format_button.setStyleSheet('QToolTip {color: white; border: 1px solid #3E3E3E}')
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
        self.accept_button.setStyleSheet('QToolTip {color: white; border: 1px solid #3E3E3E}')
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
        self.cancel_button.setStyleSheet('QToolTip {color: white; border: 1px solid #3E3E3E}')
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
        self.revert_code_button.setStyleSheet('QToolTip {color: white; border: 1px solid #3E3E3E}')
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
            style = '''
            background-color: #232323;
            background-image: url(:icons/icons/BDiagPattern.png);
            background-repeat: repeat-xy;
            background-attachment: fixed;'''
        else:
            style = 'background-color: #232323;'
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
        self.node_path = self.stage_model.node_focus
        if not self.node_path:
            self.clear()
            return

        self.node_name = nxt_path.node_name_from_node_path(self.node_path)
        if not self.node_name:
            self.clear()
        else:
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

            style = '''
                    background-color: #323232;
                    border: 1px solid transparent;
                    border-top-left-radius: 8px;
                    border-bottom-left-radius: 8px;
                    border-top-right-radius: 0px;
                    border-bottom-right-radius: 0px;
                    '''

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
        self.completer.activated.connect(self.insert_completion)
        self.completer.popup().installEventFilter(self)
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

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("text/plain"):
            event.acceptProposedAction()
            self.setFocus()
            return
        super(NxtCodeEditor, self).dragEnterEvent(event)

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
        doc = self.document()
        return [str(doc.findBlockByLineNumber(i).text()) for i in range(doc.lineCount())]

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
        found = {}
        for match in self.IMPORT_RE.finditer(self.toPlainText()):
            module_name = match.group('mod') or match.group('from')
            if not module_name:
                continue
            local_name = match.group('alias') or module_name.split('.')[0]
            if match.group('mod') and not match.group('alias'):
                # "import os.path" binds os, not os.path
                module_name = module_name.split('.')[0]
            if local_name in found:
                continue
            module = sys.modules.get(module_name)
            if module is None:
                try:
                    module = importlib.import_module(module_name)
                except Exception:
                    logger.debug('No completions for %s, it would not import'
                                 % module_name)
                    continue
            found[local_name] = module
        return found

    def module_completions(self, prefix):
        """Names reachable through a dotted prefix, like os.pa.

        :param prefix: the partial word being typed
        :type prefix: str
        :rtype: list
        """
        if '.' not in prefix or not self.completion_source_enabled(
                'complete_modules_action'):
            return []
        root, _, rest = prefix.partition('.')
        module = self.imported_modules().get(root)
        if module is None:
            return []
        walked = root
        # Follow the dots that are already complete, so os.path.jo looks
        # inside os.path rather than os.
        parts = rest.split('.')
        for part in parts[:-1]:
            module = getattr(module, part, None)
            if module is None:
                return []
            walked += '.' + part
        return ['%s.%s' % (walked, name) for name in dir(module)
                if not name.startswith('_')]

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
            words.update(('self', 'STAGE'))
            model = self.ce_widget.stage_model
            node_path = self.ce_widget.node_path
            if model and node_path:
                try:
                    for name in model.get_node_attr_names(node_path):
                        words.add(name)
                        words.add('self.' + name)
                        # How an attribute is written in a compute
                        words.add(tokens.TOKEN_PREFIX + name
                                  + tokens.TOKEN_SUFFIX)
                except Exception:
                    logger.debug('Could not read attrs for completion on '
                                 + str(node_path), exc_info=True)
            all_tokens = (tuple(tokens.TOKENTYPE.ALL)
                          + tuple(tokens.plugin_tokens))
            for token in all_tokens:
                if token.prefix:
                    words.add(tokens.TOKEN_PREFIX + token.prefix)
        if self.completion_source_enabled('complete_modules_action'):
            # The bare module names. What is inside them is resolved per
            # prefix, since dir() on everything imported would be huge.
            words.update(self.imported_modules())
        if self.completion_source_enabled('complete_document_action'):
            words.update(re.findall(r'[A-Za-z_][A-Za-z0-9_]{2,}',
                                    self.toPlainText()))
        return sorted(words)

    # What a partial word can be made of. Dots, so self.na completes
    # against attribute names rather than starting over at na. Dollars,
    # braces and colons, because a token is a word too: stopping at the $
    # meant ${fi offered the prefix "fi", which matches no token, which is
    # why only python builtins ever appeared.
    PREFIX_CHARS = r'[A-Za-z0-9_.:${}]*$'

    def completion_prefix(self):
        """The partial word in front of the cursor.

        :rtype: str
        """
        cursor = self.textCursor()
        text = cursor.block().text()[:cursor.positionInBlock()]
        match = re.search(self.PREFIX_CHARS, text)
        return match.group(0) if match else ''

    def update_completions(self, force=False):
        """Offer completions for the word being typed.

        :param force: show them even when the prefix is short or the
            auto-complete preference is off, which is what Ctrl+Space does
        :type force: bool
        """
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
        if self.completion_words is None:
            self.completion_words = self.build_completion_words()
        # Module contents depend on what is being typed, so they are worked
        # out per prefix rather than kept in the cached list.
        words = self.completion_words + self.module_completions(prefix)
        model = QtCore.QStringListModel(sorted(set(words)), self.completer)
        self.completer.setModel(model)
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
        rect = self.cursorRect()
        width = (popup.sizeHintForColumn(0)
                 + popup.verticalScrollBar().sizeHint().width() + 12)
        rect.setWidth(width)
        self.set_completion_shortcuts(False)
        self.completer.complete(rect)

    def hide_completions(self):
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
        super(NxtCodeEditor, self).keyPressEvent(event)
        if self.isReadOnly():
            return
        typed = event.text()
        if typed and (typed.isalnum() or typed in '_.'):
            self.update_completions()
        elif self.completer.popup().isVisible():
            self.hide_completions()

    def set_font_size(self, delta=0.0, default=False):
        if default:
            self.font_size = 10
        else:
            self.font_size += delta
        font = self.font()
        font.setPointSize(self.font_size)
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

    def keyPressEvent(self, event):
        plain = not (event.modifiers() & (QtCore.Qt.ControlModifier |
                                          QtCore.Qt.AltModifier))
        if plain and not self.isReadOnly() and self.handle_auto_pair(event):
            event.accept()
            return
        super(NxtCodeEditor, self).keyPressEvent(event)

    def char_after_cursor(self):
        cursor = self.textCursor()
        text = cursor.block().text()
        col = cursor.positionInBlock()
        return text[col] if col < len(text) else ''

    def char_before_cursor(self):
        cursor = self.textCursor()
        text = cursor.block().text()
        col = cursor.positionInBlock()
        return text[col - 1] if col > 0 else ''

    def handle_auto_pair(self, event):
        """Insert the matching closer for a bracket/quote, wrap the selection
        in the pair, or step over a closer that is already there.
        :param event: QKeyEvent
        :return: True if the key was handled.
        """
        text = event.text()
        if not text:
            return False
        cursor = self.textCursor()
        closers = set(self.AUTO_PAIRS.values())
        # Step over an auto-inserted closer instead of doubling it
        if (text in closers and not cursor.hasSelection() and
                self.char_after_cursor() == text):
            cursor.movePosition(QtGui.QTextCursor.Right)
            self.setTextCursor(cursor)
            return True
        close = self.AUTO_PAIRS.get(text)
        if close is None:
            return False
        # Don't pair quotes mid-word (apostrophes, string suffixes)
        if text in ("'", '"'):
            if (self.char_before_cursor().isalnum() or
                    self.char_after_cursor().isalnum()):
                return False
        if cursor.hasSelection():
            cursor.insertText(text + cursor.selectedText() + close)
            return True
        cursor.insertText(text + close)
        cursor.movePosition(QtGui.QTextCursor.Left)
        self.setTextCursor(cursor)
        return True


class NumberBar(QtWidgets.QWidget):
    """class that defines textEditor numberBar"""

    width_changed = QtCore.Signal()

    def __init__(self, editor, color):
        QtWidgets.QWidget.__init__(self, editor)

        self.editor = editor
        self.editor.blockCountChanged.connect(self.update_width)
        self.editor.updateRequest.connect(self.update_contents)
        self.color = QtGui.QColor(color)
        self.update_width()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(event.rect(), self.color)
        block = self.editor.firstVisibleBlock()
        if self.editor.changed_lines:
            changed_lines = self.editor.changed_lines[:]
        else:
            changed_lines = []
        # Iterate over all visible text blocks in the document.
        while block.isValid():
            self.font().setBold(False)
            block_number = block.blockNumber()
            block_top = self.editor.blockBoundingGeometry(block).translated(
                self.editor.contentOffset()).top()
            # Check if the position of the block is out side of the visible area
            if not block.isVisible() or block_top >= event.rect().bottom():
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
            text_rect = paint_rect.marginsAdded(QtCore.QMargins(0, 0, -4, 0))
            painter.drawText(text_rect, QtCore.Qt.AlignRight,
                             str(block_number + 1))
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

    def get_width(self):
        count = self.editor.blockCount()
        width = self.fontMetrics().horizontalAdvance(str(count)) + 10
        return width

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
            font_size = self.editor.currentCharFormat().font().pointSize()
            self.font().setPointSize(font_size)
            self.font().setStyle(QtGui.QFont.StyleNormal)
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
        painter.setFont(QtGui.QFont(FONTS.MONOSPACE, 14))
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
            offset += painter.font().pointSize() * 1.5
            painter.drawText(self.rect().right() - offset,
                             painter.font().pointSize() * 1.5, self.data_state)
        # Draw center message text
        show_msg = self._parent.ce_actions.overlay_message_action.isChecked()
        if show_msg:
            msg_offset = font_metrics.boundingRect(self.click_msg).width()
            msg_offset += painter.font().pointSize()
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
        color = '#31363B'  # Pulled from the dark.qss
    lines = []
    for thick in thickness:
        line = 'border-radius: 11px; border: {}px {} {}'.format(thick, border, color)
        lines.append(line)
    code_edit_default_style = '''
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
                                color: #f0f0f0;
                                background-color: #2b2b2b;
                                border: 1px solid #5a5a5a;
                                padding: 3px;
                            }
                            '''
    return code_edit_default_style % tuple(lines)
