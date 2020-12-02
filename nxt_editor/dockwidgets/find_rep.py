# Builtin
import logging
import re
import time
import fnmatch

# External
from Qt import QtWidgets
from Qt import QtGui
from Qt import QtCore

# Internal
from nxt_editor.dockwidgets.dock_widget_base import DockWidgetBase
from nxt import nxt_path, nxt_node
from nxt.constants import DATA_STATE
from nxt_editor import user_dir

logger = logging.getLogger('nxt.' + __name__)


class FindRepDockWidget(DockWidgetBase):
    """Widget to find and replace within active graph.
    """
    NODE_PATTERNS_PREF = user_dir.USER_PREF.FIND_REP_NODE_PATTERNS
    BUTTON_WIDTH = 75

    def __init__(self, title='Find and Replace', parent=None):
        super(FindRepDockWidget, self).__init__(title=title, parent=parent)

        self.setObjectName('Find and Replace')
        self.main_window = parent
        # main layout
        self.main = QtWidgets.QWidget(parent=self)
        self.setWidget(self.main)

        self.layout = QtWidgets.QVBoxLayout()
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(0)
        self.main.setLayout(self.layout)

        self.attrs_menu_button = QtWidgets.QPushButton('Attrs')
        self.attrs_menu_button.setMinimumWidth(self.BUTTON_WIDTH)
        searchable_attrs = SearchModel.SEARCHABLE_INTERNAL_ATTRS
        self.attrs_menu = AttrSelectionMenu(searchable_attrs)
        self.attrs_menu_button.setMenu(self.attrs_menu)

        self.results_tree = SearchResultsTree()
        self.results_tree.doubleClicked.connect(self.result_double_clicked)

        self.search_field = ReturnLineEdit()
        self.search_field.setPlaceholderText('Find')
        self.search_field.return_pressed.connect(self.update_query)

        self.search_button = QtWidgets.QPushButton('Find')
        self.search_button.setMinimumWidth(self.BUTTON_WIDTH)
        self.search_button.released.connect(self.update_query)

        self.replace_field = ReturnLineEdit()
        self.replace_field.setPlaceholderText('Replace')
        self.replace_field.return_pressed.connect(self.replace_val)

        self.replace_button = QtWidgets.QPushButton('Replace')
        self.replace_button.setMinimumWidth(self.BUTTON_WIDTH)
        self.replace_button.released.connect(self.replace_val)

        self.node_patterns_field = QtWidgets.QLineEdit()
        pref_patterns = user_dir.user_prefs.get(self.NODE_PATTERNS_PREF, '')
        self.node_patterns_field.setText(str(pref_patterns))
        self.node_patterns_field.setPlaceholderText('Nodes to search')
        patterns_tooltip = ("Comma seperated glob patterns of node paths to "
                            "search. All are searched if none are specified.")
        self.node_patterns_field.setToolTip(patterns_tooltip)

        self.search_layout = QtWidgets.QHBoxLayout()
        self.search_layout.addWidget(self.search_field)
        # self.search_layout.addWidget(self.attrs_menu_button)
        self.search_layout.addWidget(self.search_button)
        self.rep_layout = QtWidgets.QHBoxLayout()
        self.rep_layout.addWidget(self.replace_field)
        self.rep_layout.addWidget(self.replace_button)
        self.details_layout = QtWidgets.QHBoxLayout()
        self.details_layout.addWidget(self.node_patterns_field)
        self.details_layout.addWidget(self.attrs_menu_button)
        # self.layout.addWidget(self.node_patterns_field)
        self.layout.addLayout(self.search_layout)
        self.layout.addLayout(self.rep_layout)
        self.layout.addLayout(self.details_layout)
        self.layout.addWidget(self.results_tree)

    def raise_(self):
        super(FindRepDockWidget, self).raise_()
        self.search_field.setFocus()

    def set_stage_model(self, stage_model):
        super(FindRepDockWidget, self).set_stage_model(stage_model=stage_model)
        if not self.stage_model:
            self.results_tree.setModel(None)
            self.setEnabled(False)
            return
        self.setEnabled(True)
        self.results_tree.setModel(SearchModel(self.stage_model))

    def on_stage_model_destroyed(self):
        super(FindRepDockWidget, self).on_stage_model_destroyed()
        self.results_tree.setModel(None)
        self.setEnabled(False)

    def update_query(self):
        t0 = time.time()
        attrs = list(self.attrs_menu.iter_checked_attr_names())
        user_attrs = self.attrs_menu.is_user_attrs_checked()
        patterns_text = self.node_patterns_field.text()
        user_dir.user_prefs[self.NODE_PATTERNS_PREF] = patterns_text
        patterns = None
        if patterns_text:
            patterns = patterns_text.split(',')
            patterns = [p.strip() for p in patterns]
        self.results_tree.model().set_query(self.search_field.text(),
                                            node_patterns=patterns,
                                            attr_names=attrs,
                                            user_attrs=user_attrs)
        logger.debug('searched in ' + str(round(time.time() - t0)) + ' secs')
        self.results_tree.expandAll()

    def replace_val(self):
        results_model = self.results_tree.model()
        repl_text = self.replace_field.text()
        results_model.replace_selected(repl_text)

    def result_double_clicked(self, clicked_idx):
        parent = clicked_idx.parent()
        if parent.isValid():
            path_item = parent
        else:
            path_item = clicked_idx
        node_path = self.results_tree.model().data(path_item)
        if self.stage_model.selection == [node_path]:
            return
        self.stage_model.select_and_frame(node_path)


