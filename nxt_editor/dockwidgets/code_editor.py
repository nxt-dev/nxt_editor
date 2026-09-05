# Builtin
import logging
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
from nxt import DATA_STATE, nxt_path
from nxt.nxt_node import INTERNAL_ATTRS
from nxt_editor.dockwidgets import syntax
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

    def resizeEvent(self, event):
        self.overlay_widget.setGeometry(self.editor.rect().marginsRemoved(QtCore.QMargins(3, 2, 2, 2)))
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
            rect = self.editor.rect().marginsRemoved(QtCore.QMargins(3, 2,
                                                                     2, 2))
            self.overlay_widget.setGeometry(rect)

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
            # Keep find highlights/counter in sync with the new node's code
            self.editor.find_bar.reevaluate()

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

    def exit_editing(self):
        self.editor.setReadOnly(True)
        self.editing_active = False
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
        # Extra selections owned by the find bar (all matches). Kept apart
        # from the current line highlight so refreshing one keeps the other.
        self.find_selections = []
        self.cursorPositionChanged.connect(self.highlight_current_line)

        # apply syntax highlighting
        self.syntax_highlighter = syntax_highlighter
        self.highlighter = self.syntax_highlighter(self.document())

        # scroll bar memory
        func = self.update_previous_scroll_positions
        self.verticalScrollBar().valueChanged.connect(func)
        self.installEventFilter(self)

        # Find / replace bar. Parented to the editor's container rather than
        # the editor itself: as a child of the QPlainTextEdit it could not
        # hold keyboard focus and would inherit the editor's shortcuts.
        self.find_bar = FindReplaceBar(self, parent=self.ce_widget.code_widget)
        self.find_bar.hide()

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

    def selected_find_text(self):
        """Single line selection to prefill the find field, else empty string.
        :return: string
        """
        text = self.textCursor().selectedText()
        # QTextCursor.selectedText uses U+2029 for line breaks
        if not text or u'\u2029' in text:
            return ''
        return text

    def resizeEvent(self, *e):
        """overload resizeEvent handler"""
        # resize number_bar widget
        if self.display_line_numbers:
            cr = self.contentsRect()
            rec = QtCore.QRect(cr.left(), cr.top(), self.number_bar.get_width(), cr.height())
            self.number_bar.setGeometry(rec)

        QtWidgets.QPlainTextEdit.resizeEvent(self, *e)
        self.reposition_find_bar()

    def reposition_find_bar(self):
        """Anchor the find bar to the top right of the editor, clear of the
        vertical scroll bar. The bar is a sibling overlay so it is placed in
        the parent's coordinates using the editor geometry.
        """
        find_bar = getattr(self, 'find_bar', None)
        if find_bar is None or not find_bar.isVisible():
            return
        find_bar.adjustSize()
        margin = 8
        geo = self.geometry()
        scrollbar = self.verticalScrollBar()
        scrollbar_w = scrollbar.width() if scrollbar.isVisible() else 0
        x = geo.right() - find_bar.width() - margin - scrollbar_w
        y = geo.top() + margin
        find_bar.move(max(geo.left() + margin, x), y)

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

    def apply_extra_selections(self):
        """Set extra selections from the current line highlight plus the find
        bar matches, so refreshing either one does not clobber the other.
        """
        selections = []
        if self.current_line_highlight:
            hi_selection = QtWidgets.QTextEdit.ExtraSelection()
            hi_selection.format.setBackground(self.current_line_color)
            hi_selection.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
            hi_selection.cursor = self.textCursor()
            hi_selection.cursor.clearSelection()
            selections.append(hi_selection)
        selections.extend(self.find_selections)
        self.setExtraSelections(selections)

    def highlight_current_line(self):
        if self.current_line_highlight:
            new_current_line_number = self.textCursor().blockNumber()
            if new_current_line_number != self.current_line_number:
                self.current_line_number = new_current_line_number
                self.apply_extra_selections()
        else:
            self.apply_extra_selections()

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

    def focusInEvent(self, event):
        # I don't know why the event filter isn't stopping these actions so
        # I'm just forcing them to be disabled while we're typing.
        self.action_states = {}
        for a in self.ce_widget.main_window.get_global_actions():
            self.action_states[a] = a.isEnabled()
            a.setEnabled(False)
        super(NxtCodeEditor, self).focusInEvent(event)

    def focusOutEvent(self, event):
        for a, state in self.action_states.items():
            a.setEnabled(state)
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

        self.standard_menu.exec_(event.globalPos())

    def eventFilter(self, widget, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        if event.type() == QtCore.QEvent.Type.ShortcutOverride:
            # Claim Ctrl+F / Ctrl+R from the window level Find and Replace
            # action so they reach keyPressEvent and drive the in-editor bar
            if (event.modifiers() & QtCore.Qt.ControlModifier and
                    event.key() in (QtCore.Qt.Key_F, QtCore.Qt.Key_R)):
                event.accept()
                return True
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

    def keyPressEvent(self, event):
        if event.modifiers() & QtCore.Qt.ControlModifier:
            if event.key() == QtCore.Qt.Key_F:
                self.find_bar.open_find(self.selected_find_text())
                event.accept()
                return
            if event.key() == QtCore.Qt.Key_R:
                self.find_bar.open_replace(self.selected_find_text())
                event.accept()
                return
        if event.key() == QtCore.Qt.Key_Escape and self.find_bar.isVisible():
            self.find_bar.close_bar()
            event.accept()
            return
        super(NxtCodeEditor, self).keyPressEvent(event)


class FindReplaceBar(QtWidgets.QFrame):
    """Find / replace bar floating over an NxtCodeEditor.

    Find (Ctrl+F) and replace (Ctrl+R) work on the text currently shown in
    the editor: every match is highlighted, the active match is selected and
    the counter shows position/total. Replace is only enabled while the
    editor is editable.
    """

    STYLE = '''
        QFrame {
            background-color: #323232;
            border: 1px solid #555555;
            border-radius: 6px;
        }
        QLineEdit {
            background-color: #232323;
            color: #d6d6d6;
            border: 1px solid #555555;
            border-radius: 3px;
            padding: 2px;
        }
        QToolButton, QPushButton {
            background-color: #3E3E3E;
            color: #d6d6d6;
            border: 1px solid #555555;
            border-radius: 3px;
            padding: 2px 6px;
        }
        QToolButton:checked { background-color: #5a5a5a; }
        QToolButton:hover, QPushButton:hover { background-color: #4a4a4a; }
        QLabel { color: #b7b4b1; border: none; background: transparent; }
        '''

    RETURN_KEYS = (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter)

    def __init__(self, editor, parent=None):
        super(FindReplaceBar, self).__init__(parent=parent or editor)
        self.editor = editor
        self.match_starts = []
        self.setStyleSheet(self.STYLE)
        self.setFont(QtGui.QFont(FONTS.DEFAULT_FAMILY, 9))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # find row
        find_row = QtWidgets.QHBoxLayout()
        find_row.setSpacing(4)
        layout.addLayout(find_row)

        self.find_field = QtWidgets.QLineEdit()
        self.find_field.setPlaceholderText('Find')
        self.find_field.setMinimumWidth(160)
        self.find_field.textChanged.connect(self.refresh)
        find_row.addWidget(self.find_field)

        self.count_label = QtWidgets.QLabel('')
        self.count_label.setMinimumWidth(48)
        self.count_label.setAlignment(QtCore.Qt.AlignCenter)
        find_row.addWidget(self.count_label)

        self.case_button = QtWidgets.QToolButton()
        self.case_button.setText('Aa')
        self.case_button.setCheckable(True)
        self.case_button.setToolTip('Case Sensitive')
        self.case_button.toggled.connect(self.refresh)
        find_row.addWidget(self.case_button)

        self.word_button = QtWidgets.QToolButton()
        self.word_button.setText('W')
        self.word_button.setCheckable(True)
        self.word_button.setToolTip('Whole Word')
        self.word_button.toggled.connect(self.refresh)
        find_row.addWidget(self.word_button)

        self.prev_button = QtWidgets.QToolButton()
        self.prev_button.setText('Prev')
        self.prev_button.setToolTip('Previous Match (Shift+Enter)')
        self.prev_button.clicked.connect(self.find_previous)
        find_row.addWidget(self.prev_button)

        self.next_button = QtWidgets.QToolButton()
        self.next_button.setText('Next')
        self.next_button.setToolTip('Next Match (Enter)')
        self.next_button.clicked.connect(self.find_next)
        find_row.addWidget(self.next_button)

        self.close_button = QtWidgets.QToolButton()
        self.close_button.setText('X')
        self.close_button.setToolTip('Close (Esc)')
        self.close_button.clicked.connect(self.close_bar)
        find_row.addWidget(self.close_button)

        # replace row
        self.replace_row = QtWidgets.QWidget()
        replace_layout = QtWidgets.QHBoxLayout(self.replace_row)
        replace_layout.setContentsMargins(0, 0, 0, 0)
        replace_layout.setSpacing(4)
        layout.addWidget(self.replace_row)

        self.replace_field = QtWidgets.QLineEdit()
        self.replace_field.setPlaceholderText('Replace')
        self.replace_field.setMinimumWidth(160)
        replace_layout.addWidget(self.replace_field)

        self.replace_button = QtWidgets.QPushButton('Replace')
        self.replace_button.clicked.connect(self.replace_one)
        replace_layout.addWidget(self.replace_button)

        self.replace_all_button = QtWidgets.QPushButton('Replace All')
        self.replace_all_button.clicked.connect(self.replace_all)
        replace_layout.addWidget(self.replace_all_button)

        # Esc and Enter inside either field are handled by the bar
        self.find_field.installEventFilter(self)
        self.replace_field.installEventFilter(self)

    # -- show / hide --------------------------------------------------- #
    def open_find(self, prefill=''):
        self.replace_row.hide()
        self.show_bar(prefill)

    def open_replace(self, prefill=''):
        editable = not self.editor.isReadOnly()
        self.replace_row.setVisible(True)
        self.replace_field.setEnabled(editable)
        self.replace_button.setEnabled(editable)
        self.replace_all_button.setEnabled(editable)
        self.show_bar(prefill)

    def show_bar(self, prefill):
        if prefill:
            self.find_field.setText(prefill)
        self.show()
        self.raise_()
        self.adjustSize()
        self.editor.reposition_find_bar()
        self.refresh()
        # Defer the focus grab: we are inside the editor's key handler and a
        # synchronous setFocus gets overridden once the Ctrl+F event finishes
        QtCore.QTimer.singleShot(0, self.grab_focus)

    def grab_focus(self):
        self.find_field.setFocus(QtCore.Qt.ShortcutFocusReason)
        self.find_field.selectAll()

    def close_bar(self):
        self.hide()
        self.clear_highlights()
        self.editor.setFocus()

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.KeyPress:
            key = event.key()
            if key == QtCore.Qt.Key_Escape:
                self.close_bar()
                return True
            if key in self.RETURN_KEYS:
                if obj is self.replace_field:
                    self.replace_one()
                elif event.modifiers() & QtCore.Qt.ShiftModifier:
                    self.find_previous()
                else:
                    self.find_next()
                return True
        return super(FindReplaceBar, self).eventFilter(obj, event)

    def reevaluate(self):
        """Recompute matches against the editor's current content, e.g. after
        a node change replaced the code.
        """
        if self.isVisible():
            self.highlight_all()

    # -- searching ----------------------------------------------------- #
    def find_flags(self):
        flags = QtGui.QTextDocument.FindFlags()
        if self.case_button.isChecked():
            flags |= QtGui.QTextDocument.FindCaseSensitively
        if self.word_button.isChecked():
            flags |= QtGui.QTextDocument.FindWholeWords
        return flags

    def refresh(self):
        """Re-highlight all matches and jump to the first one."""
        self.highlight_all()
        if self.match_starts:
            self.find_next()

    def find_next(self, backward=False):
        needle = self.find_field.text()
        if not needle:
            return
        flags = self.find_flags()
        if backward:
            flags |= QtGui.QTextDocument.FindBackward
        found = self.editor.find(needle, flags)
        if not found:  # wrap around
            cursor = self.editor.textCursor()
            end = QtGui.QTextCursor.End if backward else QtGui.QTextCursor.Start
            cursor.movePosition(end)
            self.editor.setTextCursor(cursor)
            self.editor.find(needle, flags)
        self.update_count()

    def find_previous(self):
        self.find_next(backward=True)

    def highlight_all(self):
        needle = self.find_field.text()
        selections = []
        self.match_starts = []
        if needle:
            doc = self.editor.document()
            flags = self.find_flags()
            fmt = QtGui.QTextCharFormat()
            highlight = QtGui.QColor(colors.SELECTED)
            highlight.setAlpha(90)
            fmt.setBackground(highlight)
            cursor = QtGui.QTextCursor(doc)
            while True:
                cursor = doc.find(needle, cursor, flags)
                if cursor.isNull():
                    break
                sel = QtWidgets.QTextEdit.ExtraSelection()
                sel.format = fmt
                sel.cursor = cursor
                selections.append(sel)
                self.match_starts.append(cursor.selectionStart())
        self.editor.find_selections = selections
        self.editor.apply_extra_selections()
        self.update_count()

    def update_count(self):
        if not self.find_field.text():
            self.count_label.setText('')
            return
        total = len(self.match_starts)
        pos = self.editor.textCursor().selectionStart()
        idx = self.match_starts.index(pos) + 1 if pos in self.match_starts else 0
        self.count_label.setText('{}/{}'.format(idx, total))

    def clear_highlights(self):
        self.match_starts = []
        self.editor.find_selections = []
        self.editor.apply_extra_selections()

    # -- replacing ----------------------------------------------------- #
    def replace_one(self):
        if self.editor.isReadOnly():
            return
        needle = self.find_field.text()
        if not needle:
            return
        cursor = self.editor.textCursor()
        selected = cursor.selectedText()
        if self.case_button.isChecked():
            is_match = selected == needle
        else:
            is_match = selected.lower() == needle.lower()
        if cursor.hasSelection() and is_match:
            cursor.insertText(self.replace_field.text())
        self.highlight_all()
        self.find_next()

    def replace_all(self):
        if self.editor.isReadOnly():
            return
        needle = self.find_field.text()
        if not needle:
            return
        replacement = self.replace_field.text()
        doc = self.editor.document()
        flags = self.find_flags()
        edit_cursor = self.editor.textCursor()
        edit_cursor.beginEditBlock()
        scan = QtGui.QTextCursor(doc)
        count = 0
        while True:
            scan = doc.find(needle, scan, flags)
            if scan.isNull():
                break
            scan.insertText(replacement)
            count += 1
        edit_cursor.endEditBlock()
        logger.info("Replaced {} occurrence(s) of '{}'".format(count, needle))
        self.highlight_all()


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
                            '''
    return code_edit_default_style % tuple(lines)
