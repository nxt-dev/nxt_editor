# Built-in
import textwrap
import sys
import logging
from functools import partial

# External
from Qt import QtWidgets
from Qt import QtGui
from Qt import QtCore
try:
    QtCore.QStringListModel
except AttributeError:
    del QtCore
    from PySide2 import QtCore

# Internal
from nxt_editor import user_dir
from nxt_editor.dockwidgets.dock_widget_base import DockWidgetBase
from nxt_editor.pixmap_button import PixmapButton
from nxt_editor.label_edit import LabelEdit
from nxt_editor import colors, LOGGER_NAME
from nxt_editor.decorator_widgets import OpinionDots
from nxt import DATA_STATE, NODE_ERRORS, nxt_path
from nxt.nxt_node import INTERNAL_ATTRS, META_ATTRS
from nxt import tokens

# Fixme: Should this be a pref?
HISTORICAL_MAX_CHARS = 50

logger = logging.getLogger(LOGGER_NAME)


class PropertyEditor(DockWidgetBase):

    PREF_KEY = user_dir.USER_PREF.ATTR_SORTING

    def __init__(self, graph_model=None, title='Property Editor', parent=None,
                 minimum_width=300, minimum_height=350):
        super(PropertyEditor, self).__init__(title=title,
                                             parent=parent,
                                             minimum_width=minimum_width,
                                             minimum_height=minimum_height)

        self.setObjectName('Property Editor')

        # local attributes
        self.main_window = parent
        self.authoring_actions = parent.node_actions
        self._actions = parent.property_manager_actions
        self.comment_actions = parent.node_comment_actions
        self.stage_model = graph_model
        self.node_path = None
        self._resolved = True
        self.locked = False
        self.node_path = ''
        self.node_instance = ''
        self.node_inst_source = ('', '')
        self.inst_layer_colors = []
        self.node_name = ''
        self.node_pos = (0.0, 0.0)
        self.node_comment = ''
        self.node_comment_source = ('', '')
        self.comment_layer_colors = []
        self.node_execute = ''
        self.node_exec_source = ('', '')
        self.exec_layer_colors = []
        self.node_child_order = []
        self.co_layer_colors = []
        self.node_attr_names = []
        self.node_enabled = True
        self.enabled_layer_colors = []
        self.selection = []
        self.user_sort_pref = user_dir.user_prefs.get(self.PREF_KEY)

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

        # ACTIONS
        self.addActions(self._actions.actions())
        # Inst path
        self.localize_inst_path_action = self._actions.localize_inst_path_action
        self.localize_inst_path_action.triggered.connect(
            self.localize_inst_path)
        self.revert_inst_path_action = self._actions.revert_inst_path_action
        self.revert_inst_path_action.triggered.connect(self.revert_inst_path)
        # Exec path
        self.localize_exec_path_action = self._actions.localize_exec_path_action
        self.localize_exec_path_action.triggered.connect(
            self.localize_exec_path)
        self.revert_exec_path_action = self._actions.revert_exec_path_action
        self.revert_exec_path_action.triggered.connect(self.revert_exec_path)
        # Attrs
        self.add_attr_action = self._actions.add_attr_action
        self.add_attr_action.triggered.connect(self.add_attr)
        self.remove_attr_action = self._actions.remove_attr_action
        self.remove_attr_action.triggered.connect(self.remove_selected_attrs)
        # Copy Actions
        self.copy_raw_action = self._actions.copy_raw_action
        copy_raw = partial(self.copy_selected_attrs, DATA_STATE.RAW)
        self.copy_raw_action.triggered.connect(copy_raw)
        self.copy_resolved_action = self._actions.copy_resolved_action
        copy_resolved = partial(self.copy_selected_attrs, DATA_STATE.RESOLVED)
        self.copy_resolved_action.triggered.connect(copy_resolved)
        self.copy_cached_action = self._actions.copy_cached_action
        copy_cached = partial(self.copy_selected_attrs, DATA_STATE.CACHED)
        self.copy_cached_action.triggered.connect(copy_cached)
        # Localize/Revert
        self.localize_attr_action = self._actions.localize_attr_action
        self.localize_attr_action.triggered.connect(self.localize_attrs)
        self.revert_attr_action = self._actions.revert_attr_action
        self.revert_attr_action.triggered.connect(self.revert_attrs)
        ############
        # properties
        ############
        self.properties_frame = QtWidgets.QFrame(self)
        self.properties_frame.setStyleSheet('background-color: #3E3E3E; border-radius: 0px;')
        self.layout.addWidget(self.properties_frame)

        self.properties_layout = QtWidgets.QVBoxLayout()
        self.properties_layout.setContentsMargins(4, 0, 4, 0)
        self.properties_layout.setSpacing(0)
        self.properties_frame.setLayout(self.properties_layout)

        # name
        self.name_layout = QtWidgets.QHBoxLayout()
        self.name_layout.setContentsMargins(0, 0, 0, 0)
        self.properties_layout.addLayout(self.name_layout)

        self.name_label = LabelEdit(parent=self)
        self.name_label.setFont(QtGui.QFont("Roboto", 14))
        self.name_label.nameChangeRequested.connect(self.edit_name)
        self.name_layout.addWidget(self.name_label, 0, QtCore.Qt.AlignLeft)

        self.name_edit_button = PixmapButton(pixmap=':icons/icons/pencil.png',
                                             pixmap_hover=':icons/icons/pencil_hover.png',
                                             pixmap_pressed=':icons/icons/pencil.png',
                                             size=16,
                                             parent=self)
        self.name_edit_button.pressed.connect(self.name_label.edit_text)
        self.name_layout.addWidget(self.name_edit_button, 0, QtCore.Qt.AlignLeft)

        self.name_layout.addStretch()

        # details
        self.details_layout = QtWidgets.QGridLayout()
        self.details_layout.setContentsMargins(20, 4, 0, 4)
        self.details_layout.setSpacing(2)
        self.properties_layout.addLayout(self.details_layout)

        # path
        self.path_label = QtWidgets.QLabel('Path', parent=self)
        self.details_layout.addWidget(self.path_label, 0, 0)

        self.path_field = QtWidgets.QLineEdit(parent=self)
        self.path_field.setAlignment(QtCore.Qt.AlignVCenter)
        self.path_field.setStyleSheet('border-radius: 11px; border: 1px solid transparent; background-color: #323232')
        self.path_field.setFont(QtGui.QFont("Roboto Mono", 8))
        self.path_field.setAlignment(QtCore.Qt.AlignVCenter)
        self.path_field.setReadOnly(True)
        self.details_layout.addWidget(self.path_field, 0, 1)

        # instance
        self.instance_label = QtWidgets.QLabel('Instance', parent=self)
        self.details_layout.addWidget(self.instance_label, 1, 0)

        self.instance_layout = QtWidgets.QGridLayout()
        self.details_layout.addLayout(self.instance_layout, 1, 1)

        self.instance_field = LineEdit(parent=self)
        self.instance_field.focus_changed.connect(self.focus_instance_field)
        self.instance_field.setFont(QtGui.QFont("Roboto Mono", 8))
        self.instance_field.setAlignment(QtCore.Qt.AlignVCenter)
        self.instance_field.editingFinished.connect(self.edit_instance)
        self.instance_layout.addWidget(self.instance_field, 0, 0)

        self.instance_field_model = QtCore.QStringListModel()
        self.instance_field_completer = QtWidgets.QCompleter()
        self.instance_field_completer.popup().setStyleSheet('border: 1px solid transparent; background-color: #323232; color: white')
        self.instance_field_completer.setModel(self.instance_field_model)
        self.instance_field.setCompleter(self.instance_field_completer)
        self.instance_field.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.instance_field.customContextMenuRequested.connect(self.instance_context_menu)

        self.locate_instance_button = PixmapButton(pixmap=':icons/icons/locate_off.png',
                                                   pixmap_hover=':icons/icons/locate_on_hover.png',
                                                   pixmap_pressed=':icons/icons/locate_on_pressed.png',
                                                   size=16,
                                                   parent=self.properties_frame)
        self.locate_instance_button.setToolTip('Locate Instance')
        self.locate_instance_button.setStyleSheet('QToolTip {color: white; border: 1px solid #3E3E3E}')
        self.locate_instance_button.setFixedWidth(17)
        self.locate_instance_button.setFixedHeight(16)
        self.locate_instance_button.clicked.connect(self.view_instance_node)
        self.instance_layout.addWidget(self.locate_instance_button, 0, 1)
        self.instance_opinions = OpinionDots(self, 'Instance Opinions')
        self.instance_layout.addWidget(self.instance_opinions, 0, 2)
        self.revert_instance_button = PixmapButton(pixmap=':icons/icons/delete.png',
                                                   pixmap_hover=':icons/icons/delete_hover.png',
                                                   pixmap_pressed=':icons/icons/delete_pressed.png',
                                                   size=12,
                                                   parent=self.properties_frame)
        self.revert_instance_button.setToolTip('Revert Instance')
        self.revert_instance_button.setStyleSheet('QToolTip {color: white; border: 1px solid #3E3E3E}')
        self.revert_instance_button.set_action(self.revert_inst_path_action)
        self.instance_layout.addWidget(self.revert_instance_button, 0, 3)

        # execute in
        self.execute_label = QtWidgets.QLabel('Exec Input', parent=self)
        self.details_layout.addWidget(self.execute_label, 2, 0)

        self.execute_layout = QtWidgets.QGridLayout()
        self.details_layout.addLayout(self.execute_layout, 2, 1)

        self.execute_field = LineEdit(parent=self)
        self.execute_field.setStyleSheet(line_edit_style_factory('white'))
        self.execute_field.setFont(QtGui.QFont("Roboto Mono", 8))
        self.execute_field.setAlignment(QtCore.Qt.AlignVCenter)
        self.execute_field.editingFinished.connect(self.edit_exec_source)
        self.execute_field.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.execute_field.customContextMenuRequested.connect(self.exec_context_menu)
        self.execute_layout.addWidget(self.execute_field, 0, 0)

        self.execute_field_model = QtCore.QStringListModel()
        self.execute_field_completer = QtWidgets.QCompleter()
        self.execute_field_completer.popup().setStyleSheet('border: 1px solid transparent; background-color: #323232; color: white')
        self.execute_field_completer.setModel(self.execute_field_model)
        self.execute_field.setCompleter(self.execute_field_completer)
        self.execute_opinions = OpinionDots(self, 'Execute Opinions')
        self.execute_layout.addWidget(self.execute_opinions, 0, 1)
        self.revert_exec_source_button = PixmapButton(pixmap=':icons/icons/delete.png',
                                                      pixmap_hover=':icons/icons/delete_hover.png',
                                                      pixmap_pressed=':icons/icons/delete_pressed.png',
                                                      size=12,
                                                      parent=self.properties_frame)
        self.revert_exec_source_button.setToolTip('Revert Execute Source')
        self.revert_exec_source_button.setStyleSheet('QToolTip {color: white; border: 1px solid #3E3E3E}')
        self.revert_exec_source_button.set_action(self.revert_exec_path_action)
        self.execute_layout.addWidget(self.revert_exec_source_button, 0, 2)
        # execute_order
        self.child_order_label = QtWidgets.QLabel('Child Order',
                                                  parent=self)
        self.details_layout.addWidget(self.child_order_label, 3, 0)

        self.child_order_layout = QtWidgets.QGridLayout()
        self.details_layout.addLayout(self.child_order_layout, 3, 1)

        self.child_order_field = LineEdit(parent=self)
        self.child_order_field.setStyleSheet('border-radius: 11px; border: 1px solid transparent; background-color: #232323')
        self.child_order_field.setFont(QtGui.QFont("Roboto Mono", 8))
        self.child_order_field.setAlignment(QtCore.Qt.AlignVCenter)
        self.child_order_field.accept.connect(self.accept_edit_child_order)
        self.child_order_field.cancel.connect(self.cancel_edit_child_order)
        self.child_order_layout.addWidget(self.child_order_field, 0, 0)

        self.child_order_field_model = QtCore.QStringListModel()
        self.child_order_field_completer = QtWidgets.QCompleter()
        self.child_order_field_completer.popup().setStyleSheet('border: 1px solid transparent; background-color: #323232; color: white')
        self.child_order_field_completer.setModel(self.child_order_field_model)
        self.child_order_field.setCompleter(self.child_order_field_completer)
        self.child_order_opinions = OpinionDots(self, 'Child Order Opinions')
        self.child_order_layout.addWidget(self.child_order_opinions, 0, 1)
        self.revert_child_order_button = PixmapButton(
            pixmap=':icons/icons/delete.png',
            pixmap_hover=':icons/icons/delete_hover.png',
            pixmap_pressed=':icons/icons/delete_pressed.png',
            size=12,
            parent=self.properties_frame)
        self.revert_child_order_button.setToolTip('Revert Child Order')
        self.revert_child_order_button.setStyleSheet(
            'QToolTip {color: white; border: 1px solid #3E3E3E}')
        self.revert_child_order_button.clicked.connect(self.revert_child_order)
        self.child_order_layout.addWidget(self.revert_child_order_button, 0, 2)

        # position
        self.position_label = QtWidgets.QLabel('Position', parent=self)
        self.position_label.setMaximumWidth(80)
        self.details_layout.addWidget(self.position_label, 4, 0)

        self.position_layout = QtWidgets.QHBoxLayout()
        self.details_layout.addLayout(self.position_layout, 4, 1)

        self.positionX_field = NodePositionSpinbox(parent=self)
        self.positionX_field.setFixedWidth(80)
        self.positionX_field.setAlignment(QtCore.Qt.AlignRight)
        self.positionX_field.setSingleStep(1)
        self.positionX_field.setMaximum(10000)
        self.positionX_field.setMinimum(-10000)
        self.positionX_field.stepChanged.connect(self.edit_position)
        self.positionX_field.editingFinished.connect(self.edit_position)
        self.position_layout.addWidget(self.positionX_field, 0, QtCore.Qt.AlignLeft)

        self.positionY_field = NodePositionSpinbox(parent=self)
        self.positionY_field.setFixedWidth(80)
        self.positionY_field.setAlignment(QtCore.Qt.AlignRight)
        self.positionY_field.setSingleStep(1)
        self.positionY_field.setMaximum(10000)
        self.positionY_field.setMinimum(-10000)
        self.positionY_field.stepChanged.connect(self.edit_position)
        self.positionY_field.editingFinished.connect(self.edit_position)
        self.position_layout.addWidget(self.positionY_field, 0, QtCore.Qt.AlignLeft)

        self.enabled_checkbox_label = QtWidgets.QLabel('Enabled: ',
                                                       parent=self)
        self.position_layout.addWidget(self.enabled_checkbox_label, 0,
                                       QtCore.Qt.AlignLeft)
        self.enabled_checkbox = QtWidgets.QCheckBox()
        self.enabled_checkbox.stateChanged.connect(self.toggle_node_enabled)
        self.position_layout.addWidget(self.enabled_checkbox, 0,
                                       QtCore.Qt.AlignLeft)
        self.enabled_opinions = OpinionDots(self, 'Enabled Opinions')
        self.position_layout.addWidget(self.enabled_opinions, 0,
                                       QtCore.Qt.AlignLeft)
        icn = ':icons/icons/'
        self.revert_enabled_button = PixmapButton(pixmap=icn + 'delete.png',
                                                  pixmap_hover=icn+'delete_hover.png',
                                                  pixmap_pressed=icn+'delete_pressed.png',
                                                  size=12,
                                                  parent=self.properties_frame)
        self.revert_enabled_button.setToolTip('Revert Enabled State')
        self.revert_enabled_button.setStyleSheet('QToolTip {color: white; '
                                          'order: 1px solid #3E3E3E'
                                          '}')
        self.revert_enabled_button.clicked.connect(self.revert_node_enabled)
        self.position_layout.addWidget(self.revert_enabled_button, 0,
                                       QtCore.Qt.AlignLeft)

        self.position_layout.addStretch()

        # comment
        self.comment_label = QtWidgets.QLabel('Comment')
        self.details_layout.addWidget(self.comment_label, 5, 0)

        self.comment_layout = QtWidgets.QGridLayout()
        self.details_layout.addLayout(self.comment_layout, 5, 1)

        self.comment_field = TextEdit(self, 'Node Comment')
        self.comment_field.addActions(self.comment_actions.actions())
        self.comment_field.setFixedHeight(44)
        self.comment_field.setTabChangesFocus(False)
        self.comment_field.accept.connect(self.accept_edit_comment)
        self.comment_field.cancel.connect(self.cancel_edit_comment)
        self.comment_layout.addWidget(self.comment_field, 0, 0)
        self.comment_opinions = OpinionDots(self, 'Comment Opinions', vertical=True)
        self.comment_layout.addWidget(self.comment_opinions, 0, 1)
        self.revert_comment_button = PixmapButton(pixmap=':icons/icons/delete.png',
                                                  pixmap_hover=':icons/icons/delete_hover.png',
                                                  pixmap_pressed=':icons/icons/delete_pressed.png',
                                                  size=12,
                                                  parent=self.properties_frame)
        self.revert_comment_button.setToolTip('Revert Comment')
        self.revert_comment_button.setStyleSheet('QToolTip {color: white; border: 1px solid #3E3E3E}')
        self.revert_comment_button.clicked.connect(self.remove_comment)
        self.comment_layout.addWidget(self.revert_comment_button, 0, 2)
        # Comment
        self.accept_comment_action = self.comment_actions.accept_comment_action
        self.accept_comment_action.triggered.connect(self.accept_edit_comment)
        self.cancel_comment_action = self.comment_actions.cancel_comment_action
        self.cancel_comment_action.triggered.connect(self.cancel_edit_comment)
        ##################
        # attributes table
        ##################
        style = '''
                QTableView {
                    outline: none;
                    border-radius: 11px;
                    border: 1px solid transparent;
                    font-family: "Roboto Mono";
                    font-size: 12px
                }

                QTableView::item {
                    padding: 3px;
                }

                QTableView::item:selected:hover {
                    color: #148CD2;
                }

                QTableView:item:selected {
                    background-color: #113343;
                    color: white;
                }

                QHeaderView {
                    border-radius: 8px;
                    border: 0px solid transparent;
                }

                QHeaderView::section::horizontal::first {
                    border-top-left-radius: 6px;
                }

                QHeaderView::section::horizontal::last {
                    border-top-right-radius: 6px;
                }

                QToolTip {
                    font-family: Roboto Mono;
                    color: white;
                    border: 1px solid #3E3E3E
                }
                '''

        self.attributes_widget = QtWidgets.QWidget(self)
        self.attributes_widget.setStyleSheet('background-color: #232323')
        self.properties_layout.addWidget(self.attributes_widget, 1)

        self.attributes_layout = QtWidgets.QVBoxLayout()
        self.attributes_layout.setContentsMargins(0, 0, 0, 0)
        self.attributes_layout.setSpacing(0)
        self.attributes_widget.setLayout(self.attributes_layout)

        self.table_view = AttrsTableView(self)
        self.table_view.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table_view.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked)
        self.table_view.setSortingEnabled(True)
        self.table_view.setStyleSheet(style)
        self.table_view.verticalHeader().setMinimumSectionSize(12)
        self.table_view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table_view.customContextMenuRequested.connect(self.custom_context_menu)
        self.attributes_layout.addWidget(self.table_view, 1)

        self.attributes_layout.addStretch()

        # headers
        horizontal_header = self.table_view.horizontalHeader()
        horizontal_header.setSectionsMovable(True)
        horizontal_header.setStretchLastSection(True)
        header_dict = {COLUMNS.name: 'Name',
                       COLUMNS.value: 'Value',
                       COLUMNS.nxt_type: 'Type',
                       COLUMNS.source: 'Source',
                       COLUMNS.locality: 'Locality',
                       COLUMNS.comment: 'Comment'}
        self.header_names = COLUMNS.column_dict_to_list(header_dict)
        self.model = PropertyModel(graph_model=self.stage_model,
                                   node_path=self.node_path,
                                   view=self.table_view,
                                   headers=self.header_names,
                                   parent=self)

        self.proxy_model = QtCore.QSortFilterProxyModel()
        self.proxy_model.setSourceModel(self.model)

        self.table_view.setModel(self.proxy_model)
        self.table_view.selectionModel().selectionChanged.connect(self.set_selection)

        # add remove row
        self.property_options_layout = QtWidgets.QHBoxLayout()
        self.property_options_layout.setContentsMargins(10, 4, 10, 10)
        self.property_options_layout.setSpacing(8)
        self.properties_layout.addLayout(self.property_options_layout)
        self.property_options_layout.addStretch(10)


        # Add attr button
        self.add_attr_button = PixmapButton(pixmap=':icons/icons/plus.png',
                                            pixmap_hover=':icons/icons/plus_hover.png',
                                            pixmap_pressed=':icons/icons/plus_hover.png',
                                            size=10,
                                            parent=self.properties_frame)
        self.add_attr_button.setFixedWidth(10)
        self.add_attr_button.set_action(self.add_attr_action)
        self.property_options_layout.addWidget(self.add_attr_button)
        # Remove attr button
        self.remove_attr_button = PixmapButton(pixmap=':icons/icons/minus.png',
                                               pixmap_hover=':icons/icons/minus_hover.png',
                                               pixmap_pressed=':icons/icons/minus_hover.png',
                                               size=10,
                                               parent=self.properties_frame)
        self.remove_attr_button.setFixedWidth(10)
        self.remove_attr_button.set_action(self.remove_attr_action)
        self.property_options_layout.addWidget(self.remove_attr_button)

        if not self.main_window.in_startup:
            self.update_styles()
            self.display_properties()

    @property
    def view(self):
        return self.main_window.view

    @property
    def resolved(self):
        return self.stage_model.data_state if self.stage_model else True

    def update_resolved(self):
        self.model.set_represented_node(node_path=self.node_path)

    def set_selection(self):
        indexes = [self.proxy_model.mapToSource(p) for p in self.table_view.selectedIndexes()]
        self.model.selected_indexes = indexes

    def set_stage_model(self, stage_model):
        super(PropertyEditor, self).set_stage_model(stage_model=stage_model)
        if self.stage_model:
            self.model.stage_model = self.stage_model
            self.set_represented_node()

    def set_stage_model_connections(self, model, connect):
        self.model_signal_connections = [
            (model.node_focus_changed, self.set_represented_node),
            (model.layer_lock_changed, self.handle_locking),
            (model.nodes_changed, self.handle_nodes_changed),
            (model.attrs_changed, self.handle_attrs_changed),
            (model.data_state_changed, self.update_resolved),
            (model.node_moved, self.handle_node_moved),
            (model.comp_layer_changed, self.set_represented_node),
            (model.target_layer_changed, self.set_represented_node),
        ]
        super(PropertyEditor, self).set_stage_model_connections(model,
                                                                connect)

    def on_stage_model_destroyed(self):
        super(PropertyEditor, self).on_stage_model_destroyed()
        self.properties_frame.hide()

    def handle_locking(self, *args):
        # TODO: Make it a user pref to lock the property editor when node is locked?
        # self.locked = self.stage_model.target_layer.get_locked()
        if self.locked:
            self.table_view.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        else:
            self.table_view.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked)
        # Read only
        self.name_label.setReadOnly(self.locked)
        self.instance_field.setReadOnly(self.locked)
        self.execute_field.setReadOnly(self.locked)
        self.child_order_field.setReadOnly(self.locked)
        self.positionX_field.setReadOnly(self.locked)
        self.positionY_field.setReadOnly(self.locked)
        self.comment_field.setReadOnly(self.locked)
        # Enable/Disable
        self.revert_instance_button.setEnabled(not self.locked)
        self.revert_exec_source_button.setEnabled(not self.locked)
        self.revert_child_order_button.setEnabled(not self.locked)
        self.enabled_checkbox.setEnabled(not self.locked)
        self.revert_enabled_button.setEnabled(not self.locked)
        self.revert_comment_button.setEnabled(not self.locked)
        self.add_attr_button.setEnabled(not self.locked)
        self.remove_attr_button.setEnabled(not self.locked)
        # Actions
        for action in self.authoring_actions.actions() + self._actions.actions() + self.comment_actions.actions():
            action.setEnabled(not self.locked)

    def handle_nodes_changed(self, nodes):
        if self.node_path in nodes:
            self.set_represented_node()

    def handle_attrs_changed(self, attr_paths):
        for path in attr_paths:
            if self.node_path == nxt_path.node_path_from_attr_path(path):
                self.set_represented_node()
                return

    def handle_node_moved(self, node_path):
        if node_path == self.node_path:
            self.node_pos = self.stage_model.get_node_pos(node_path)
            self.update_properties()

    def set_represented_node(self):
        self.node_path = self.stage_model.node_focus
        if not self.node_path:
            self.clear()
            self.properties_frame.hide()
            return
        self.properties_frame.show()
        if self.user_sort_pref:
            order_str = self.user_sort_pref['order']
            if order_str == 'AscendingOrder':
                order = QtCore.Qt.AscendingOrder
            else:
                order = QtCore.Qt.DescendingOrder
            col = self.user_sort_pref['column']
            if self.model.rowCount(self):
                self.model.horizontal_header.blockSignals(True)
                self.model.horizontal_header.setSortIndicator(col, order)
                self.model.horizontal_header.blockSignals(False)

        self.node_name = nxt_path.node_name_from_node_path(self.node_path)
        if not self.node_name:
            self.clear()
            return
        disp_layer = self.stage_model.comp_layer
        # set instance completer options
        # Todo: node_path completer logic needed!
        top_nodes = self.stage_model.get_node_sibling_paths(self.node_path)
        if top_nodes:
            self.instance_field_model.setStringList(top_nodes)

        node_path = self.node_path
        # set execute completer options
        sibling_node_paths = self.stage_model.get_node_sibling_paths(node_path)
        if sibling_node_paths:
            self.execute_field_model.setStringList(sibling_node_paths)

        # set node data
        if self.stage_model.data_state != DATA_STATE.RAW:
            expand = True
        else:
            expand = False
        self.node_instance = self.stage_model.get_node_instance_path(node_path,
                                                                     disp_layer,
                                                                     expand)
        self.node_inst_source = self.stage_model.get_node_attr_source(node_path,
                                                                      INTERNAL_ATTRS.INSTANCE_PATH,
                                                                      disp_layer)
        inst_layers = self.stage_model.get_layers_with_opinion(self.node_path,
                                                               INTERNAL_ATTRS.INSTANCE_PATH)
        self.inst_layer_colors = self.stage_model.get_layer_colors(inst_layers)
        self.node_pos = self.stage_model.get_node_pos(self.node_path)
        self.node_comment = self.stage_model.get_node_comment(self.node_path,
                                                              disp_layer)
        self.node_comment_source = self.stage_model.get_node_attr_source(node_path,
                                                                         INTERNAL_ATTRS.COMMENT,
                                                                         disp_layer)
        comment_layers = self.stage_model.get_layers_with_opinion(self.node_path,
                                                                  INTERNAL_ATTRS.COMMENT)
        self.comment_layer_colors = self.stage_model.get_layer_colors(comment_layers)
        self.node_execute = self.stage_model.get_node_exec_in(node_path,
                                                              disp_layer)
        self.node_exec_source = self.stage_model.get_node_attr_source(node_path,
                                                                      INTERNAL_ATTRS.EXECUTE_IN,
                                                                      disp_layer)
        exec_layers = self.stage_model.get_layers_with_opinion(self.node_path,
                                                             INTERNAL_ATTRS.EXECUTE_IN)
        self.exec_layer_colors = self.stage_model.get_layer_colors(exec_layers)

        self.node_enabled = self.stage_model.get_node_enabled(self.node_path)
        enabled_layers = self.stage_model.get_layers_with_opinion(self.node_path,
                                                                  INTERNAL_ATTRS.ENABLED)
        self.enabled_layer_colors = self.stage_model.get_layer_colors(enabled_layers)
        self.node_child_order = self.stage_model.get_node_child_order(node_path,
                                                                      disp_layer)
        co_layers = self.stage_model.get_layers_with_opinion(self.node_path,
                                                             INTERNAL_ATTRS.CHILD_ORDER)
        self.co_layer_colors = self.stage_model.get_layer_colors(co_layers)

        # update general
        self.update_name()
        self.update_properties()
        self.update_styles()
        self.display_properties()

        # update attribute model
        self.model.set_represented_node(node_path=self.node_path)
        self.handle_locking()

    def view_instance_node(self):
        instance_path = self.instance_field.text()
        if instance_path:
            self.stage_model.select_and_frame(instance_path)

    def focus_instance_field(self, in_focus):
        """Ensures the path is not expanded when the instance field gains
        focus. Listens to the custom focus signal.
        :param in_focus: bool
        :return: None
        """
        expand = not in_focus
        if self.instance_field.has_focus:
            return
        if in_focus:
            layer = self.stage_model.target_layer
        else:
            layer = self.stage_model.comp_layer
        path = self.stage_model.get_node_instance_path(self.node_path, layer,
                                                       expand=expand)
        if not path:
            layer = self.stage_model.comp_layer
            comp_path = self.stage_model.get_node_instance_path(self.node_path,
                                                                layer,
                                                                expand=expand)
            if comp_path != path:
                path = comp_path
        if in_focus:
            self.instance_field.focus_in_val = path
        else:
            self.instance_field.focus_in_val = ''
        self.instance_field.setText(path)

    def update_properties(self):
        self.name_label.setText(self.node_name)
        self.path_field.setText(self.node_path)
        self.instance_field.setText(self.node_instance)
        self.instance_opinions.layer_colors = self.inst_layer_colors
        self.positionX_field.setValue(self.node_pos[0])
        self.positionY_field.setValue(self.node_pos[1])
        self.comment_field.setText(self.node_comment)
        self.comment_opinions.layer_colors = self.comment_layer_colors
        self.execute_field.setText(self.node_execute)
        self.execute_opinions.layer_colors = self.exec_layer_colors
        old_signal_state = self.enabled_checkbox.blockSignals(True)
        if self.node_enabled:
            check_box_state = QtCore.Qt.Checked
        else:
            check_box_state = QtCore.Qt.Unchecked
        self.enabled_checkbox.setCheckState(check_box_state)
        self.enabled_checkbox.blockSignals(old_signal_state)
        self.enabled_opinions.layer_colors = self.enabled_layer_colors
        self.child_order_field.setText(' '.join(self.node_child_order))
        self.child_order_opinions.layer_colors = self.co_layer_colors

    def update_styles(self):
        if not self.stage_model or not self.node_path:
            return

        # get colors
        tgt_layer_color = self.stage_model.get_layer_color(
            self.stage_model.target_layer) or 'transparent'

        # style position widgets
        top_layer_color = self.stage_model.get_layer_color(
            self.stage_model.top_layer) or 'transparent'
        pos_style = '''
                    QAbstractSpinBox {
                        background-color: #232323;
                        border: 1px solid transparent;
                        color: #F0F0F0;
                        padding-top: 2px;
                        padding-bottom: 2px;
                        padding-left: 0px;
                        padding-right: 0px;
                        border-radius: 11px;
                    }

                    QAbstractSpinBox:hover {
                        border: 1px solid %s;
                    }

                    QAbstractSpinBox:focus {
                        border: 2px solid %s;
                    }

                    QAbstractSpinBox:up-button {
                        border-left: 0px solid #3E3E3E;
                        padding-right: 6px;
                        padding-top: 3px;
                    }

                    QAbstractSpinBox:down-button {
                        border-left: 0px solid #3E3E3E;
                        padding-right: 6px;
                        padding-bottom: 3px;
                    }
                    ''' % (top_layer_color, top_layer_color)
        self.positionX_field.setStyleSheet(pos_style)
        self.positionY_field.setStyleSheet(pos_style)

        errors = self.stage_model.get_node_error(self.node_path,
                                                 self.stage_model.comp_layer)

        # other fields
        ec = self.stage_model.get_layer_color(self.node_exec_source[0])
        e_s = line_edit_style_factory(ec, tgt_layer_color)
        self.execute_field.setStyleSheet(e_s)
        co_s = line_edit_style_factory(tgt_layer_color=tgt_layer_color)
        self.child_order_field.setStyleSheet(co_s)
        cc = self.stage_model.get_layer_color(self.node_comment_source[0])
        c_s = line_edit_style_factory(cc, tgt_layer_color)
        self.comment_field.setStyleSheet(c_s)

        # instance field
        inst_color = self.stage_model.get_layer_color(self.node_inst_source[0])
        inst_style = line_edit_style_factory(inst_color, tgt_layer_color)
        self.instance_field.setStyleSheet(inst_style)
        for error in errors:
            if error == NODE_ERRORS.INSTANCE:
                error_style = line_edit_style_factory(inst_color,
                                                      tgt_layer_color,
                                                      colors.ERROR.getRgb())
                self.instance_field.setStyleSheet(error_style)
            elif error == NODE_ERRORS.EXEC:
                error_style = line_edit_style_factory(ec,
                                                      tgt_layer_color,
                                                      colors.ERROR.getRgb())
                self.execute_field.setStyleSheet(error_style)
            elif error == NODE_ERRORS.ORPHANS:
                error_style = line_edit_style_factory('white',
                                                      tgt_layer_color,
                                                      colors.ERROR.getRgb())
                self.child_order_field.setStyleSheet(error_style)

    def display_properties(self):
        # display properties if the node path is valid
        if not self.node_path or not self.stage_model:
            self.properties_frame.hide()
        elif self.properties_frame.isHidden():
            self.properties_frame.show()

        # display properties if the node is a root node
        if self.stage_model:
            is_world = self.node_path == nxt_path.WORLD
            is_top = self.stage_model.is_top_node(self.node_path)
            self.name_label.setEnabled(not is_world)
            self.name_edit_button.setVisible(not is_world)

            self.instance_label.setVisible(not is_world)
            self.instance_field.setVisible(not is_world)
            self.locate_instance_button.setVisible(not is_world)
            self.revert_instance_button.setVisible(not is_world)
            self.instance_opinions.setVisible(not is_world)

            self.execute_field.setVisible(is_top)
            self.execute_label.setVisible(is_top)
            self.revert_exec_source_button.setVisible(is_top)
            self.execute_opinions.setVisible(not is_world)


            self.child_order_label.setVisible(not is_world)
            self.child_order_field.setVisible(not is_world)
            self.revert_child_order_button.setVisible(not is_world)
            self.child_order_opinions.setVisible(not is_world)

            self.position_label.setVisible(is_top)
            self.positionX_field.setVisible(is_top)
            self.positionY_field.setVisible(is_top)

            self.enabled_checkbox.setVisible(not is_world)
            self.enabled_checkbox_label.setVisible(not is_world)
            self.revert_enabled_button.setVisible(not is_world)
            self.enabled_opinions.setVisible(not is_world)

    def edit_name(self, new_name):
        self.stage_model.set_node_name(self.node_path, new_name, self.stage_model.target_layer)
        self.node_name = nxt_path.node_name_from_node_path(self.node_path)
        self.update_name()

    def update_name(self):
        self.name_label.setText(self.node_name)

    def edit_instance(self):
        comp_layer = self.stage_model.comp_layer
        target_layer = self.stage_model.target_layer
        if self.stage_model.node_exists(self.node_path, target_layer):
            lookup_layer = target_layer
        else:
            lookup_layer = comp_layer
        cur_inst_path = self.stage_model.get_node_instance_path(self.node_path,
                                                                lookup_layer,
                                                                expand=False)
        cur_inst_path = str(self.instance_field.focus_in_val)
        instance_path = str(self.instance_field.text())
        if (not cur_inst_path and not instance_path
                or cur_inst_path == instance_path):
            # I want to use .isModified() but the completer doesn't count and
            # a modification, I think it internally uses setText - Lucas 2020
            return
        if instance_path is not None:
            self.stage_model.set_node_instance(self.node_path, instance_path,
                                               target_layer)
        elif cur_inst_path is not None:
            self.stage_model.revert_node_instance(self.node_path, target_layer)
        self.update_styles()
        cur_inst_path = self.stage_model.get_node_instance_path(self.node_path,
                                                                comp_layer,
                                                                expand=False)
        self.instance_field.clearFocus()
        self.instance_field.setText(cur_inst_path)

    def edit_exec_source(self):
        comp_layer = self.stage_model.comp_layer
        target_layer = self.stage_model.target_layer
        cur_exec_path = self.stage_model.get_node_exec_in(self.node_path,
                                                          comp_layer)
        source = str(self.execute_field.text())
        if not cur_exec_path and not source or cur_exec_path == source:
            # I want to use .isModified() but the completer doesn't count and
            # a modification, I think it internally uses setText - Lucas 2020
            return
        self.stage_model.set_node_exec_in(self.node_path, source, target_layer)
        real_exec_path = self.stage_model.get_node_exec_in(self.node_path,
                                                           comp_layer)
        self.execute_field.setText(real_exec_path)
        self.update_styles()

    def remove_exec_source(self):
        self.stage_model.set_node_exec_in(self.node_path, None,
                                          self.stage_model.target_layer)

    def accept_edit_child_order(self):
        child_order = self.child_order_field.text().split()
        if self.stage_model:
            self.stage_model.set_node_child_order(self.node_path, child_order)
            self.node_child_order = self.stage_model.get_node_child_order(self.node_path, self.stage_model.comp_layer)
            self.update_properties()

    def cancel_edit_child_order(self):
        self.child_order_field.clearFocus()
        self.update_properties()

    def revert_child_order(self):
        if self.stage_model:
            self.stage_model.revert_child_order(node_path=self.node_path)

    def toggle_node_enabled(self):
        if self.stage_model:
            button_state = True if self.enabled_checkbox.checkState() == \
                                   QtCore.Qt.Checked else False
            self.stage_model.set_node_enabled(self.node_path, button_state)
            return

    def revert_node_enabled(self):
        if self.stage_model:
            self.stage_model.revert_node_enabled(self.node_path)

    def edit_position(self):
        if self.locked:
            return
        x = self.positionX_field.value()
        y = self.positionY_field.value()
        if not self.node_path or not self.stage_model.node_exists(self.node_path, self.stage_model.comp_layer):
            self.clear()
            return
        self.node_pos = (x, y)
        self.stage_model.set_nodes_pos({self.node_path: self.node_pos})

    def accept_edit_comment(self):
        comment = self.comment_field.toPlainText()
        if self.stage_model:
            if (not comment and not self.node_comment
                    or comment == self.node_comment):
                return
            self.stage_model.set_node_comment(self.node_path, comment, self.stage_model.target_layer)
            self.node_comment = self.stage_model.get_node_comment(self.node_path, self.stage_model.comp_layer)
            self.update_properties()

    def cancel_edit_comment(self):
        self.comment_field.blockSignals(True)
        self.comment_field.clearFocus()
        self.comment_field.blockSignals(False)
        self.update_properties()

    def remove_comment(self):
        if self.stage_model:
            self.stage_model.set_node_comment(node_path=self.node_path,
                                              comment=None,
                                              layer=self.stage_model.target_layer)

    def add_attr(self):
        if self.node_path:
            self.stage_model.add_node_attr(node_path=self.node_path,
                                           layer=self.stage_model.target_layer)

    def get_selected_attr_names(self):
        selection = self.table_view.selectedIndexes()
        attr_names = set()
        for index in selection:
            proxy_index = self.proxy_model.mapToSource(index)
            target_row = proxy_index.row()
            attr_names.add(self.model.get_data()[target_row][0])
        return attr_names

    def remove_selected_attrs(self):
        for attr_name in self.get_selected_attr_names():
            self.stage_model.delete_node_attr(node_path=self.node_path,
                                              attr_name=attr_name)

    def copy_selected_attrs(self, data_state):
        attr_names = self.get_selected_attr_names()
        self.stage_model.copy_attrs_val(self.node_path, attr_names, data_state)

    def clear(self):
        # clear data
        self.node_path = str()
        self.node_instance = str()
        self.node_name = str()
        self.node_pos = (float(), float())
        self.node_comment = ''
        self.node_attr_names = list()

        # update general
        self.update_name()
        self.update_properties()
        self.display_properties()

        # update attribute model
        self.model.set_represented_node(node_path=self.node_path)

    def localize_inst_path(self):
        self.instance_field.blockSignals(True)
        self.stage_model.localize_node_instance(self.node_path)
        self.instance_field.blockSignals(False)

    def revert_inst_path(self):
        self.instance_field.blockSignals(True)
        comp_layer = self.stage_model.comp_layer
        cur_inst_path = self.stage_model.get_node_instance_path(self.node_path,
                                                                comp_layer,
                                                                expand=False)
        if cur_inst_path is not None:
            self.stage_model.revert_node_instance(self.node_path)
        self.instance_field.blockSignals(False)

    def localize_exec_path(self):
        self.execute_field.blockSignals(True)
        self.stage_model.localize_node_in_exec_source(self.node_path)
        self.execute_field.blockSignals(False)

    def revert_exec_path(self):
        self.execute_field.blockSignals(True)
        comp_layer = self.stage_model.comp_layer
        cur_inst_path = self.stage_model.get_node_exec_in(self.node_path,
                                                          comp_layer)
        if cur_inst_path:
            self.stage_model.set_node_exec_in(self.node_path, None)
        self.execute_field.blockSignals(False)

    def localize_attrs(self):
        data = self.model._data
        path = self.node_path
        attr_names = list()
        for index in self.model.selected_indexes:
            attr_names.append(data[index.row()][0])
        self.stage_model.localize_node_attrs(path, attr_names)

    def revert_attrs(self):
        data = self.model._data
        path = self.node_path
        attr_names = list()
        for index in self.model.selected_indexes:
            attr_names.append(data[index.row()][0])
        self.stage_model.revert_node_attrs(path, attr_names)

    def custom_context_menu(self, pos):
        index = self.table_view.indexAt(pos)
        if not index.isValid:
            return
        index = self.proxy_model.mapToSource(index)
        name = index.sibling(index.row(), COLUMNS.name).data()
        if index.column() != COLUMNS.source:
            try:
                locality = self.model._data[index.row()][COLUMNS.locality]
            except IndexError:
                locality = None
            menu = QtWidgets.QMenu(self)
            menu.addAction(self.add_attr_action)
            if index.row() != -1:
                menu.addAction(self.remove_attr_action)
                menu.addSeparator()
                menu.addAction(self.localize_attr_action)
                path = self.node_path
                hist_func = self.stage_model.get_historical_opinions
                if locality == LOCALITIES.local and hist_func(path, name):
                    menu.addAction(self.revert_attr_action)
            if index.column() == COLUMNS.value:
                menu.addSeparator()
                menu.addAction(self.copy_raw_action)
                menu.addAction(self.copy_resolved_action)
                menu.addAction(self.copy_cached_action)
        else:
            menu = HistoricalContextMenu(self, self.node_path, name,
                                         self.stage_model)
        menu.popup(QtGui.QCursor.pos())

    def reset_action_enabled(self, actions):
        if self.locked:
            return
        for action in actions:
            action.setEnabled(True)

    def instance_context_menu(self):
        self.instance_field.clearFocus()
        l_inst = self.instance_field
        menu = QtWidgets.QLineEdit.createStandardContextMenu(l_inst)
        menu.addAction(self.localize_inst_path_action)
        menu.addAction(self._actions.revert_inst_path_action)
        if not l_inst.text():
            self.localize_inst_path_action.setEnabled(False)
        link_to = HistoricalContextMenu.LINKS.SOURCE
        historical_menu = HistoricalContextMenu(self, self.node_path,
                                                INTERNAL_ATTRS.INSTANCE_PATH,
                                                self.stage_model,
                                                truncate_left=True,
                                                link_to=link_to)
        menu.addMenu(historical_menu)

        menu.popup(QtGui.QCursor.pos())
        menu.aboutToHide.connect(partial(self.reset_action_enabled,
                                         menu.actions()))

    def exec_context_menu(self):
        self.execute_field.clearFocus()
        l_exec = self.execute_field
        menu = QtWidgets.QLineEdit.createStandardContextMenu(l_exec)
        menu.addAction(self.localize_exec_path_action)
        menu.addAction(self.revert_exec_path_action)
        layer, src_path = self.stage_model.get_node_attr_source(self.node_path,
                                                                INTERNAL_ATTRS.EXECUTE_IN,
                                                                self.stage_model.comp_layer)
        tgt_path = self.stage_model.target_layer.real_path
        exec_is_path_local = (src_path == self.node_path) and (layer == tgt_path)
        self.localize_exec_path_action.setEnabled(not exec_is_path_local and not self.locked)
        self.revert_exec_path_action.setEnabled(exec_is_path_local and not self.locked)
        link_to = HistoricalContextMenu.LINKS.SOURCE
        historical_menu = HistoricalContextMenu(self, self.node_path,
                                                INTERNAL_ATTRS.EXECUTE_IN,
                                                self.stage_model,
                                                truncate_left=True,
                                                link_to=link_to)
        menu.addMenu(historical_menu)
        menu.popup(QtGui.QCursor.pos())
        menu.aboutToHide.connect(partial(self.reset_action_enabled,
                                         menu.actions()))


