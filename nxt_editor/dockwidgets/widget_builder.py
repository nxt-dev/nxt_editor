# Built-in
import logging
import ast
try:
    from collections.abc import Iterable
except ImportError:
    from collections import Iterable

# External
from Qt import QtWidgets
from Qt import QtGui
from Qt import QtCore
# Maya fix
try:
    QtCore.QStringListModel
except AttributeError:
    del QtCore
    from PySide2 import QtCore

# Internal
import nxt_editor
from nxt_editor import user_dir
from nxt_editor.dockwidgets.dock_widget_base import DockWidgetBase
from nxt import DATA_STATE, nxt_path
from nxt import nxt_node

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

WINDOW_ATTR = '_widget_window'
WIDGET_TYPES = ['window', 'tab', 'panel', 'gridLayout', 'button', 'menuItem',
                'dropDownMenu', 'checkbox']
RECOMP_PREF = user_dir.USER_PREF.RECOMP_PREF


class WidgetBuilder(DockWidgetBase):

    WINDOW_TITLE_ATTR = 'window_title'
    WINDOW_COLOR_ATTR = 'background_color'

    def __init__(self, graph_model=None, title='Workflow Tools', parent=None,
                 minimum_width=50, minimum_height=50):
        super(WidgetBuilder, self).__init__(title=title,
                                            parent=parent,
                                            minimum_width=minimum_width,
                                            minimum_height=minimum_height)

        self.updating = False
        self.setObjectName('Workflow Tools')
        self.default_title = title

        # local attributes
        self.main_window = parent
        self.stage_model = graph_model
        self.window_node_path = None
        self.window_title = None

        # state attributes
        self.widget_state_data = {}
        self.tab_widgets = []
        self.scroll_pos = 0

        # main layout
        self.main = QtWidgets.QWidget(parent=self)
        self.setWidget(self.main)

        self.layout = QtWidgets.QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.main.setLayout(self.layout)

        # background frame
        self.background_frame = QtWidgets.QFrame(self)
        self.background_frame.setStyleSheet(
            'QFrame {background-color: #3E3E3E; border-radius: 0px;}')
        self.layout.addWidget(self.background_frame)

        self.background_layout = QtWidgets.QVBoxLayout()
        self.background_layout.setContentsMargins(4, 4, 4, 4)
        self.background_frame.setLayout(self.background_layout)

        # window
        self.window_frame = QtWidgets.QFrame(self)
        self.background_layout.addWidget(self.window_frame)

        self.window_layout = QtWidgets.QVBoxLayout()
        self.window_layout.setContentsMargins(4, 4, 0, 4)
        self.window_layout.setSpacing(0)
        self.window_frame.setLayout(self.window_layout)

        # scroll area
        self.scroll_area = QtWidgets.QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.window_layout.addWidget(self.scroll_area)

        self.scroll_widget = QtWidgets.QWidget(self.window_frame)
        self.scroll_area.setWidget(self.scroll_widget)

        self.scroll_layout = QtWidgets.QVBoxLayout(self.scroll_widget)
        self.scroll_layout.setContentsMargins(0, 0, 4, 0)
        self.scroll_layout.setSpacing(4)
        self.scroll_layout.setAlignment(QtCore.Qt.AlignTop)
        self.scroll_widget.setLayout(self.scroll_layout)
        # Context menu
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.context_menu)

        # update
        self.update_window()

    def context_menu(self):
        menu = QtWidgets.QMenu(self)
        refresh_action = menu.addAction('Refresh')
        refresh_action.triggered.connect(self.update_window)
        menu.addAction(self.main_window.execute_actions.wt_recomp_action)
        menu.popup(QtGui.QCursor.pos())

    def show(self):
        super(WidgetBuilder, self).show()
        self.update_window()

    def set_stage_model(self, stage_model):
        super(WidgetBuilder, self).set_stage_model(stage_model)
        if self.stage_model:
            self.tab_widgets = []
            self.update_window()

    def set_stage_model_connections(self, model, connect):
        self.model_signal_connections = [
            (model.nodes_changed, self.update_window),
            (model.attrs_changed, self.update_window),
            (model.comp_layer_changed, self.update_window),
            (model.executing_changed, self.on_executing_changed)
        ]
        super(WidgetBuilder, self).set_stage_model_connections(model, connect)

    def on_executing_changed(self, state):
        self.window_frame.setVisible(not state)

    def on_stage_model_destroyed(self):
        super(WidgetBuilder, self).on_stage_model_destroyed()
        self.tab_widgets = []
        self.window_frame.hide()

    def build_widgets(self, node_path, layout):
        child_paths = self.stage_model.get_children(
            node_path=node_path,
            layer=self.stage_model.comp_layer,
            ordered=True)
        for child_path in child_paths:
            if not self.stage_model.get_node_enabled(child_path):
                self.build_widgets(node_path=child_path, layout=layout)
                continue

            widget_type = get_widget_type(child_path, self.stage_model)
            # tabs
            if widget_type == 'tab':
                # get existing tab widget
                count = layout.count()
                tab_widget = None
                if count:
                    for child_index in range(count):
                        child_item = layout.itemAt(child_index)
                        if not child_item:
                            continue
                        child_widget = child_item.widget()
                        if child_widget.__class__.__name__ == 'QTabWidget':
                            tab_widget = child_widget

                # create new tab widget
                if not tab_widget:
                    tab_widget = QtWidgets.QTabWidget(self)
                    tab_widget.setContextMenuPolicy(
                        QtCore.Qt.CustomContextMenu)
                    tab_widget.customContextMenuRequested.connect(
                        lambda: self.tab_context_menu(tab_widget))
                    tab_widget.currentChanged.connect(
                        lambda: self.set_tab_style(tab_widget))
                    tab_widget.currentChanged.connect(
                        lambda: self.set_tab_index(tab_widget))
                    layout.addWidget(tab_widget)
                    tab_widget_path = 'tab_widget_' + str(len(self.tab_widgets))
                    tab_widget.tab_widget_path = tab_widget_path
                else:
                    tab_widget_path = tab_widget.tab_widget_path

                # create tab
                tab_widget.blockSignals(True)
                widget = Tab(node_path=child_path,
                             tab_parent=tab_widget,
                             parent=self)
                tab_widget.blockSignals(False)
                self.build_widgets(node_path=child_path, layout=widget.layout)

                # set tab state
                data = self.widget_state_data.get(tab_widget_path)
                if data:
                    if data['widget_type'] == widget_type:
                        state = data.get('state', 0)
                        tab_widget.setCurrentIndex(state)
                    else:
                        data['widget_type'] = widget_type
                        data['state'] = tab_widget.currentIndex()
                    data['widget'] = self
                else:
                    data = {'widget_type': widget_type,
                            'widget': tab_widget,
                            'state': tab_widget.currentIndex()}
                    self.widget_state_data[tab_widget_path] = data
                self.set_tab_style(tab_widget)

            # panels
            elif widget_type == 'panel':
                widget = Panel(node_path=child_path, parent=self)
                layout.addWidget(widget)
                self.build_widgets(node_path=child_path, layout=widget.layout)

            # grid layouts
            elif widget_type == 'gridLayout':
                widget = GridLayout(node_path=child_path, parent=self)
                layout.addWidget(widget)
                self.build_widgets(node_path=child_path, layout=widget.layout)

            # buttons
            elif widget_type == 'button':
                widget = Button(node_path=child_path, parent=self)
                layout.addWidget(widget)
                self.build_widgets(node_path=child_path, layout=layout)

            # checkboxes
            elif widget_type == 'checkbox':
                widget = CheckBox(node_path=child_path, parent=self)
                layout.addWidget(widget)

            # drop-down menus
            elif widget_type == 'dropDownMenu':
                widget = DropDownMenu(node_path=child_path, parent=self)
                layout.addWidget(widget)

            # unrecognized node
            else:
                self.build_widgets(node_path=child_path, layout=layout)
            self.stage_model.process_events()  # Visually update

    def get_window_node_path(self):
        if not self.stage_model:
            return
        if not self.stage_model.comp_layer:
            return

        all_node_paths = self.stage_model.comp_layer.descendants()
        window_nodes = []
        for node_path in all_node_paths:
            local_attrs = self.stage_model.get_node_local_attr_names(
                node_path,
                self.stage_model.comp_layer)
            if WINDOW_ATTR in local_attrs:
                window_nodes.append(node_path)

        window_node = None
        for node in window_nodes:
            value = self.stage_model.get_node_attr_value(
                node_path=node,
                attr_name=WINDOW_ATTR,
                layer=self.stage_model.comp_layer,
                data_state=DATA_STATE.RESOLVED)
            if value == 'True':
                window_node = node
                break

        return window_node

    def get_window_title(self):
        if self.window_node_path:
            title = self.stage_model.get_node_attr_value(
                        node_path=self.window_node_path,
                        attr_name=self.WINDOW_TITLE_ATTR,
                        layer=None)
            return title or None

    def update_window(self, changed_paths=None):
        if self.updating:
            return
        if not self.isVisible():
            return

        self.window_node_path = self.get_window_node_path()
        if not self.window_node_path:
            self.window_frame.hide()
            return

        update = False if changed_paths else True
        if not isinstance(changed_paths, Iterable):
            changed_paths = []
        for path in changed_paths:
            node_path, _ = nxt_path.path_attr_partition(path)
            is_widget = get_widget_type(node_path, self.stage_model)
            if is_widget:
                desc = self.stage_model.get_descendants(self.window_node_path)
                if node_path in desc:
                    update = True
                    break
            else:
                if not self.stage_model.node_exists(node_path):
                    update = True
                    break
        if not update:
            return
        self.updating = True
        # window title
        title = self.get_window_title()
        self.setWindowTitle(title or self.default_title)

        # remove existing widgets
        while self.scroll_layout.count():
            child = self.scroll_layout.itemAt(0)
            if child.widget():
                c = child.widget()
                c.setParent(None)
                c.deleteLater()
                del c

        # build widgets
        self.build_widgets(self.window_node_path, self.scroll_layout)
        self.set_window_style()
        self.window_frame.show()

        # add context menu
        ContextMenu(stage_model=self.stage_model,
                    node_path=self.window_node_path,
                    widget=self.window_frame,
                    items=None,
                    parent=self)
        self.updating = False

    def set_window_style(self):
        background_color = self.stage_model.get_node_attr_value(
            node_path=self.window_node_path,
            attr_name=self.WINDOW_COLOR_ATTR)
        background_color = background_color or '#232323'
        style = '''
                QFrame {
                    background-color:%s;
                    border-radius: 11px;
                    border: 0px solid transparent;
                }
                ''' % background_color
        self.window_frame.setStyleSheet(style)

    @staticmethod
    def set_tab_style(tab_widget):
        if not tab_widget:
            return

        if not tab_widget.count():
            return

        tab = tab_widget.currentWidget()
        tab.set_tab_style()

    def set_tab_index(self, tab_widget):
        data = self.widget_state_data.get(tab_widget.tab_widget_path)
        if not data:
            return

        index = tab_widget.currentIndex()
        self.widget_state_data[tab_widget.tab_widget_path]['state'] = index

    def tab_context_menu(self, tab_widget):
        cursor_pos = QtGui.QCursor.pos()
        tab_widget_pos = tab_widget.mapFromGlobal(cursor_pos)
        tab_index = tab_widget.tabBar().tabAt(tab_widget_pos)
        tab = tab_widget.widget(tab_index)
        if tab:
            tab.menu.show_menu(tab.mapFromGlobal(cursor_pos))
        else:
            self.window_frame.menu.show_menu(tab_widget_pos)


