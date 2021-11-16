# Builtin
import logging

# External
from Qt import QtWidgets
from Qt import QtGui
from Qt import QtCore

# Internal
import nxt_editor
from nxt_editor import user_dir
from nxt_editor.dockwidgets.dock_widget_base import DockWidgetBase
from nxt import nxt_path


logger = logging.getLogger(nxt_editor.LOGGER_NAME)


class LayerManager(DockWidgetBase):
    """Interactive tree view of the layers in the open graph.
    """
    def __init__(self, title='Layer Manger', parent=None):
        super(LayerManager, self).__init__(title=title,
                                           parent=parent,
                                           minimum_width=100)

        self.setObjectName('Layer Manager')
        self.nxt = self.parent().nxt
        self.main_window = parent
        self.addActions(self.main_window.layer_actions.actions())
        # main layout
        self.main = QtWidgets.QWidget(parent=self)
        self.setWidget(self.main)

        self.layout = QtWidgets.QVBoxLayout()
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(0)
        self.main.setLayout(self.layout)

        # tree widget
        self.layer_tree = LayerTreeView(self.main_window.layer_actions)
        self.layout.addWidget(self.layer_tree)

        table_action = self.main_window.layer_actions.lay_manger_table_action
        table_action.triggered.connect(self.layer_tree.refresh_indention)

    def set_stage_model(self, stage_model):
        super(LayerManager, self).set_stage_model(stage_model=stage_model)
        if not self.stage_model:
            return
        self.layer_tree.setModel(LayerModel(self.stage_model))

    def on_stage_model_destroyed(self):
        super(LayerManager, self).on_stage_model_destroyed()
        self.layer_tree.setModel(None)


class LayerTreeView(QtWidgets.QTreeView):
    SIZE = 25

    def __init__(self, layer_actions):
        """An interactive tree view of layers in a stage.

        :param layer_actions: Layer actions container for the context menu.
        :type layer_actions: NxtActionContainer
        """
        super(LayerTreeView, self).__init__()
        self.actions = layer_actions
        self.alias_delegate = AliasDelegate()
        pencil_pix = QtGui.QPixmap(':icons/icons/pencil_hover.png')
        self.target_delegate = PixMapCheckboxDelegate(pencil_pix)
        layer_pix = QtGui.QPixmap(':icons/icons/layers_hover.png')
        self.display_delegate = PixMapCheckboxDelegate(layer_pix)
        self.mute_delgate = LetterCheckboxDelegeate('M')
        self.solo_delegate = LetterCheckboxDelegeate('S')
        self.lock_delegate = LetterCheckboxDelegeate('L')
        self.setItemDelegateForColumn(LayerModel.ALIAS_COLUMN,
                                      self.alias_delegate)
        self.setItemDelegateForColumn(LayerModel.TARGET_COLUMN,
                                      self.target_delegate)
        self.setItemDelegateForColumn(LayerModel.DISPLAY_COLUMN,
                                      self.display_delegate)
        self.setItemDelegateForColumn(LayerModel.MUTE_COLUMN,
                                      self.mute_delgate)
        self.setItemDelegateForColumn(LayerModel.SOLO_COLUMN,
                                      self.solo_delegate)
        self.setItemDelegateForColumn(LayerModel.LOCK_COLUMN,
                                      self.lock_delegate)
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.custom_context_menu)
        self.clicked.connect(self.on_item_clicked)
        self.doubleClicked.connect(self.on_item_dbl_clicked)
        self.refresh_indention()

    def setModel(self, model):
        """Sets up headers and expands tree.
        """
        super(LayerTreeView, self).setModel(model)
        header = self.header()
        header.setStretchLastSection(False)
        header.setDefaultSectionSize(LayerTreeView.SIZE)
        header.setSectionResizeMode(header.Fixed)
        if header.count():
            header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
            self.hideColumn(LayerModel.TARGET_COLUMN)
        self.expandAll()
        if self.model():
            self.model().modelReset.connect(self.expandAll)

    def refresh_indention(self):
        table_pref_key = user_dir.USER_PREF.LAYER_TABLE
        indent_pref = user_dir.USER_PREF.TREE_INDENT
        if user_dir.user_prefs.get(table_pref_key, False):
            self.expandAll()
            self.setIndentation(0)
        else:
            self.setIndentation(user_dir.user_prefs.get(indent_pref, 20))

    def on_item_clicked(self, clicked_idx):
        if not clicked_idx.column() == LayerModel.ALIAS_COLUMN:
            return
        if not self.model().stage_model:
            return
        layer = clicked_idx.internalPointer()
        layer_path = self.model().stage_model.get_layer_path(layer)
        if self.model().stage_model.get_layer_locked(layer_path):
            logger.warning('The layer "{}" is locked!'.format(layer.alias))
            self.model().stage_model.request_ding.emit()
            return
        self.model().stage_model.set_target_layer(layer_path)

    def on_item_dbl_clicked(self, clicked_idx):
        if not clicked_idx.column() == LayerModel.ALIAS_COLUMN:
            return
        if not self.model().stage_model:
            return
        layer = clicked_idx.internalPointer()
        layer_path = self.model().stage_model.get_layer_path(layer)
        if self.model().stage_model.get_layer_locked(layer_path):
            return
        self.model().stage_model.set_selection([nxt_path.WORLD])

    def custom_context_menu(self, pos):
        """Builds context menu to act upon right clicked layer.
        """
        index = self.indexAt(pos)
        layer = index.internalPointer()
        menu = QtWidgets.QMenu(self)
        if not layer:
            menu.addAction(self.actions.save_all_layers_action)
            menu.popup(QtGui.QCursor.pos())
            return
        stage_model = self.model().stage_model

        self.actions.save_layer_action.setData(layer)
        menu.addAction(self.actions.save_layer_action)
        self.actions.save_layer_as_action.setData(layer)
        menu.addAction(self.actions.save_layer_as_action)
        menu.addAction(self.actions.save_all_layers_action)
        if layer != stage_model.top_layer:
            self.actions.open_source_action.setData(layer)
            menu.addAction(self.actions.open_source_action)
            self.actions.remove_layer_action.setData(layer)
            menu.addAction(self.actions.remove_layer_action)
        menu.addSeparator()
        self.actions.change_color_action.setData(layer)
        menu.addAction(self.actions.change_color_action)

        def start_edit_alias():
            alias_idx = self.model().index(index.row(),
                                           LayerModel.ALIAS_COLUMN,
                                           index.parent())
            self.edit(alias_idx)
        menu.addAction("Edit Alias", start_edit_alias)

        if layer != stage_model.target_layer:
            layer_path = stage_model.get_layer_path(layer)

            def set_target_layer():
                stage_model.set_target_layer(layer_path)
            menu.addAction("Make Target Layer", set_target_layer)

        if layer != stage_model.display_layer:
            def set_disp_layer():
                stage_model.set_display_layer(layer)
            menu.addAction("Make Display Layer", set_disp_layer)

        self.actions.solo_layer_action.setData(layer)
        soloed = layer.get_soloed()
        text = 'Un-Solo' if soloed else 'Solo'
        menu.addAction(text, self.actions.solo_layer_action.trigger)

        self.actions.mute_layer_action.setData(layer)
        muted = layer.get_muted()
        text = 'Un-Mute' if muted else 'Mute'
        menu.addAction(text, self.actions.mute_layer_action.trigger)

        menu.addSeparator()
        self.actions.new_layer_above_action.setData(layer)
        menu.addAction(self.actions.new_layer_above_action)
        self.actions.new_layer_below_action.setData(layer)
        menu.addAction(self.actions.new_layer_below_action)
        self.actions.ref_layer_above_action.setData(layer)
        menu.addAction(self.actions.ref_layer_above_action)
        self.actions.ref_layer_below_action.setData(layer)
        menu.addAction(self.actions.ref_layer_below_action)
        menu.addSeparator()
        builtins_menu = QtWidgets.QMenu('Reference Builtin Graph')
        nxt_editor.main_window.populate_builtins_menu(qmenu=builtins_menu,
                                                      main_window=self.actions.main_window)
        menu.addMenu(builtins_menu)
        menu.popup(QtGui.QCursor.pos())