class PropertyModel(QtCore.QAbstractTableModel):
    """Property Editor model"""

    def __init__(self, parent=None, graph_model=None, node_path=None, view=None, headers=None):
        """Initialize the data structure and get header labels.

        Data Structure
        ##############
        attributes:
            <attributeName>:
                cached_value: <value>
                dirty: <bool>
                type: <value>
                value: <value>
                runtime: <bool>

        :param graph_model:
        :param parent:
        """
        super(PropertyModel, self).__init__()

        # incoming data
        self.parent = parent
        self.stage_model = graph_model
        self.node_path = node_path
        self.view = view
        self.headers = headers

        # local attributes
        self.node_attr_names = []
        self.node_attr_draw_details = {}
        self.attr_data = []
        self.attr_data_resolved = []
        self.attr_data_cached = []
        self.selected_indexes = []
        self.horizontal_header = self.view.horizontalHeader()
        self.state = None
        self.horizontal_header.sortIndicatorChanged.connect(self.save_state)
        self.horizontal_header.sectionResized.connect(self.save_state)
        # set default data
        self._data = [[]]

    @property
    def resolved(self):
        return self.stage_model.data_state

    def set_represented_node(self, node_path=None):
        """Sends node data for selected node to the model.

        :param node_path:
        :return:
        """
        comp_layer = self.stage_model.comp_layer
        stage_model = self.stage_model
        self.node_path = node_path
        if not self.node_path or not stage_model.node_exists(node_path,
                                                             comp_layer):
            self.clear()
            return

        # get attribute model data
        local_attrs = stage_model.get_node_local_attr_names(node_path,
                                                            comp_layer)
        local_attrs = sorted(local_attrs)
        parent_attrs = stage_model.get_node_inherited_attr_names(node_path,
                                                                 comp_layer)
        parent_attrs = sorted(parent_attrs)
        inst_attrs = stage_model.get_node_instanced_attr_names(node_path,
                                                               comp_layer)
        inst_attrs = sorted(inst_attrs)
        self.node_attr_names = []
        for attr_list in (local_attrs, parent_attrs, inst_attrs):
            for attr in attr_list:
                if attr not in self.node_attr_names:
                    self.node_attr_names += [attr]
        cached_attrs = stage_model.get_cached_attr_names(node_path)
        if stage_model.data_state == DATA_STATE.CACHED:
            for attr_name in cached_attrs:
                if attr_name not in self.node_attr_names:
                    self.node_attr_names += [attr_name]
        self.attr_data = []
        self.attr_data_resolved = []
        self.attr_data_cached = []
        for attr_name in self.node_attr_names:
            # get cached data
            cached = DATA_STATE.CACHED
            attr_cached = stage_model.get_node_attr_value(self.node_path,
                                                          attr_name,
                                                          data_state=cached,
                                                          as_string=True)
            self.attr_data_cached += [attr_cached]
            # get resolved data
            resolved = DATA_STATE.RESOLVED
            resolved_val = stage_model.get_node_attr_value(node_path,
                                                           attr_name,
                                                           comp_layer,
                                                           data_state=resolved)
            self.attr_data_resolved += [resolved_val]

            # Get locality
            if attr_name in local_attrs:
                locality = LOCALITIES.local
            elif attr_name in parent_attrs:
                locality = LOCALITIES.inherited
            elif attr_name in inst_attrs:
                locality = LOCALITIES.instanced
            elif attr_name in cached_attrs:
                locality = LOCALITIES.code
            # get raw data
            raw = DATA_STATE.RAW
            attr_value = stage_model.get_node_attr_value(node_path, attr_name,
                                                         comp_layer,
                                                         data_state=raw,
                                                         as_string=True)
            type_layer = comp_layer
            if (stage_model.data_state == DATA_STATE.CACHED and
                stage_model.current_rt_layer):
                type_layer = stage_model.current_rt_layer.cache_layer
            attr_type = stage_model.get_node_attr_type(node_path, attr_name,
                                                       type_layer)
            if locality == LOCALITIES.code:
                attr_source = node_path
            else:
                attr_source = stage_model.get_node_attr_source_path(node_path,
                                                                    attr_name,
                                                                    comp_layer)
            attr_comment = stage_model.get_node_attr_comment(node_path,
                                                             attr_name,
                                                             comp_layer)
            # add data row
            row_dict = {COLUMNS.name: attr_name,
                        COLUMNS.value: attr_value,
                        COLUMNS.nxt_type: attr_type,
                        COLUMNS.source: attr_source,
                        COLUMNS.locality: locality,
                        COLUMNS.comment: attr_comment}
            row_data = COLUMNS.column_dict_to_list(row_dict)
            self.attr_data += [row_data]

            # get draw details for this attr
            color = stage_model.get_node_attr_color(node_path, attr_name,
                                                    comp_layer)
            self.node_attr_draw_details[attr_name] = {'color': color}

        # set model data
        self.horizontal_header.sortIndicatorChanged.disconnect(self.save_state)
        self.horizontal_header.sectionResized.disconnect(self.save_state)
        self.beginResetModel()
        self._data = self.attr_data if self.attr_data else [[]]
        self.endResetModel()
        self.horizontal_header.sortIndicatorChanged.connect(self.save_state)
        self.horizontal_header.sectionResized.connect(self.save_state)

        # header settings
        # TODO Why on earth is the model touching the view like this?
        if self.attr_data:
            self.horizontal_header.setSectionResizeMode(COLUMNS.name,
                                                        QtWidgets.QHeaderView.Interactive)
            self.horizontal_header.setSectionResizeMode(COLUMNS.value,
                                                        QtWidgets.QHeaderView.Interactive)
            self.horizontal_header.setSectionResizeMode(COLUMNS.nxt_type,
                                                        QtWidgets.QHeaderView.Fixed)
            self.horizontal_header.setSectionResizeMode(COLUMNS.source,
                                                        QtWidgets.QHeaderView.Interactive)
            self.horizontal_header.setSectionResizeMode(COLUMNS.locality,
                                                        QtWidgets.QHeaderView.Interactive)
            self.horizontal_header.setSectionResizeMode(COLUMNS.comment,
                                                        QtWidgets.QHeaderView.Interactive)
            self.horizontal_header.setSortIndicatorShown(True)

            # column widths
            if self.state:
                if sys.version_info[0] > 2 and isinstance(self.state, str):
                    self.state = bytes(self.state, 'utf-8')
                try:
                    self.horizontal_header.restoreState(self.state)
                except TypeError:
                    logger.error('Corrupted property editor pref!')
                    self.state = ''
            self.view.resizeColumnToContents(COLUMNS.nxt_type)

    def get_data(self):
        return self._data

    def clear(self):
        self.beginResetModel()
        self._data = [[]]
        self.endResetModel()

    def save_state(self):
        self.state = self.horizontal_header.saveState()
        col = self.horizontal_header.sortIndicatorSection()
        order = self.horizontal_header.sortIndicatorOrder().name
        state = {'column': int(col),
                 'order':  str(order)}
        if state == self.parent.user_sort_pref:
            return
        user_dir.user_prefs[self.parent.PREF_KEY] = state
        self.parent.user_sort_pref = state

    def setData(self, index, value, role=None):
        if not index.isValid:
            return False

        row = index.row()
        column = index.column()
        if value == self.attr_data[row][column] and column != COLUMNS.source:
            return False

        attr_name = str(self._data[row][COLUMNS.name])

        # set attr name
        if role == QtCore.Qt.EditRole and column == COLUMNS.name:
            self.stage_model.rename_node_attr(node_path=self.node_path,
                                              attr_name=attr_name,
                                              new_attr_name=value,
                                              layer=self.stage_model.target_layer)
            return True

        # set attr value
        elif role == QtCore.Qt.EditRole and column == COLUMNS.value:
            if value == self.attr_data[row][column]:
                return False

            self.stage_model.set_node_attr_value(node_path=self.node_path,
                                                 attr_name=attr_name,
                                                 value=value,
                                                 layer=self.stage_model.target_layer)
            return True

        # set attr comment
        elif role == QtCore.Qt.EditRole and column == COLUMNS.comment:
            self.stage_model.node_setattr_comment(self.node_path, attr_name,
                                                  value,
                                                  self.stage_model.target_layer)
            return True
        elif role == QtCore.Qt.CheckStateRole and column == COLUMNS.source:
            self.stage_model.select_and_frame(value)
            return True

        return False

    def data(self, index, role=None):
        if not index.isValid:
            return None

        row = index.row()
        column = index.column()
        cached_state = DATA_STATE.CACHED
        resolved_state = DATA_STATE.RESOLVED
        if role is None:
            return self._data[row][column]
        if role == QtCore.Qt.BackgroundRole and column == COLUMNS.value:
            try:
                unresolved_data = self._data[row][column]
            except IndexError:
                unresolved_data = None
            try:
                cached_data = self.attr_data_cached[row]
            except IndexError:
                cached_data = None
            in_cached_state = self.stage_model.data_state == cached_state
            if in_cached_state and not cached_data:
                color = colors.UNCACHED_RED
                return QtGui.QBrush(color, QtCore.Qt.BDiagPattern)
        if role == QtCore.Qt.DisplayRole:
            state = self.stage_model.data_state
            if column == COLUMNS.value and state is resolved_state:
                try:
                    return self.attr_data_resolved[row]
                except IndexError:
                    return None
            elif column == COLUMNS.value and state is cached_state:
                try:
                    unresolved_data = self._data[row][column]
                    cached_data = self.attr_data_cached[row]
                    invalid_cache = unresolved_data and not cached_data
                    if invalid_cache:
                        return unresolved_data
                    else:
                        return cached_data
                except IndexError:
                    return None
            else:
                return self._data[row][column]

        if role == QtCore.Qt.ToolTipRole:
            if column == COLUMNS.value:
                value = '   value : ' + (',\n ' + (' ' * 10)).join(
                    textwrap.wrap(self._data[row][COLUMNS.value], 100))
                resolved_state = 'resolved : ' + (',\n ' + (' ' * 10)).join(
                    textwrap.wrap(str(self.attr_data_resolved[row]), 100))
                cached_state = '  cached : ' + (',\n ' + (' ' * 10)).join(
                    textwrap.wrap(str(self.attr_data_cached[row]), 100))
                return '\n'.join([value, resolved_state, cached_state])
            elif column == COLUMNS.source:
                path = self.node_path
                name = index.sibling(index.row(), COLUMNS.name).data()
                historicals = self.stage_model.get_historical_opinions(path,
                                                                       name)
                lines = []
                for historical in historicals:
                    _, source = historical.get(META_ATTRS.SOURCE)
                    val = historical.get(META_ATTRS.VALUE)
                    if len(val) > 50:
                        val = val[:50] + '...'
                    text = source + '.' + name + '\t' + val
                    lines += [text]
                if not historicals:
                    lines = ['No Historical Opinions']
                return '\n'.join(lines)

        if role == QtCore.Qt.ForegroundRole:
            attr_name = self._data[row][COLUMNS.name]
            locality_idx = self._data[row][COLUMNS.locality]
            color = self.node_attr_draw_details[attr_name]['color']
            if locality_idx in (LOCALITIES.local, LOCALITIES.code):
                return QtGui.QColor(color).lighter(150)
            else:
                return QtGui.QColor(color).darker(150)

        if role == QtCore.Qt.FontRole:
            if self._data[row][COLUMNS.locality] == LOCALITIES.instanced:
                font = QtGui.QFont()
                font.setItalic(True)
                return font

        if role == QtCore.Qt.DecorationRole and column == COLUMNS.nxt_type:
            attr_type = self._data[row][column]
            color = colors.ATTR_COLORS.get(attr_type, QtCore.Qt.gray)
            icon = QtGui.QPixmap(QtCore.QSize(10, 10))
            icon.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(icon)
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setBrush(color)
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawEllipse(QtCore.QPointF(7, 5), 3, 3)
            del painter
            return icon

        if role == QtCore.Qt.EditRole:
            return self._data[row][column]

    def flags(self, index):
        column = index.column()
        if column in (COLUMNS.name, COLUMNS.value, COLUMNS.comment):
            return QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable | \
                   QtCore.Qt.ItemIsEditable
        elif column == COLUMNS.nxt_type:
            return QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
        elif column == COLUMNS.source:
            return QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
        else:
            return QtCore.Qt.NoItemFlags

    def headerData(self, section, orientation, role):
        if orientation == QtCore.Qt.Horizontal:
            if role == QtCore.Qt.DisplayRole:
                return self.headers[section]

    def rowCount(self, parent):
        return len(self._data)

    def columnCount(self, parent):
        return len(self._data[0])


class AttrsTableView(QtWidgets.QTableView):
    def __init__(self, parent=None):
        super(AttrsTableView, self).__init__(parent=parent)
        self.node_path_delegate = NodePathBtnDelegate(self)
        self.setItemDelegateForColumn(COLUMNS.source, self.node_path_delegate)
        self.mouse_pressed = False
        self.drag_start_pos = None
        self.setDragEnabled(True)
        self.setMouseTracking(True)
        self.installEventFilter(self)

    def mousePressEvent(self, event):
        super(AttrsTableView, self).mousePressEvent(event)
        self.mouse_pressed = self.indexAt(event.pos())
        self.startDrag(event)

    def mouseReleaseEvent(self, event):
        super(AttrsTableView, self).mouseReleaseEvent(event)
        self.mouse_pressed = False
        self.drag_start_pos = None

    def mouseMoveEvent(self, event):
        super(AttrsTableView, self).mouseMoveEvent(event)
        if not self.drag_start_pos or not self.mouse_pressed:
            return
        start_drag_dist = QtWidgets.QApplication.startDragDistance()
        drag_delta = (event.pos() - self.drag_start_pos).manhattanLength()
        if drag_delta >= start_drag_dist:
            drag = QtGui.QDrag(self)
            mime_data = QtCore.QMimeData()
            attr_name = self.get_attr_name()
            if attr_name is None:
                return
            token = tokens.make_token_str(attr_name)
            mime_data.setText(token)
            drag.setMimeData(mime_data)
            drag.exec_()
            self.drag_start_pos = None

    def dragEnterEvent(self, event):
        event.setDropAction(QtCore.Qt.LinkAction)
        event.accept()

    def startDrag(self, event):
        self.drag_start_pos = None
        if not self.mouse_pressed:
            return
        self.drag_start_pos = event.pos()

    def get_attr_name(self):
        if not self.mouse_pressed:
            return
        idx = self.model().index(self.mouse_pressed.row(), COLUMNS.name)
        return self.model().data(idx)