def get_resolved_attr_values(node_path, stage_model):
    attr_values = {}
    attr_names = stage_model.get_node_attr_names(node_path=node_path,
                                                 layer=stage_model.comp_layer)
    for attr_name in attr_names:
        attr_value = stage_model.get_node_attr_value(
            node_path=node_path,
            attr_name=attr_name,
            layer=stage_model.comp_layer,
            data_state=DATA_STATE.RESOLVED)
        attr_values[attr_name] = attr_value
    return attr_values


def get_widget_type(node_path, stage_model):
    node = stage_model.comp_layer.lookup(node_path)
    if not node:
        return

    instance_trace_list = stage_model.stage.get_instance_sources(
        node=node,
        trace_list=[],
        comp_layer=stage_model.comp_layer)
    if not instance_trace_list:
        return

    instance_node = instance_trace_list[-1]
    instance_path = stage_model.comp_layer.get_node_path(instance_node)
    if not instance_path:
        return

    instance_name = nxt_path.node_name_from_node_path(instance_path)
    widget_type = instance_name if instance_name in WIDGET_TYPES else None
    return widget_type


class ContextMenu(QtWidgets.QMenu):

    def __init__(self, stage_model, node_path, widget, items=None,
                 parent=None):
        super(ContextMenu, self).__init__(parent=parent)
        self.setStyleSheet(
            'background-color: #232323; border: 1px solid #3E3E3E')

        self.stage_model = stage_model
        self.node_path = node_path
        self.widget = widget

        # add context menu to widget
        self.widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.widget.customContextMenuRequested.connect(self.show_menu)
        self.widget.menu = self

        # add menu items
        items = items or []
        for item in items:
            if item == 'separator':
                self.addSeparator()
            else:
                self.addAction(item)

        # add node selection item
        if items:
            self.addSeparator()
        node_action = QtWidgets.QAction('Select NXT Node', self)
        node_action.triggered.connect(self.select_node)
        self.addAction(node_action)

    def show_menu(self, pos):
        self.exec_(self.widget.mapToGlobal(pos))

    def select_node(self):
        self.stage_model.select_and_frame(self.node_path)