class LayerModel(QtCore.QAbstractItemModel):
    ALIAS_COLUMN = 0
    DISPLAY_COLUMN = 1
    TARGET_COLUMN = 2
    MUTE_COLUMN = 3
    SOLO_COLUMN = 4
    LOCK_COLUMN = 5
    HAS_SELECTED_COLUMN = 6
    UNSAVED = 7

    def __init__(self, stage_model):
        super(LayerModel, self).__init__()
        self.stage_model = stage_model
        self.stage_model.layer_mute_changed.connect(self.on_mute_changed)
        self.stage_model.layer_solo_changed.connect(self.on_solo_changed)
        self.stage_model.disp_layer_changed.connect(self.on_disp_changed)
        self.stage_model.target_layer_changed.connect(self.on_tgt_changed)
        self.stage_model.layer_color_changed.connect(self.on_color_changed)
        self.stage_model.layer_alias_changed.connect(self.on_alias_changed)
        self.stage_model.layer_added.connect(self.reset)
        self.stage_model.layer_removed.connect(self.reset)
        self.stage_model.selection_changed.connect(self.on_selection_changed)
        self.stage_model.effected_layers.signal.connect(self.on_command)
        self.layers_with_selected = []
        self.on_selection_changed()

    def reset(self):
        self.beginResetModel()
        self.endResetModel()

    def on_disp_changed(self):
        self.emit_columns_changed([self.DISPLAY_COLUMN])

    def on_tgt_changed(self, new_target):
        self.emit_columns_changed([self.ALIAS_COLUMN, self.TARGET_COLUMN])

    def on_command(self):
        self.emit_columns_changed([self.UNSAVED, self.ALIAS_COLUMN])

    def on_selection_changed(self):
        self.layers_with_selected = []
        for idx in self.get_all_layer_indices():
            for path in self.stage_model.get_selected_nodes():
                layer = idx.internalPointer()
                if self.stage_model.node_exists(path, layer):
                    self.layers_with_selected += [layer]
                    break
        # intentionally broken into 2 calls, because alias and has selected
        # are on opposite sides of the table, allowing emit columns changed
        # to do process both in a list would inavlidate the entire table.
        self.emit_columns_changed([self.HAS_SELECTED_COLUMN])
        self.emit_columns_changed([self.ALIAS_COLUMN])

    def emit_columns_changed(self, columns):
        """Shortcut to emit dataChanged for every row at the given columns

        :param columns: list of columns indices that changed
        :type columns: list
        """
        min_col = min(columns)
        max_col = max(columns)
        for index in self.get_all_layer_indices():
            top_left = self.createIndex(index.row(), min_col,
                                        index.internalPointer())
            bot_right = self.createIndex(index.row(), max_col,
                                         index.internalPointer())
            self.dataChanged.emit(top_left, bot_right)

    def get_all_layer_indices(self):
        """Returns list of all layer indices
        """
        top_idx = self.get_index_of_layer(self.stage_model.top_layer)
        out = self.descendant_indicies(top_idx)
        return out + [top_idx]

    def descendant_indicies(self, index):
        """Return all model indices which are descendants of given model index

        :param index: parent index
        :type index: QModelIndex
        :return: list of model indices
        :rtype: lists
        """
        layer = index.internalPointer()
        out = []
        i = 0
        for layer_dict in layer.sub_layers:
            sub_idx = self.index(i, 0, index)
            out += [sub_idx]
            out += self.descendant_indicies(sub_idx)
            i += 1
        return out

    def on_color_changed(self, layer_path):
        layer = self.stage_model.lookup_layer(layer_path)
        layer_index = self.get_index_of_layer(layer)
        top_left = self.createIndex(layer_index.row(), 0)
        bot_right = self.createIndex(layer_index.row(), self.columnCount()-1)
        self.dataChanged.emit(top_left, bot_right)

    def on_alias_changed(self, layer_path):
        layer = self.stage_model.lookup_layer(layer_path)
        layer_index = self.get_index_of_layer(layer)
        idx = self.createIndex(layer_index.row(), self.ALIAS_COLUMN)
        self.dataChanged.emit(idx, idx)

    def on_mute_changed(self, layer_paths):
        for path in layer_paths:
            layer = self.stage_model.lookup_layer(path)
            layer_index = self.get_index_of_layer(layer)
            top_left = self.createIndex(layer_index.row(), self.ALIAS_COLUMN)
            bot_right = self.createIndex(layer_index.row(), self.MUTE_COLUMN)
            self.dataChanged.emit(top_left, bot_right)

    def on_solo_changed(self, layer_paths):
        for path in layer_paths:
            layer = self.stage_model.lookup_layer(path)
            layer_index = self.get_index_of_layer(layer)
            top_left = self.createIndex(layer_index.row(), self.ALIAS_COLUMN)
            bot_right = self.createIndex(layer_index.row(), self.SOLO_COLUMN)
            self.dataChanged.emit(top_left, bot_right)

    def get_index_of_layer(self, layer):
        """Create and return a model index for given `layer`

        :param layer: layer to get model index of
        :type layer: Layer
        :return: Model index of given layer
        :rtype: QModelIndex
        """
        if not layer.parent_layer:
            return self.createIndex(0, 0, layer)
        layer_row = LayerModel.find_layer_index_in_parent(layer)
        parent_idx = self.get_index_of_layer(layer.parent_layer)
        return self.index(layer_row, self.ALIAS_COLUMN, parent_idx)

    def index(self, row, column, parent=None):
        """Returns a model index for the layer at the given row/column with
        given parent.
        Part of QAbstractItemModel
        """
        if not parent or not parent.isValid():
            return self.createIndex(row, column, self.stage_model.top_layer)
        parent_layer = parent.internalPointer()
        try:
            target_dict = parent_layer.sub_layers[row]
        except IndexError:
            return QtCore.QModelIndex()
        target_layer = target_dict.get('layer')
        return self.createIndex(row, column, target_layer)

    @staticmethod
    def find_layer_index_in_parent(layer):
        """Returns the index of given `layer` inside it's parent's list of
        sub layers

        :param layer: layer to find index of
        :type layer: Layer
        :return: index of given layer in parent layer, or 0
        :rtype: int
        """
        parent_layer = layer.parent_layer
        if not parent_layer:
            return 0
        i = 0
        for layer_dict in parent_layer.sub_layers:
            if layer_dict['layer'] == layer:
                return i
            i += 1
        return 0

    def parent(self, child_index):
        """Returns model index that represents the parent of the layer at
        given `child_index`
        Part of QAbstractItemModel
        """
        if not child_index.isValid():
            return QtCore.QModelIndex()
        layer = child_index.internalPointer()
        if not layer:
            return QtCore.QModelIndex()
        parent_layer = layer.parent_layer
        if not parent_layer:
            return QtCore.QModelIndex()
        parent_row = LayerModel.find_layer_index_in_parent(parent_layer)
        return self.createIndex(parent_row, 0, parent_layer)

    def rowCount(self, parent=None):
        """Returns count of rows(children) for the model, or parent specified
        by `parent`
        Part of QAbstractItemModel
        """
        if not parent or not parent.isValid():
            return 1
        if parent.column() > 0:
            return 0
        layer = parent.internalPointer()
        if not layer:
            return 0
        return len(layer.sub_layers)

    def columnCount(self, parent=None):
        """Returns number of columns in the model.
        Part of QAbstractItemModel
        """
        return 6

    def data(self, index, role=None):
        """Returns the data continaed at given model index with given role.
        Part of QAbstractItemModel
        """
        layer = index.internalPointer()
        column = index.column()
        if role == QtCore.Qt.BackgroundRole:
            color_hex = self.stage_model.get_layer_color(layer, local=False)
            return QtGui.QBrush(QtGui.QColor(color_hex))
        if role == QtCore.Qt.DisplayRole:
            if column == self.ALIAS_COLUMN:
                return layer.get_alias()
            return
        is_disp = layer == self.stage_model.display_layer
        is_target = layer == self.stage_model.target_layer
        is_locked = layer.get_locked()
        if role == QtCore.Qt.EditRole:
            if column == self.ALIAS_COLUMN:
                return layer.get_alias()
            if column == self.TARGET_COLUMN:
                return is_target
            if column == self.DISPLAY_COLUMN:
                return is_disp
            if column == self.MUTE_COLUMN:
                return layer.get_muted()
            if column == self.SOLO_COLUMN:
                return layer.get_soloed()
            if column == self.LOCK_COLUMN:
                return is_locked
            if column == self.HAS_SELECTED_COLUMN:
                return layer in self.layers_with_selected
            if column == self.UNSAVED:
                return layer.real_path in self.stage_model.effected_layers
            return
        if role == QtCore.Qt.CheckStateRole:
            if column == self.TARGET_COLUMN:
                return QtCore.Qt.Checked if is_target else QtCore.Qt.Unchecked
            if column == self.DISPLAY_COLUMN:
                return QtCore.Qt.Checked if is_disp else QtCore.Qt.Unchecked
            if column == self.MUTE_COLUMN:
                muted = layer.get_muted()
                return QtCore.Qt.Checked if muted else QtCore.Qt.Unchecked
            if column == self.SOLO_COLUMN:
                soloed = layer.get_soloed()
                return QtCore.Qt.Checked if soloed else QtCore.Qt.Unchecked
            if column == self.LOCK_COLUMN:
                return QtCore.Qt.Checked if is_locked else QtCore.Qt.Unchecked

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        """Allows editing of layers via qt model interface.
        """
        column = index.column()
        layer = index.internalPointer()
        # TODO: Make the internal pointer a layer path
        layer_path = self.stage_model.get_layer_path(layer)
        if role == QtCore.Qt.EditRole:
            if column != self.ALIAS_COLUMN:
                return False
            self.stage_model.set_layer_alias(value, layer)
            self.dataChanged.emit(index, index)
            return True
        if role == QtCore.Qt.CheckStateRole:
            if column == self.TARGET_COLUMN:
                if not value:
                    return False
                self.stage_model.set_target_layer(layer_path)
                return True
            if column == self.DISPLAY_COLUMN:
                if not value:
                    return False
                self.stage_model.set_display_layer(layer)
                return True
            if column == self.MUTE_COLUMN:
                self.stage_model.mute_toggle_layer(layer)
                return True
            if column == self.SOLO_COLUMN:
                self.stage_model.solo_toggle_layer(layer)
                return True
            if column == self.LOCK_COLUMN:
                self.stage_model.set_layer_locked(layer_path,
                                                  lock=not layer.get_locked())
                return True
        return False

    def flags(self, index):
        column = index.column()
        if column in (self.TARGET_COLUMN, self.DISPLAY_COLUMN,
                      self.MUTE_COLUMN, self.SOLO_COLUMN, self.LOCK_COLUMN):
            return (QtCore.Qt.ItemIsEnabled |
                    QtCore.Qt.ItemIsUserCheckable)
        return (QtCore.Qt.ItemIsEnabled |
                QtCore.Qt.ItemIsEditable)


class PixMapCheckboxDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, pixmap):
        """Paints given `pixmap` as checked and a grey cirlce as unchecked.

        :param pixmap: pixmap for checked
        :type pixmap: QtGui.QPixmap
        """
        self.pixmap = pixmap
        self.height = LayerTreeView.SIZE
        super(PixMapCheckboxDelegate, self).__init__()

    def paint(self, painter, option, index):
        self.initStyleOption(option, index)
        painter.setPen(QtCore.Qt.NoPen)
        if option.checkState == QtCore.Qt.CheckState.Checked:
            painter.setBrush(option.backgroundBrush)
            inner_rect = QtCore.QRect().united(option.rect)
            inner_rect = inner_rect.marginsRemoved(QtCore.QMargins(1, 1, 1, 1))
            painter.drawRoundedRect(inner_rect, 2, 2)
            inner_rect = inner_rect.marginsRemoved(QtCore.QMargins(2, 2, 2, 2))
            scaled = self.pixmap.size().scaled(inner_rect.size(),
                                               QtCore.Qt.KeepAspectRatio)
            painter.drawPixmap(inner_rect.x(), inner_rect.y(),
                               scaled.width(), scaled.height(), self.pixmap)
        else:
            painter.setBrush(QtCore.Qt.gray)
            center = option.rect.center()
            painter.drawEllipse(center, self.height/8, self.height/8)

    def sizeHint(self, option, index):
        return QtCore.QSize(self.height, self.height)

    def editorEvent(self, event, model, option, index):
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return False
        if event.type() != QtCore.QEvent.Type.MouseButtonRelease:
            return False
        prev_checked = option.checkState == QtCore.Qt.CheckState.Checked
        model.setData(index, not prev_checked, role=QtCore.Qt.CheckStateRole)
        return True