class NodePathBtnDelegate(QtWidgets.QStyledItemDelegate):

    def __init__(self, parent):
        self.parent = parent
        super(NodePathBtnDelegate, self).__init__()

    def paint(self, painter, option, index):
        self.initStyleOption(option, index)
        inner_rect = QtCore.QRect().united(option.rect)
        inner_rect = inner_rect.marginsRemoved(QtCore.QMargins(1, 1, 1, 1))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(option.backgroundBrush)
        attr_name = index.sibling(index.row(), COLUMNS.name).data()
        model = index.model().sourceModel()
        color = model.node_attr_draw_details[attr_name]['color']
        color = QtGui.QColor(color)
        painter.setPen(color)
        if option.state & QtWidgets.QStyle.State_MouseOver:
            if self.parent.mouse_pressed == index.column():
                color.setAlpha(110)
            else:
                color.setAlpha(80)
        else:
            color.setAlpha(50)
        painter.fillRect(inner_rect, color)
        color.setAlpha(255)
        painter.drawText(inner_rect, QtCore.Qt.AlignCenter, index.data())

    def editorEvent(self, event, model, option, index):
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return False
        if event.type() != QtCore.QEvent.Type.MouseButtonRelease:
            return False
        model.setData(index, index.data(), role=QtCore.Qt.CheckStateRole)
        return True


class HistoricalContextMenu(QtWidgets.QMenu):
    class LINKS(object):
        SOURCE = 'source'
        VALUE = 'value'

    def __init__(self, parent, node_path, attr_name, stage_model,
                 title='Historical Values', label_fmt=None,
                 link_to=LINKS.SOURCE, truncate_left=False):
        self.colors = []
        self.mouse_pos = QtCore.QPoint(0, 0)
        self.mouse_pressed = False
        super(HistoricalContextMenu, self).__init__(title=title, parent=parent)
        self.add_historcal_value_actions(node_path, attr_name, stage_model,
                                         truncate_left, link_to, label_fmt)

    def mouseMoveEvent(self, event):
        super(HistoricalContextMenu, self).mouseMoveEvent(event)
        self.mouse_pos = event.pos()

    def mousePressEvent(self, event):
        super(HistoricalContextMenu, self).mousePressEvent(event)
        self.mouse_pressed = True

    def mouseReleaseEvent(self, event):
        super(HistoricalContextMenu, self).mouseReleaseEvent(event)
        self.mouse_pressed = False

    def paintEvent(self, event):
        painter = QtGui.QPainter()
        fm = QtGui.QFontMetrics(self.font())
        painter.begin(self)
        y = 0
        y_txt = fm.height() * .5

        self.rect().setHeight(self.rect().height() + y)
        step = self.rect().height() / len(self.actions())
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        data = []
        x_offset = self.rect().width()
        option = QtWidgets.QStyleOptionButton()
        option.initFrom(self)
        for action in self.actions():
            color = getattr(action, 'color', '#232323')
            rect = QtCore.QRect(0, y, self.rect().width(), step)
            x = fm.boundingRect(action.text()).width()
            x_pos = (rect.width() - x) * .5
            if x_pos < x_offset:
                x_offset = x_pos
            item_data = {'rect': rect, 'color': color, 'text': action.text(),
                         'y': y}
            data += [item_data]
            y += step

        for item_data in data:
            color = QtGui.QColor(item_data['color'])
            rect = item_data['rect']
            if rect.contains(self.mouse_pos):
                if self.mouse_pressed:
                    mult = 110
                else:
                    mult = 80
                color.setAlpha(mult)
            else:
                color.setAlpha(50)
            painter.fillRect(rect, color)
            color = QtCore.Qt.white
            painter.setPen(color)
            painter.drawText(x_offset, rect.height() - y_txt +
                             item_data['y'], item_data['text'])

        painter.end()

    def add_historcal_value_actions(self, node_path, attr_name,
                                    stage_model, truncate_left=False,
                                    link_to=LINKS.SOURCE, label_fmt=None):
        """Adds menu actions representing each historical value for the given
        node_path and attr_name. If truncate_left is True the any characters
        over the HISTORICAL_MAX_CHARS limit will be removed from the left of the
        string. Otherwise they will be removed from the right.
        Default text_mode will result in: "/node.attr  123"
        :param node_path: String of node path
        :param attr_name: String of attr name
        :param stage_model: StageModel
        :param link_to: LINKS.SOURCE or LINKS.VALUE tells the stage model
        what data to try and select and focus to
        :param label_fmt: String ready for formatting
            i.e.: '{source}.{attr_name}  {value}'
        Valid format keys are:
                source
                attr_name
                value
        :param truncate_left: bool
        :return: None
        """
        if attr_name != INTERNAL_ATTRS.INSTANCE_PATH:
            historicals = stage_model.get_historical_opinions(node_path,
                                                              attr_name)
        else:
            historicals = stage_model.get_instance_trace(node_path)
        if not historicals:
            action = self.addAction('No Historical Opinions')
            action.setEnabled(False)
        if attr_name in INTERNAL_ATTRS.SAVED:
            attr_name = INTERNAL_ATTRS.as_save_key(attr_name)
        for historical in historicals:
            layer, source = historical.get(META_ATTRS.SOURCE)
            color = stage_model.get_layer_color(layer)
            val = historical.get(META_ATTRS.VALUE) or ''
            char_count = len(val)
            if link_to == self.LINKS.SOURCE:
                link = source
            else:
                link = val
            if char_count > HISTORICAL_MAX_CHARS:
                if truncate_left:
                    val = '...' + val[char_count - HISTORICAL_MAX_CHARS:]
                else:
                    val = val[:HISTORICAL_MAX_CHARS] + '...'
            if label_fmt is None:
                pref_key = user_dir.USER_PREF.HISTORICAL_LABEL_FORMAT
                default_fmt = '{source}.{attr_name}  {value}'
                label_fmt = user_dir.user_prefs.get(pref_key, default_fmt)
            text = label_fmt.format(source=source, attr_name=attr_name,
                                    value=val)
            func = partial(stage_model.select_and_frame, link)
            action = self.addAction(text, func)
            action.color = color