class Tab(QtWidgets.QWidget):

    TEXT_ATTR = 'text'
    BACKGROUND_COLOR_ATTR = 'tab_color'
    BORDER_COLOR_ATTR = 'tab_border_color'

    def __init__(self, node_path, tab_parent, parent=None):
        super(Tab, self).__init__(parent=parent)

        # internal setup
        self._parent = parent
        self._tab_parent = tab_parent
        self.stage_model = parent.stage_model
        self.node_path = node_path

        attr_data = get_resolved_attr_values(node_path=node_path,
                                             stage_model=self.stage_model)

        self.background_color = attr_data.get(self.BACKGROUND_COLOR_ATTR)
        self.border_color = attr_data.get(self.BORDER_COLOR_ATTR)

        # setup tab
        text = attr_data.get(self.TEXT_ATTR) or self.TEXT_ATTR
        tab_parent.addTab(self, text)

        # main layout
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.setLayout(self.main_layout)

        # scroll area
        self.scroll_area = QtWidgets.QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        style = '''
                QScrollBar:vertical {
                    background-color: #303030;
                    width: 16px;
                    margin: 16px 2px 16px 2px;
                    border: none;
                    border-radius: 4px;
                }

                QScrollBar::handle:vertical {
                    background-color: #606060;
                    border: none;
                    min-height: 8px;
                    border-radius: 4px;
                }

                QScrollBar::handle:vertical:hover {
                    background-color: #148CD2;
                    border: none;
                    border-radius: 4px;
                    min-height: 8px;

                }
                '''
        self.scroll_area.verticalScrollBar().setStyleSheet(style)
        self.scroll_area.setStyleSheet(style)
        self.main_layout.addWidget(self.scroll_area)

        self.scroll_widget = QtWidgets.QWidget(self.scroll_area)
        self.scroll_area.setWidget(self.scroll_widget)

        # layout
        self.layout = QtWidgets.QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 6, 0)
        self.layout.setSpacing(8)
        self.layout.setAlignment(QtCore.Qt.AlignTop)
        self.scroll_widget.setLayout(self.layout)

        # add context menu
        ContextMenu(stage_model=self.stage_model,
                    node_path=node_path,
                    widget=self,
                    items=None,
                    parent=self)

    def set_tab_style(self):
        background_color = self.background_color if self.background_color else '#3E3E3E'
        border = '2px solid ' + self.border_color if self.border_color else 'none'
        style = '''
                        QTabWidget::pane {
                            border-radius: 9px;
                            border: %s;
                            background-color: %s;
                        }

                        QTabWidget::tab-bar {
                            left: 5px;
                        }

                        QTabBar {
                            background-color: transparent;
                            border: none;
                        }

                        QTabBar::tab {
                            alignment: center;
                            border: %s;
                            border-radius: 8px;
                            padding-bottom: 14px;
                            margin-bottom: -10px;
                            background-color: %s;
                        }

                        QTabBar::tab:hover {
                            padding-top: 2px;
                        }

                        QTabBar::tab:!selected {
                            border: none;
                            background-color: #303030;
                        }

                        QTabBar::tab:!selected:hover {
                            padding-top: 0px;
                        }

                        QWidget {
                            background-color: transparent;
                        }
                        ''' % (border, background_color, border,
                               background_color)
        self._tab_parent.setStyleSheet(style)


class Panel(QtWidgets.QWidget):

    TEXT_ATTR = 'text'
    TEXT_COLOR_ATTR = 'text_color'
    BACKGROUND_COLOR_ATTR = 'panel_color'
    BORDER_COLOR_ATTR = 'panel_border_color'

    def __init__(self, node_path, parent=None):
        super(Panel, self).__init__(parent=parent)

        # internal setup
        self._parent = parent
        self.node_path = node_path
        self.stage_model = parent.stage_model

        attr_data = get_resolved_attr_values(node_path=node_path,
                                             stage_model=self.stage_model)

        # main layout
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.main_layout.setAlignment(QtCore.Qt.AlignTop)
        self.setLayout(self.main_layout)

        # panel frame
        background_color = attr_data.get(self.BACKGROUND_COLOR_ATTR)
        border_color = attr_data.get(self.BORDER_COLOR_ATTR)
        background_color = background_color or '#3E3E3E'
        border_color = border_color or 'transparent'
        style = '''
                QFrame {
                    background-color: %s;
                    border-radius: 9px;
                    border: 2px solid %s;
                    }
                ''' % (background_color, border_color)
        self.panel_frame = QtWidgets.QFrame(self)
        self.panel_frame.setStyleSheet(style)
        self.main_layout.addWidget(self.panel_frame)

        # panel layout
        self.panel_layout = QtWidgets.QVBoxLayout(self.panel_frame)
        self.panel_layout.setContentsMargins(0, 0, 0, 0)
        self.panel_layout.setSpacing(0)
        self.panel_frame.setLayout(self.panel_layout)

        # title layout
        self.title_layout = QtWidgets.QHBoxLayout()
        self.title_layout.setContentsMargins(4, 0, 0, 0)
        self.title_layout.setSpacing(0)
        self.panel_layout.addLayout(self.title_layout)

        # collapse button
        self.collapse_button = QtWidgets.QToolButton(checkable=True,
                                                     checked=False)
        self.collapse_button.setStyleSheet(
            'QToolButton {background-color: transparent; border: none;}')
        self.collapse_button.setArrowType(QtCore.Qt.DownArrow)
        self.collapse_button.toggled.connect(self.toggle_collapsed)
        self.title_layout.addWidget(self.collapse_button)

        # title label
        text = attr_data.get(self.TEXT_ATTR) or self.TEXT_ATTR
        text_color = attr_data.get(self.TEXT_COLOR_ATTR)
        self.title_label = DoubleClickLabel(text=text, parent=self.panel_frame)
        if text_color:
            self.title_label.setStyleSheet(
                'QLabel {color: %s; border-color: none;}' % text_color)
        else:
            self.title_label.setStyleSheet(
                'QLabel {border-color: transparent;}')
        self.title_label.doubleClicked.connect(self.collapse_button.toggle)
        self.title_layout.addWidget(self.title_label)

        # main frame
        self.main_frame = QtWidgets.QFrame(self)
        self.main_frame.setStyleSheet('QFrame {border: none;}')
        self.panel_layout.addWidget(self.main_frame)

        # layout
        self.layout = QtWidgets.QVBoxLayout(self.main_frame)
        self.layout.setContentsMargins(10, 4, 10, 10)
        self.main_frame.setLayout(self.layout)

        ContextMenu(stage_model=self.stage_model,
                    node_path=node_path,
                    widget=self,
                    items=None,
                    parent=self)

        # set state
        data = parent.widget_state_data.get(node_path)
        if data:
            if data['widget_type'] == 'panel':
                state = data.get('state', False)
                self.set_collapse_state(state)
            else:
                data['widget_type'] = 'panel'
                data['state'] = self.is_collapsed
            data['widget'] = self
        else:
            data = {'widget_type': 'panel',
                    'widget': self,
                    'state': self.is_collapsed}
        parent.widget_state_data[self.node_path] = data

    @property
    def is_collapsed(self):
        return self.collapse_button.isChecked()

    def set_collapse_state(self, state):
        self.collapse_button.setChecked(state)

    def toggle_collapsed(self):
        if self.is_collapsed:
            self.collapse_button.setArrowType(QtCore.Qt.RightArrow)
            self.main_frame.hide()
        else:
            self.collapse_button.setArrowType(QtCore.Qt.DownArrow)
            self.main_frame.show()

        state = self.is_collapsed
        self._parent.widget_state_data[self.node_path]['state'] = state


class DoubleClickLabel(QtWidgets.QLabel):
    doubleClicked = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super(DoubleClickLabel, self).__init__(*args, **kwargs)

    def mouseDoubleClickEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.doubleClicked.emit()


class GridLayout(QtWidgets.QWidget):

    MAX_COLUMN_ATTR = 'max_columns'

    def __init__(self, node_path, parent=None):
        super(GridLayout, self).__init__(parent=parent)

        # internal setup
        self._parent = parent
        self.stage_model = parent.stage_model

        attr_data = get_resolved_attr_values(node_path=node_path,
                                             stage_model=self.stage_model)

        # layout
        self.layout = QtWidgets.QGridLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)

        # set column stretch
        # this also also has the side effect of defining the number of columns
        # so no custom row/col logic is required when using "addWidget".
        max_columns = attr_data.get(self.MAX_COLUMN_ATTR)
        self.max_columns = int(max_columns) if max_columns else 1
        for c in range(self.max_columns):
            self.layout.setColumnStretch(c, 1)

        ContextMenu(stage_model=self.stage_model,
                    node_path=node_path,
                    widget=self,
                    items=None,
                    parent=self)


class Button(QtWidgets.QPushButton):

    MENU_ITEM_TYPE_ATTR = 'menuItem'
    TEXT_ATTR = 'text'
    TEXT_COLOR_ATTR = 'text_color'
    BACKGROUND_COLOR_ATTR = 'button_color'
    BORDER_COLOR_ATTR = 'button_border_color'
    EXEC_PATH_ATTR = 'button_exec_path'
    ITEM_PATH_ATTR = 'item_exec_path'
    SEPARATOR_ATTR = 'item_is_separator'
    SELECTOR_ITEM_ATTR = 'is_item_selector'
    ITEM_LIST_PATH_ATTR = 'item_list_attr_path'
    INPUT_LIST_ATTR = 'item_input_list'
    SELECTOR_TITLE_ATTR = 'item_selector_title'

    def __init__(self, node_path, parent=None):
        super(Button, self).__init__(parent=parent)

        # internal setup
        self._parent = parent
        self.stage_model = parent.stage_model
        self.node_path = node_path

        attr_data = get_resolved_attr_values(node_path=node_path,
                                             stage_model=self.stage_model)

        # button setup
        text = (attr_data.get(self.TEXT_ATTR) or
                nxt_path.node_name_from_node_path(node_path))
        self.setText(text)
        self.pressed.connect(lambda p=self.node_path, a=self.EXEC_PATH_ATTR:
                             self.execute_node_path(p, a))

        background_color = attr_data.get(self.BACKGROUND_COLOR_ATTR) or '#606060'
        border_color = attr_data.get(self.BORDER_COLOR_ATTR) or 'none'
        text_color = attr_data.get(self.TEXT_COLOR_ATTR) or 'white'
        style = '''
                QPushButton {
                    color: %s;
                    background-color: %s;
                    border-radius: 9px;
                    border: none;
                    }

                QPushButton:hover {
                    padding-bottom: -1;
                    padding-top: -1;
                    border: 2px solid %s;
                    }
                ''' % (text_color, background_color, border_color)
        self.setStyleSheet(style)

        # add context menu
        items = []
        for menu_item_path in self.get_menu_item_paths():
            menu_data = get_resolved_attr_values(node_path=menu_item_path,
                                                 stage_model=self.stage_model)
            if menu_data.get(self.SEPARATOR_ATTR) == 'True':
                items.append('separator')
            else:
                text = menu_data.get(self.TEXT_ATTR)
                action = QtWidgets.QAction(text, self)
                if menu_data.get(self.SELECTOR_ITEM_ATTR) == 'True':
                    title = menu_data.get(self.SELECTOR_TITLE_ATTR)
                    action.triggered.connect(lambda p=menu_item_path, t=title:
                                             self.selection_widget(p, t))
                else:
                    action.triggered.connect(lambda p=menu_item_path,
                                             a=self.ITEM_PATH_ATTR:
                                             self.execute_node_path(p, a))
                items.append(action)

        ContextMenu(stage_model=self.stage_model,
                    node_path=self.node_path,
                    widget=self,
                    items=items,
                    parent=self)

    def get_menu_item_paths(self):
        children = self.stage_model.get_children(
            node_path=self.node_path,
            layer=self.stage_model.comp_layer,
            ordered=True)

        menu_items = []
        for child in children:
            widget_type = get_widget_type(child, self.stage_model)
            if widget_type == self.MENU_ITEM_TYPE_ATTR:
                menu_items.append(child)

        return menu_items

    def selection_widget(self, node_path, title):
        # execute node to calculate input list
        if user_dir.user_prefs.get(RECOMP_PREF, True):
            rt_layer = None
        else:
            rt_layer = self.stage_model.current_rt_layer
        self.stage_model.execute_nodes(node_paths=[node_path],
                                       rt_layer=rt_layer)

        # get items list from input value
        # try resolved value first then fall back to cached value
        input_value = self.stage_model.get_node_attr_value(
            node_path=node_path,
            attr_name=self.INPUT_LIST_ATTR,
            layer=None,
            data_state=DATA_STATE.RESOLVED)
        if not input_value:
            input_value = self.stage_model.get_node_attr_value(
                node_path=node_path,
                attr_name=self.INPUT_LIST_ATTR,
                layer=None,
                data_state=DATA_STATE.CACHED)
        if (not isinstance(input_value, str) and
                isinstance(input_value, Iterable)):
            items = input_value
        else:
            items = []
        # selector dialog
        screen = QtWidgets.QApplication.desktop().screenNumber(
            QtWidgets.QApplication.desktop().cursor().pos())
        center = QtWidgets.QApplication.desktop().screenGeometry(screen).center()
        dialog = SelectionDialog(title=title, items=items, pos=center, parent=self)
        dialog.exec_()
        if not dialog.result():
            return

        list_path_attr = self.stage_model.get_node_attr_value(
            node_path=node_path,
            attr_name=self.ITEM_LIST_PATH_ATTR,
            layer=None)

        try:
            target_node, target_attr = list_path_attr.split('.')
        except ValueError:
            logger.error('You must enter a /valid/node/path.attr in "{}.{}",'
                         'Invalid: {}'
                         ''.format(node_path, self.ITEM_LIST_PATH_ATTR,
                                   list_path_attr))
            return
        self.stage_model.set_node_attr_value(
            node_path=target_node,
            attr_name=target_attr,
            value=dialog.item_list,
            layer=None)

    def execute_node_path(self, node_path, attr_name):
        exec_path = self.stage_model.get_node_attr_value(
            node_path=node_path,
            attr_name=attr_name,
            layer=self.stage_model.comp_layer,
            data_state=DATA_STATE.RESOLVED)

        if not exec_path:
            return

        descendants = self.stage_model.comp_layer.descendants(exec_path,
                                                              ordered=True)

        # filter out widget nodes
        filtered_nodes = []
        dont_run = []
        for path in descendants:
            widget_type = get_widget_type(path, self.stage_model)
            if widget_type:
                des = self.stage_model.comp_layer.descendants(path,
                                                              ordered=True)
                dont_run += des
            if not widget_type and path not in dont_run:
                enabled = self.stage_model.get_node_enabled(path)
                anc_enabled = self.stage_model.get_node_ancestor_enabled(path)
                if enabled and anc_enabled:
                    filtered_nodes.append(path)
                else:
                    des = self.stage_model.comp_layer.descendants(path,
                                                                  ordered=True)
                    dont_run += [path] + des

        node_paths = [exec_path] + filtered_nodes
        if user_dir.user_prefs.get(RECOMP_PREF, True):
            rt_layer = None
        else:
            rt_layer = self.stage_model.current_rt_layer
        self.stage_model.execute_nodes(node_paths=node_paths,
                                       rt_layer=rt_layer)


class CheckBox(QtWidgets.QWidget):

    TEXT_ATTR = 'text'
    TEXT_COLOR_ATTR = 'text_color'
    TEXT_ALIGN_ATTR = 'text_align'
    IS_CHECKED_ATTR = 'is_checked'
    ALIGNMENT_ATTR = 'checkbox_alignment'
    EXEC_PATH_ATTR = 'checkbox_exec_path'
    ALIGNMENT = {'center': QtCore.Qt.AlignHCenter,
                 'left': QtCore.Qt.AlignLeft,
                 'right': QtCore.Qt.AlignRight}
    LABEL_ALIGNMENT = {'left': QtCore.Qt.RightToLeft,
                       'right': QtCore.Qt.LeftToRight}

    def __init__(self, node_path, parent=None):
        super(CheckBox, self).__init__(parent=parent)
        self.setStyleSheet('QWidget {margin-top: -4; margin-bottom: -4;}')

        # internal setup
        self._parent = parent
        self.stage_model = parent.stage_model
        self.node_path = node_path

        attr_data = get_resolved_attr_values(node_path=node_path,
                                             stage_model=self.stage_model)

        # layout
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        alignment = attr_data.get(self.ALIGNMENT_ATTR)
        layout_alignment = self.ALIGNMENT.get(alignment)
        if layout_alignment:
            self.main_layout.setAlignment(layout_alignment)
        self.setLayout(self.main_layout)

        # checkbox
        text_color = attr_data.get(self.TEXT_COLOR_ATTR) or 'white'
        is_checked = attr_data.get(self.IS_CHECKED_ATTR)
        checked = True if is_checked == 'True' else False
        text = (attr_data.get(self.TEXT_ATTR) or
                nxt_path.node_name_from_node_path(self.node_path))
        style = 'QCheckBox {color: %s;}' % text_color
        self.checkbox = QtWidgets.QCheckBox(text=text, checked=checked)
        self.checkbox.setStyleSheet(style)
        self.checkbox.toggled.connect(self.execute_node_path)
        self.main_layout.addWidget(self.checkbox)

        text_align = attr_data.get(self.TEXT_ALIGN_ATTR)
        label_alignment = self.LABEL_ALIGNMENT.get(text_align)
        if label_alignment:
            self.checkbox.setLayoutDirection(label_alignment)

        # add context menu
        ContextMenu(stage_model=self.stage_model,
                    node_path=node_path,
                    widget=self.checkbox,
                    items=None,
                    parent=self)

    def execute_node_path(self):
        check_state = 'True' if self.checkbox.checkState() else 'False'
        self.stage_model.set_node_attr_value(node_path=self.node_path,
                                             attr_name=self.IS_CHECKED_ATTR,
                                             value=check_state,
                                             layer=None)

        exec_path = self.stage_model.get_node_attr_value(
            node_path=self.node_path,
            attr_name=self.EXEC_PATH_ATTR,
            layer=self.stage_model.comp_layer,
            data_state=DATA_STATE.RESOLVED)
        if exec_path:
            if not self.stage_model.node_exists(node_path=self.node_path,
                                                layer=self.stage_model.comp_layer):
                return
            if user_dir.user_prefs.get(RECOMP_PREF, True):
                rt_layer = None
            else:
                rt_layer = self.stage_model.current_rt_layer
            self.stage_model.execute_nodes(node_paths=[exec_path],
                                           rt_layer=rt_layer)


class DropDownMenu(QtWidgets.QWidget):

    TEXT_ATTR = 'text'
    TEXT_COLOR_ATTR = 'text_color'
    BACKGROUND_COLOR_ATTR = 'menu_background_color'
    BORDER_COLOR_ATTR = 'menu_border_color'
    MENU_ITEMS_ATTR = 'menu_items'
    EXEC_PATH_ATTR = 'menu_exec_path'
    MENU_VALUE_ATTR = 'menu_value'

    def __init__(self, node_path, parent=None):
        super(DropDownMenu, self).__init__(parent=parent)
        size_policy = QtWidgets.QSizePolicy()
        size_policy.setHorizontalPolicy(QtWidgets.QSizePolicy.Preferred)
        size_policy.setHorizontalStretch(1)
        self.setSizePolicy(size_policy)

        # internal setup
        self._parent = parent
        self.stage_model = parent.stage_model
        self.node_path = node_path

        attr_data = get_resolved_attr_values(node_path=node_path,
                                             stage_model=self.stage_model)

        # layout
        self.main_layout = QtWidgets.QHBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        self.setLayout(self.main_layout)

        # label
        text = (attr_data.get(self.TEXT_ATTR) or
                nxt_path.node_name_from_node_path(self.node_path))
        text_color = attr_data.get(self.TEXT_COLOR_ATTR) or 'white'
        self.label = QtWidgets.QLabel(text)
        self.label.setStyleSheet('QLabel {color: %s}' % text_color)
        self.main_layout.addWidget(self.label)

        # style
        background_color = attr_data.get(self.BACKGROUND_COLOR_ATTR) or '#232323'
        border_color = attr_data.get(self.BORDER_COLOR_ATTR) or 'transparent'
        border_line = '2px solid %s' % border_color if border_color != 'transparent' else 'none'
        padding = '4' if border_color != 'transparent' else '6'
        style = '''
                QComboBox {
                    color: %s;
                    background: %s;
                    border-radius: 9px;
                    border: none;
                    padding-left: 6;
                    overflow: hidden;
                    }

                QComboBox:hover {
                    padding-left: %s;
                    border: %s;
                    }
                ''' % (text_color, background_color, padding,
                       border_line)
        view_style = '''
                     QComboBox QAbstractItemView {
                         selection-color: white;
                         selection-background-color: #148CD2;
                         background: %s;
                         border-top-left-radius: 0px;
                         border-top-right-radius: 0px;
                         border-bottom-left-radius: 9px;
                         border-bottom-right-radius: 9px;
                         border-width: 2px;
                         border-style: solid;
                         border-color: transparent %s %s %s;
                         margin-right: 9px;
                         margin-left: 9px;
                         outline: 0;
                     }
                     ''' % (background_color, border_color, border_color,
                            border_color)

        # combo box
        self.combo_box = QtWidgets.QComboBox(self)
        self.combo_box.setStyleSheet(style)
        self.combo_box.view().window().setWindowFlags(
            QtCore.Qt.Popup |
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.NoDropShadowWindowHint)
        self.combo_box.view().setStyleSheet(view_style)
        self.combo_box.view().window().setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.main_layout.addWidget(self.combo_box, 1)

        # menu items
        menu_items = attr_data.get(self.MENU_ITEMS_ATTR)
        if not menu_items:
            return

        menu_items_list = menu_items.split(' ')
        self.combo_box.addItems(menu_items_list)
        menu_value = self.stage_model.get_node_attr_value(
            node_path=self.node_path,
            attr_name=self.MENU_VALUE_ATTR,
            layer=self.stage_model.comp_layer,
            data_state=DATA_STATE.RESOLVED)
        if menu_value in menu_items_list:
            self.combo_box.setCurrentText(menu_value)
        self.combo_box.currentIndexChanged.connect(self.execute_node_path)

        # add context menus
        ContextMenu(stage_model=self.stage_model,
                    node_path=node_path,
                    widget=self,
                    items=None,
                    parent=self)

        ContextMenu(stage_model=self.stage_model,
                    node_path=node_path,
                    widget=self.combo_box,
                    items=None,
                    parent=self)

    def set_menu_value(self):
        self.stage_model.set_node_attr_value(node_path=self.node_path,
                                             attr_name=self.MENU_VALUE_ATTR,
                                             value=self.combo_box.currentText(),
                                             layer=None)

    def execute_node_path(self):
        self.set_menu_value()

        exec_path = self.stage_model.get_node_attr_value(
            node_path=self.node_path,
            attr_name=self.EXEC_PATH_ATTR,
            layer=self.stage_model.comp_layer,
            data_state=DATA_STATE.RESOLVED)

        if exec_path:
            if not self.stage_model.node_exists(node_path=self.node_path,
                                                layer=self.stage_model.comp_layer):
                return
            if user_dir.user_prefs.get(RECOMP_PREF, True):
                rt_layer = None
            else:
                rt_layer = self.stage_model.current_rt_layer
            self.stage_model.execute_nodes(node_paths=[exec_path],
                                           rt_layer=rt_layer)


class SelectionDialog(QtWidgets.QDialog):

    def __init__(self, title=None, items=None, pos=None, parent=None):
        super(SelectionDialog, self).__init__(parent=parent)

        self.setWindowFlags(
            self.windowFlags() & ~QtCore.Qt.WindowContextHelpButtonHint)
        self.setWindowTitle(title or 'Select Items')
        self.setStyleSheet('QDialog {background: #232323;}')

        self.main_layout = QtWidgets.QVBoxLayout()
        self.main_layout.setContentsMargins(8, 8, 8, 8)
        self.main_layout.setSpacing(0)
        self.setLayout(self.main_layout)

        # scroll area
        self.scroll_area = QtWidgets.QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.main_layout.addWidget(self.scroll_area)

        self.scroll_widget = QtWidgets.QWidget(self)
        self.scroll_area.setWidget(self.scroll_widget)

        self.scroll_layout = QtWidgets.QVBoxLayout(self)
        self.scroll_layout.setContentsMargins(0, 0, 4, 0)
        self.scroll_layout.setSpacing(4)
        self.scroll_layout.setAlignment(QtCore.Qt.AlignTop)
        self.scroll_widget.setLayout(self.scroll_layout)

        # list view
        self.model = QtGui.QStandardItemModel()
        items = items if items is not None else []
        for item in items:
            i = QtGui.QStandardItem(str(item))
            i.item_value = item
            i.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
            i.setData(QtCore.Qt.Checked, QtCore.Qt.CheckStateRole)
            self.model.appendRow(i)

        self.view = QtWidgets.QListView()
        self.view.setModel(self.model)
        self.view.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self.context_menu)
        self.scroll_layout.addWidget(self.view)

        # buttons
        self.button_layout = QtWidgets.QHBoxLayout(self)
        self.button_layout.setContentsMargins(0, 8, 0, 4)
        self.button_layout.setSpacing(8)
        self.main_layout.addLayout(self.button_layout)

        style = 'QPushButton {border-radius: 9px; background-color: #606060;}'

        self.accept_button = QtWidgets.QPushButton('Accept')
        self.accept_button.setStyleSheet(style)
        self.accept_button.pressed.connect(self.accept)
        self.button_layout.addWidget(self.accept_button)

        self.cancel_button = QtWidgets.QPushButton('Cancel')
        self.cancel_button.setStyleSheet(style)
        self.cancel_button.pressed.connect(self.reject)
        self.button_layout.addWidget(self.cancel_button)

    @property
    def item_list(self):
        item_list = []
        for row_index in range(self.model.rowCount()):
            item = self.model.item(row_index, 0)
            if item.checkState():
                item_list.append(item.item_value)
        return item_list

    def select_all(self):
        for row_index in range(self.model.rowCount()):
            item = self.model.item(row_index, 0)
            item.setCheckState(QtCore.Qt.Checked)

    def select_none(self):
        for row_index in range(self.model.rowCount()):
            item = self.model.item(row_index, 0)
            item.setCheckState(QtCore.Qt.Unchecked)

    def context_menu(self):
        menu = QtWidgets.QMenu(self)
        menu.addAction('Select All', self.select_all)
        menu.addAction('Select None', self.select_none)
        menu.popup(QtGui.QCursor.pos())