class LetterCheckboxDelegeate(QtWidgets.QStyledItemDelegate):
    def __init__(self, letter):
        """Paints given `letter` as checked and a grey circle as unchecked.

        :param letter: letter to display
        :type letter: str
        """
        self.letter = letter
        self.height = LayerTreeView.SIZE
        super(LetterCheckboxDelegeate, self).__init__()

    def paint(self, painter, option, index):
        self.initStyleOption(option, index)
        inner_rect = QtCore.QRect().united(option.rect)
        inner_rect = inner_rect.marginsRemoved(QtCore.QMargins(1, 1, 1, 1))
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(option.backgroundBrush)
        if option.checkState == QtCore.Qt.CheckState.Checked:
            painter.drawRoundedRect(inner_rect, 2, 2)
            painter.setPen(QtCore.Qt.white)
        else:
            painter.setPen(QtCore.Qt.gray)
        painter.drawText(inner_rect, QtCore.Qt.AlignCenter, self.letter)

    def sizeHint(self, option, index):
        return QtCore.QSize(self.height, self.height)

    def editorEvent(self, event, model, option, index):
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return False
        if event.type() != QtCore.QEvent.Type.MouseButtonRelease:
            return False
        prev_checked = option.checkState == QtCore.Qt.CheckState.Checked
        model.setData(index, not prev_checked, role=QtCore.Qt.CheckStateRole)
        return True


class AliasDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self):
        """Paints alias column of layer manager, paints in several different
        ways based on context gathered from layer model.
        """
        super(AliasDelegate, self).__init__()
        self.muted = False
        self.soloed = False
        self.locked = False
        self.is_tgt = False
        self.has_selected = False
        self.unsaved = False
        self.diag_bitmap = QtGui.QBitmap(':icons/icons/diagline_pattern.png')

    def paint_swatch(self, painter, brush, rect):
        swatch_size = QtCore.QSize(rect.height(), rect.height())
        swatch_rect = QtCore.QRect(rect.topLeft(), swatch_size)
        painter.setPen(QtCore.Qt.NoPen)
        if not self.is_tgt:
            painter.setPen(brush.color())
        if self.unsaved:
            diag_brush = QtGui.QBrush(brush.color(), self.diag_bitmap)
            painter.setBrush(diag_brush)
        else:
            painter.setBrush(brush)
        if self.soloed:
            painter.drawEllipse(swatch_rect)
        else:
            painter.drawRoundedRect(swatch_rect, 2, 2)

    def paint_bg(self, painter, bg_brush, rect):
        if self.muted:
            painter.setPen(bg_brush.color())
            pen = painter.pen()
            pen.setWidth(2)
            if not self.is_tgt:
                pen.setStyle(QtCore.Qt.DashLine)
            painter.setPen(pen)
        elif self.is_tgt:
            if self.unsaved:
                diag_brush = QtGui.QBrush(bg_brush.color(), self.diag_bitmap)
                painter.setBrush(diag_brush)
            else:
                painter.setBrush(bg_brush)
        painter.drawRoundedRect(rect, 2, 2)

    def paint_text(self, painter, text, text_rect):
        if self.soloed:
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
        if self.has_selected:
            font = painter.font()
            font.setUnderline(True)
            painter.setFont(font)
        if self.unsaved:
            text += '*'
        painter.setPen(QtCore.Qt.white)
        painter.drawText(text_rect, QtCore.Qt.AlignVCenter, text)

    def paint(self, painter, option, index):
        model = index.model()
        row = index.row()
        parent = index.parent()
        mute_index = model.index(row, LayerModel.MUTE_COLUMN, parent)
        self.muted = model.data(mute_index, role=QtCore.Qt.EditRole)
        solo_index = model.index(row, LayerModel.SOLO_COLUMN, parent)
        self.soloed = model.data(solo_index, role=QtCore.Qt.EditRole)
        lock_index = model.index(row, LayerModel.LOCK_COLUMN, parent)
        self.locked = model.data(lock_index, role=QtCore.Qt.EditRole)
        tgt_index = model.index(row, LayerModel.TARGET_COLUMN, parent)
        self.is_tgt = model.data(tgt_index, role=QtCore.Qt.EditRole)
        sel_idx = model.index(row, LayerModel.HAS_SELECTED_COLUMN, parent)
        self.has_selected = model.data(sel_idx, role=QtCore.Qt.EditRole)
        effected_idx = model.index(row, LayerModel.UNSAVED, parent)
        self.unsaved = model.data(effected_idx, role=QtCore.Qt.EditRole)
        # Global drawing info
        self.initStyleOption(option, index)
        inner_rect = QtCore.QRect().united(option.rect)
        inner_rect = inner_rect.marginsRemoved(QtCore.QMargins(1, 1, 1, 1))
        # Swatch
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtCore.Qt.NoBrush)
        self.paint_swatch(painter, option.backgroundBrush, inner_rect)
        # BG
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtCore.Qt.NoBrush)
        self.paint_bg(painter, option.backgroundBrush, inner_rect)
        # Text
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtCore.Qt.NoBrush)
        text_rect = inner_rect.adjusted(inner_rect.height() + 4, 0, 0, 0)
        pre_text_font = painter.font()
        self.paint_text(painter, option.text, text_rect)
        painter.setFont(pre_text_font)

    def sizeHint(self, option, index):
        known_size = super(AliasDelegate, self).sizeHint(option, index)
        return known_size + QtCore.QSize(known_size.height() + 4, 0)

    def editorEvent(self, event, model, option, index):
        if (event.type() == QtCore.QEvent.Type.MouseButtonDblClick and
            event.modifiers() == QtCore.Qt.ControlModifier):
            return False
        return True