class NodePositionSpinbox(QtWidgets.QSpinBox):
    stepChanged = QtCore.Signal()

    def stepBy(self, step):
        value = self.value()
        super(QtWidgets.QSpinBox, self).stepBy(step)
        if self.value() != value:
            self.stepChanged.emit()


class LineEdit(QtWidgets.QLineEdit):
    accept = QtCore.Signal()
    cancel = QtCore.Signal()
    focus_changed = QtCore.Signal(bool)

    def __init__(self, parent=None):
        # Cheat because hasFocus is the parent not the actual line
        self.has_focus = False
        self.focus_in_val = ''
        super(LineEdit, self).__init__(parent)

    def keyPressEvent(self, event):
        # accept edit
        if event.key() in (QtCore.Qt.Key_Enter, QtCore.Qt.Key_Return):
            self.accept.emit()
            self.clearFocus()

        # cancel edit
        elif event.key() == QtCore.Qt.Key_Escape:
            self.cancel.emit()

        # pass
        else:
            return QtWidgets.QLineEdit.keyPressEvent(self, event)

    def focusInEvent(self, event):
        super(LineEdit, self).focusInEvent(event)
        self.focus_changed.emit(True)
        self.has_focus = True

    def focusOutEvent(self, event):
        super(LineEdit, self).focusOutEvent(event)
        self.has_focus = False
        self.focus_changed.emit(False)