class AttrSelectionMenu(QtWidgets.QMenu):
    USER_ATTRS_ACTION_NAME = 'User Attrs'
    PREF_KEY = user_dir.USER_PREF.FIND_REP_ATTRS

    def __init__(self, attr_names):
        super(AttrSelectionMenu, self).__init__('Attrs')
        pref_checked = user_dir.user_prefs.get(self.PREF_KEY, {})

        self.actions_by_attr = {}
        for attr_name in attr_names:
            new_action = self.addAction(attr_name)
            new_action.setCheckable(True)
            new_action.setChecked(pref_checked.get(attr_name, False))
            self.actions_by_attr[attr_name] = new_action

        self.user_attrs_action = self.addAction(self.USER_ATTRS_ACTION_NAME)
        self.user_attrs_action.setCheckable(True)
        user_checked = pref_checked.get(self.USER_ATTRS_ACTION_NAME, True)
        self.user_attrs_action.setChecked(user_checked)
        self.triggered.connect(self.action_triggered)

    def action_triggered(self, action):
        pref_val = {}
        for attr_name, action in self.actions_by_attr.items():
            pref_val[attr_name] = action.isChecked()
        pref_val[self.USER_ATTRS_ACTION_NAME] = self.is_user_attrs_checked()
        user_dir.user_prefs[self.PREF_KEY] = pref_val

    def iter_checked_attr_names(self):
        for attr_name, action in self.actions_by_attr.items():
            if action.isChecked():
                yield attr_name

    def is_user_attrs_checked(self):
        return self.user_attrs_action.isChecked()


class ReturnLineEdit(QtWidgets.QLineEdit):
    return_pressed = QtCore.Signal()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Return:
            self.return_pressed.emit()
        super(ReturnLineEdit, self).keyPressEvent(event)


class SearchResultsTree(QtWidgets.QTreeView):
    def __init__(self):
        super(SearchResultsTree, self).__init__()
        self.setHeaderHidden(True)

    def setModel(self, model):
        """Sets up headers and expands tree.
        """
        super(SearchResultsTree, self).setModel(model)
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(header.ResizeToContents)
        if self.model():
            self.model().modelReset.connect(self.expandAll)