class TextEdit(QtWidgets.QTextEdit):

    accept = QtCore.Signal()
    cancel = QtCore.Signal()

    def __init__(self, parent, name):
        super(TextEdit, self).__init__(parent=parent)
        self.layer_colors = []
        self.setObjectName(name)

    def focusOutEvent(self, event):
        super(TextEdit, self).focusOutEvent(event)
        self.accept.emit()


class OverlayWidget(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super(OverlayWidget, self).__init__(parent)
        self._parent = parent
        self.ext_color = QtGui.QColor(62, 62, 62, 190)
        self.base_color = QtGui.QColor(62, 62, 62, 0)
        self.main_color = self.base_color
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.data_state = ''

    def paintEvent(self, event):
        painter = QtGui.QPainter()
        painter.begin(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        # actual_display_state
        self.data_state = DATA_STATE.RAW
        if self.data_state == DATA_STATE.RAW:
            color = QtGui.QColor(100, 0, 0, 200)
            painter.fillRect(self.parent().rect(),
                             QtGui.QBrush(color, QtCore.Qt.BDiagPattern))
        painter.end()

    def update(self):
        self.setGeometry(self.parent().rect())
        super(OverlayWidget, self).update()


class LOCALITIES:
    code = '0.Code'
    local = '1.Local'
    inherited = '2.Parent'
    instanced = '3.Inst'


class COLUMNS:
    name = 0
    value = 1
    nxt_type = 2
    source = 3
    locality = 4
    comment = 5

    @classmethod
    def column_dict_to_list(cls, columns_dict):
        """Helper method for sorting row data correctly. This allows for
        easy changes to row data in the future.
        """
        columns = ['', '', '', '', '', '']
        for k, v in columns_dict.items():
            columns[k] = v
        return columns


def line_edit_style_factory(txt_color='white', tgt_layer_color='white',
                            bg_color='#232323'):
    """Generates a string of a qss style sheet for a line edit. Colors can be
    supplied as strings of color name or hex value. If a color arg receives
    a tuple we assume it is either an rgb or rgba tuple.
    :param txt_color: Color the text of the line edit should be.
    :param tgt_layer_color: The color of the current target layer.
    :param bg_color: The color that will fill the background of the line eidit.
    :return: string of qss
    """

    def handle_rgb(color_tuple):
        """Assumes the tuple is rgba or rgb (len 4 or 3)"""
        val = ','.join([str(i) for i in color_tuple])
        if len(color_tuple) == 4:
            rgb = 'rgba({})'.format(val)
        else:
            rgb = 'rgb({})'.format(val)
        return rgb
    if isinstance(bg_color, tuple):
        bg_color = handle_rgb(bg_color)
    style = '''
                QTextEdit,
                QLineEdit {
                    border-radius: 11px;
                    border: 1px solid transparent;
                    background-color: %s;
                    color: %s
                }

                QTextEdit:hover,
                QLineEdit:hover {
                    border: 1px solid %s
                }

                QTextEdit:focus,
                QLineEdit:focus {
                    border: 2px solid %s
                }
                ''' % (bg_color, txt_color, tgt_layer_color,
                       tgt_layer_color)
    return style