class SearchModel(QtGui.QStandardItemModel):
    SEARCHABLE_INTERNAL_ATTRS = [
        nxt_node.INTERNAL_ATTRS.COMMENT,
        nxt_node.INTERNAL_ATTRS.COMPUTE,
        nxt_node.INTERNAL_ATTRS.EXECUTE_IN,
        nxt_node.INTERNAL_ATTRS.INSTANCE_PATH,
    ]
    USER_ATTRS_NAME = 'User Attrs'

    def __init__(self, stage_model):
        super(SearchModel, self).__init__()
        self.setColumnCount(2)

        self.stage_model = stage_model
        self._query_str = None
        self.search_node_patterns = ['*']
        self.search_attr_names = self.SEARCHABLE_INTERNAL_ATTRS
        self.search_user_attrs = True

    @property
    def query_str(self):
        return self._query_str

    def set_query(self, query_str, node_patterns=None, attr_names=None,
                  user_attrs=True):
        self._query_str = query_str
        if node_patterns:
            self.search_node_patterns = node_patterns
        else:
            self.search_node_patterns = ['*']
        if attr_names is not None:
            self.search_attr_names = attr_names
        self.search_user_attrs = user_attrs
        self.reset()

    def populate(self):
        if not self.query_str:
            return
        node_paths = self.stage_model.get_descendants(nxt_path.WORLD)
        node_paths += [nxt_path.WORLD]
        for node_path in node_paths:
            search_node = False
            for pattern in self.search_node_patterns:
                if fnmatch.fnmatch(node_path, pattern):
                    search_node = True
                    break
            if not search_node:
                continue
            path_item = self.get_results_for_node(node_path)
            if path_item.rowCount() <= 0:
                continue
            self.appendRow([path_item, QtGui.QStandardItem('')])

    def get_results_for_node(self, node_path):
        legal_attrs = []
        comp_layer = self.stage_model.comp_layer
        if self.search_user_attrs:
            loc_attrs = self.stage_model.get_node_local_attr_names(node_path,
                                                                   comp_layer)
            legal_attrs += loc_attrs
        legal_attrs += self.search_attr_names
        path_item = QtGui.QStandardItem(node_path)
        path_item.setCheckable(True)
        for attr_name in legal_attrs:
            raw = DATA_STATE.RAW
            if attr_name == nxt_node.INTERNAL_ATTRS.COMPUTE:
                val = self.stage_model.get_node_code_string(node_path,
                                                            data_state=raw)
            else:
                val = self.stage_model.get_node_attr_value(node_path,
                                                           attr_name,
                                                           data_state=raw,
                                                           layer=comp_layer)
                val = str(val)
            if val is None:
                continue
            if self.query_str in val:
                name_item = QtGui.QStandardItem(attr_name)
                name_item.setCheckable(True)
                disp_val = val
                query_re = "^.*" + self.query_str + ".*$"
                multi_line_results = re.findall(query_re, val, re.MULTILINE)
                if multi_line_results:
                    disp_val = '\n'.join(multi_line_results)
                results = [name_item,
                           QtGui.QStandardItem(disp_val)]
                path_item.appendRow(results)
        return path_item

    def replace_selected(self, rep_value):
        to_replace = {}
        for path_row in range(self.rowCount()):
            path_item = self.item(path_row)
            node_path = path_item.text()
            for attr_row in range(path_item.rowCount()):
                attr_item = path_item.child(attr_row)
                if attr_item.checkState() != QtCore.Qt.Checked:
                    continue
                attr_name = attr_item.text()
                state = DATA_STATE.RAW
                if attr_name == nxt_node.INTERNAL_ATTRS.COMPUTE:
                    code_str = self.stage_model.get_node_code_string(node_path,
                                                                     data_state=state)
                    code_lines = code_str.split('\n')
                    code_lines_count = len(code_lines)
                    val = ['' for _ in range(code_lines_count)]
                    for i in range(code_lines_count):
                        if self.query_str in code_lines[i]:
                            val[i] = code_lines[i].replace(self.query_str, rep_value)
                        else:
                            val[i] = code_lines[i]
                else:
                    existing = self.stage_model.get_node_attr_value(node_path, attr_name,
                                                                    data_state=state)
                    existing = str(existing)
                    val = existing.replace(self.query_str, rep_value)
                to_replace[(node_path, attr_name)] = val
        if len(to_replace) == 0:
            return
        macro_fmt = "Replace {} with {} in {} attributes"
        macro_str = macro_fmt.format(self.query_str, rep_value, len(to_replace))
        self.stage_model.undo_stack.beginMacro(macro_str)
        for path_tpl, val in to_replace.items():
            self.stage_model.set_node_attr_value(path_tpl[0], path_tpl[1], val)
        self.stage_model.undo_stack.endMacro()

    def setData(self, index, value, role):
        result = super(SearchModel, self).setData(index, value, role)
        if role == QtCore.Qt.CheckStateRole:
            parent_idx = index.parent()
            # attr checkbox
            if parent_idx.isValid():
                found_states = set()
                for i in range(self.rowCount(parent_idx)):
                    child_index = self.index(i, 0, parent_idx)
                    found_states.add(self.data(child_index, role))
                if len(found_states) == 1:
                    state = found_states.pop()
                    super(SearchModel, self).setData(parent_idx, state, role)
                elif len(found_states) > 1:
                    partially = QtCore.Qt.PartiallyChecked
                    super(SearchModel, self).setData(parent_idx, partially,
                                                     role)
            # node path check box
            elif value in (QtCore.Qt.Checked, QtCore.Qt.Unchecked):
                for i in range(self.rowCount(index)):
                    child_index = self.index(i, 0, index)
                    super(SearchModel, self).setData(child_index, value, role)
        return result

    def reset(self):
        self.beginResetModel()
        self.clear()
        self.populate()
        self.endResetModel()

    def flags(self, index):
        return QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsUserCheckable
