# Builtin
import logging
import time

# External
from Qt import QtWidgets, QtGui, QtCore

# Internal
from nxt_editor.dockwidgets.dock_widget_base import DockWidgetBase
from nxt import nxt_path
from nxt_editor.dockwidgets.layer_manager import LetterCheckboxDelegeate
import nxt_editor
from nxt_editor import colors

logger = logging.getLogger(nxt_editor.LOGGER_NAME)


class STARTS(object):
    SELECTION = 'Selection'
    FROM_SELECT = 'From selected'
    DESCENDANTS = 'Hierachy'  # TODO swap everywhere to desecendants.
    RUNNING = 'Running'


DEFAULT_STARTS = [
            STARTS.FROM_SELECT,
            STARTS.SELECTION,
            STARTS.DESCENDANTS]


class BuildView(DockWidgetBase):
    """Displays a combo box of start points as well as a list of the execution
    order implied by the selected start point. The combo box value can be
    edited to a node path to display execution order implied by that node path.
    Includes a button to execute the displayed order.
    """

    def __init__(self, parent=None):
        super(BuildView, self).__init__(title='Build', parent=parent)
        self.main_window = parent
        self.execute_actions = self.main_window.execute_actions
        self.execute_actions.pause_resume_exec_action.triggered.connect(self.pause_resume_pressed)
        self.stop_exec_action = self.execute_actions.stop_exec_action
        self.addAction(self.stop_exec_action)
        self.addAction(self.execute_actions.pause_resume_exec_action)
        self.main_widget = QtWidgets.QWidget()
        self.main_layout = QtWidgets.QVBoxLayout()
        self.main_widget.setLayout(self.main_layout)
        self.setWidget(self.main_widget)

        self.main_layout.addLayout(self.make_build_controls())
        self.build_table = BuildTable()
        self.main_layout.addWidget(self.build_table)

        self.pre_exec_start = ''
        self.in_running_mode = False
        self.build_model = None
        # One dock serves every tab, so what it was showing for a graph has
        # to be kept somewhere while another graph is in front of it.
        # Keyed by model uid.
        self._starts_by_model = {}  # uid -> start box text
        self._order_cache = {}  # uid -> (cache key, execution order)

    def make_build_controls(self):
        """Assemble a Layout of build controls including a combo box and
        execution control buttons to go above the build table.

        :return: A Qt layout of buttons and a combobox
        :rtype: QtWidgets.QLayout
        """
        # Start combo box
        self.starts_combo = QtWidgets.QComboBox()
        self.starts_combo.setEditable(True)
        self.starts_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.starts_combo.currentTextChanged.connect(self.start_text_changed)
        # Start action and button
        self.run_build_action = self.execute_actions.run_build_action
        self.run_build_action.triggered.connect(self.exec_build_pressed)
        self.restart_icon = QtGui.QIcon()
        rest_off_pix = QtGui.QPixmap(':icons/icons/reset.png')
        rest_hov_pix = QtGui.QPixmap(':icons/icons/reset_hover.png')
        self.restart_icon.addPixmap(rest_hov_pix, QtGui.QIcon.Active,
                                    QtGui.QIcon.Off)
        self.restart_icon.addPixmap(rest_off_pix, QtGui.QIcon.Normal,
                                    QtGui.QIcon.Off)
        self.restart_button = QtWidgets.QPushButton(self.restart_icon, '')
        self.restart_button.pressed.connect(self.run_build_action.trigger)
        self.restart_button.setEnabled(False)
        # Step button
        step_icon = self.execute_actions.step_build_action.icon()
        self.step_button = QtWidgets.QPushButton(step_icon, '')
        self.step_button.pressed.connect(self.step_build_pressed)
        # Pause Button
        self.pause_icon = QtGui.QIcon()
        pause_pixmap_on = QtGui.QPixmap(':icons/icons/pause.png')
        pause_pixmap_hov = QtGui.QPixmap(':icons/icons/pause_hover.png')
        self.pause_icon.addPixmap(pause_pixmap_on, QtGui.QIcon.Normal,
                             QtGui.QIcon.On)
        self.pause_icon.addPixmap(pause_pixmap_hov, QtGui.QIcon.Active,
                             QtGui.QIcon.Off)

        self.play_icon = QtGui.QIcon()
        play_pixmap_on = QtGui.QPixmap(':icons/icons/play.png')
        play_pixmap_hov = QtGui.QPixmap(':icons/icons/play_hover.png')
        self.play_icon.addPixmap(play_pixmap_on, QtGui.QIcon.Normal,
                             QtGui.QIcon.On)
        self.play_icon.addPixmap(play_pixmap_hov, QtGui.QIcon.Active,
                             QtGui.QIcon.Off)
        self.pause_resume_button = QtWidgets.QPushButton(self.play_icon, '')
        self.pause_resume_button.pressed.connect(self.pause_resume_pressed)
        # Find the selected node in the build
        self.find_icon = QtGui.QIcon()
        find_pixmap_on = QtGui.QPixmap(':icons/icons/find_startpoint.png')
        find_pixmap_hov = QtGui.QPixmap(':icons/icons/find_startpoint_hover.png')
        self.find_icon.addPixmap(find_pixmap_on, QtGui.QIcon.Normal,
                                 QtGui.QIcon.Off)
        self.find_icon.addPixmap(find_pixmap_hov, QtGui.QIcon.Active,
                                 QtGui.QIcon.Off)
        self.find_selected_button = QtWidgets.QPushButton(self.find_icon, '')
        self.find_selected_button.setToolTip('Scroll to the node selected in '
                                             'the graph')
        self.find_selected_button.pressed.connect(self.find_selected_pressed)
        # Stop button
        self.stop_button = QtWidgets.QPushButton(self.stop_exec_action.icon(),
                                                 '')
        self.stop_button.pressed.connect(self.stop_exec_action.trigger)

        self.controls_layout = QtWidgets.QHBoxLayout()
        self.controls_layout.addWidget(self.starts_combo, 1)
        self.controls_layout.addWidget(self.find_selected_button, 0)
        self.controls_layout.addWidget(self.pause_resume_button, 0)
        self.controls_layout.addWidget(self.step_button, 0)
        self.controls_layout.addWidget(self.stop_button, 0)
        self.controls_layout.addWidget(self.restart_button, 0)
        return self.controls_layout

    def find_selected_pressed(self):
        """Scroll the build to whatever is selected in the graph.

        The build is an execution order, not a picture of the graph, so a
        selected node is not always in it: it may be skipped, outside the
        start point's branch, or not executable at all. Say which, rather
        than appearing to do nothing.
        """
        if not self.stage_model:
            return
        selection = self.stage_model.selection
        if not selection:
            logger.info('Select a node in the graph to find it in the build.')
            return
        node_path = selection[0]
        if self.build_table.scroll_to_path(node_path):
            return
        logger.info('{} is not in this build.'.format(node_path))
        self.stage_model.request_ding.emit()

    def pause_resume_pressed(self):
        """When the pause resume button is pressed,
        pause or resume with context.
        """
        if self.stage_model.build_paused:
            self.stage_model.resume_build()
        elif self.in_running_mode:
            self.stage_model.pause_build()
        else:
            self.run_build_action.trigger()

    @property
    def visible_build(self):
        """If possible, retuns the list of nodes that are visible in the
        current build table.

        :return: list of node paths visible, if any.
        :rtype: list or None
        """
        if not self.build_model:
            return
        if not self.build_model.nodes:
            return
        return self.build_model.nodes

    def exec_build_pressed(self):
        """Exeucte current exec order(set in refresh_build_list)
        """
        vis_build = self.visible_build
        if not vis_build:
            return
        self.stage_model.execute_nodes(vis_build)

    def step_build_pressed(self):
        """When step build is presssed, either step the current build, or
        take first step into planned build.
        """
        vis_build = self.visible_build
        if not vis_build:
            return
        if not self.stage_model.is_build_setup():
            self.stage_model.setup_build(vis_build)
        self.stage_model.step_build()

    def set_stage_model(self, model):
        """Overload of dock widget base to disconnect previous model before
        changing and connect to new one after.

        The start point somebody chose belongs to their graph, not to this
        dock, so it is put away when their tab goes to the back and taken
        out again when it comes forward. Switching tabs used to blank the
        box, which emptied the build and read as the dock having given up.
        """
        outgoing = self.stage_model
        if outgoing is not None:
            start = self.starts_combo.currentText()
            self._starts_by_model[outgoing.uid] = start
        super(BuildView, self).set_stage_model(model)
        self._forget_closed_models()
        if not self.stage_model:
            return
        self.build_model = BuildModel(self.stage_model)
        self.build_table.setModel(self.build_model)
        self.main_widget.setEnabled(True)
        # on_starts_changed keeps whatever is in the box when it still means
        # something, so putting this back first is what restores it.
        remembered = self._starts_by_model.get(self.stage_model.uid, '')
        self.starts_combo.blockSignals(True)
        self.starts_combo.setEditText(remembered)
        self.starts_combo.blockSignals(False)
        self.on_starts_changed(self.stage_model.get_start_nodes())
        self.on_executing_changed(self.stage_model.executing)
        self.on_model_focus_changed(self.stage_model.node_focus)
        return

    def _forget_closed_models(self):
        """Drop what was remembered for graphs that are no longer open."""
        open_uids = set(self.main_window.open_files)
        for remembered in (self._starts_by_model, self._order_cache):
            for uid in list(remembered):
                if uid not in open_uids:
                    remembered.pop(uid)

    def set_stage_model_connections(self, model, connect):
        self.model_signal_connections = [
            (model.starts_changed, self.on_starts_changed),
            (model.comp_layer_changed, self.on_disp_layer_changed),
            (model.node_focus_changed, self.on_model_focus_changed),
            (model.executing_changed, self.on_executing_changed),
            (model.build_paused_changed, self.on_pause_change)
        ]
        super(BuildView, self).set_stage_model_connections(model, connect)

    def on_pause_change(self, paused):
        self.execute_actions.pause_resume_exec_action.setChecked(paused)
        if paused:
            icn = self.play_icon
        else:
            icn = self.pause_icon
        self.pause_resume_button.setIcon(icn)

    def on_executing_changed(self, executing):
        """Called when model's executing state is changed.
        Changes build view in and out of "running mode". Should disable
        and enable buttons as needed during execution.

        :param executing: Whether stage model is executing or not.
        :type executing: bool
        """
        self.stop_button.setEnabled(executing)
        self.stop_exec_action.setEnabled(executing)
        if executing == self.in_running_mode:
            return
        self.on_pause_change(not executing)
        self.in_running_mode = executing
        self.starts_combo.setEnabled(not self.in_running_mode)
        if self.in_running_mode:
            self.restart_button.setEnabled(True)
            self.pre_exec_start = self.starts_combo.currentText()
            self.starts_combo.setEditText(STARTS.RUNNING)
            self.stage_model.build_changed.connect(self.on_build_changed)
        else:
            self.restart_button.setEnabled(False)
            self.pause_resume_button.clearFocus()
            self.starts_combo.setEditText(self.pre_exec_start)

    def on_stage_model_destroyed(self):
        super(BuildView, self).on_stage_model_destroyed()
        self.build_model = None
        self.build_table.setModel(None)
        self.main_widget.setEnabled(False)

    def on_disp_layer_changed(self, disp_layer):
        self.refresh_build_table()

    def start_text_changed(self, text):
        self.refresh_build_table()

    def on_build_changed(self, new_build):
        self.build_model.nodes = new_build

    def refresh_build_table(self):
        """Dump current build table is and rebuild it based on start combo.
        """
        # t0 = time.time()
        if not self.stage_model or not self.build_model:
            # The combo box goes on emitting while the dock is being handed
            # from one graph to the next, and between the two there is no
            # graph to describe.
            return
        current_start = self.starts_combo.currentText()
        self.build_model.nodes = self.get_start_exec_order(current_start)
        # t1 = time.time()
        # logger.debug("Build Refresh took: " + str((t1-t0)))

    def get_start_exec_order(self, start):
        """Returns the execute order from given start.

        Walking a big graph for its execution order is not cheap, and the
        answer only changes when the graph or the selection does. What was
        worked out last time is kept per graph, so that coming back to a
        tab nobody has touched reads the answer off a shelf rather than
        walking the graph again.

        :param start: [description]
        :type start: [type]
        :return: [description]
        :rtype: [type]
        """
        if start == STARTS.RUNNING:
            # A running build moves under us, so there is nothing to keep.
            return self.stage_model.current_build_order
        key = (start, self.stage_model.comp_generation,
               tuple(self.stage_model.get_selected_nodes()))
        cached = self._order_cache.get(self.stage_model.uid)
        if cached and cached[0] == key:
            # A copy, so that what is kept stays the answer whatever the
            # table does with the list it is given.
            return list(cached[1])
        exec_order = list(self._walk_start_exec_order(start) or [])
        self._order_cache[self.stage_model.uid] = (key, exec_order)
        return list(exec_order)

    def _walk_start_exec_order(self, start):
        """Work out the execution order from a start box value.

        :param start: text from the start box
        :type start: str
        :return: node paths in execution order
        :rtype: list
        """
        # NOTE Duplicates some code from stage model, because it can't answer
        # the questions I needed to know. Implementations should merge someday
        if start == '':
            return []
        if start == nxt_path.WORLD:
            return []
        if start not in DEFAULT_STARTS:
            # Must be an attempt at a literal node path
            if not self.stage_model.node_exists(start):
                return []
            # t2 = time.time()
            exec_order = self.stage_model.get_exec_order(start)
            # t3 = time.time()
            # logger.debug("Big output " + str(t3-t2))
            return exec_order
        sel_node_paths = self.stage_model.get_selected_nodes()
        if not sel_node_paths:
            return []
        if start == STARTS.SELECTION:
            return sel_node_paths
        if start == STARTS.FROM_SELECT:
            if len(sel_node_paths) != 1:
                return []
            start_path = sel_node_paths[0]
            return self.stage_model.get_exec_order(start_path)
        if start == STARTS.DESCENDANTS:
            if len(sel_node_paths) != 1:
                return []
            desc = self.stage_model.get_descendants(sel_node_paths[0])
            return sel_node_paths + desc

    def on_starts_changed(self, real_starts):
        """Called when a startpoint is added or removed to keep starts combo
        up to date.
        """
        prev_value = self.starts_combo.currentText()
        self.starts_combo.clear()
        if real_starts:
            self.starts_combo.addItems(real_starts)
        self.starts_combo.addItems(DEFAULT_STARTS)
        # Keep what was in the box when it still describes a build, so that
        # a start point being added -- or a tab coming back to the front --
        # does not empty out a build somebody was reading. A typed node
        # path counts, even though the graph has no start points at all.
        if self.start_is_usable(prev_value, real_starts):
            self.starts_combo.setEditText(prev_value)
        elif real_starts:
            self.starts_combo.setEditText(real_starts[0])
        else:
            self.starts_combo.setEditText('')
        self.refresh_build_table()

    def start_is_usable(self, start, real_starts):
        """Whether a start box value still names a build we can show.

        :param start: text from the start box
        :type start: str
        :param real_starts: start point paths the graph has
        :return: bool
        """
        if not start:
            return False
        if start in DEFAULT_STARTS or start in real_starts:
            return True
        if start == STARTS.RUNNING:
            # The box says this while a build is running, and the build
            # running is not something to be talked out of.
            return True
        if not self.stage_model:
            return False
        return self.stage_model.node_exists(start)

    def on_model_focus_changed(self, new_focus):
        """When startpoint is concnered with selection, refresh table for
        focus changes.
        """
        if self.starts_combo.currentText() in DEFAULT_STARTS:
            self.refresh_build_table()


class BuildTable(QtWidgets.QTableView):
    """Displays a table of nodes for a build.
    The node highlighted in red will be the next run node if the graph is
    stepped or resumed.
    """
    def __init__(self):
        super(BuildTable, self).__init__()
        self.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.horizontalHeader().hide()
        self.verticalHeader().hide()
        self.break_delegate = LetterCheckboxDelegeate('B')
        self.setItemDelegateForColumn(BuildModel.BREAK_COLUMN,
                                      self.break_delegate)
        self.skip_delegate = LetterCheckboxDelegeate('S')
        self.setItemDelegateForColumn(BuildModel.SKIP_COLUMN,
                                      self.skip_delegate)
        self.clicked.connect(self.on_row_clicked)
        # TODO context menu and shift-click for +descendents.

    def on_row_clicked(self, clicked_idx):
        """When a row in the table is clicked, select and frame.
        """
        if clicked_idx.column() != BuildModel.PATH_COLUMN:
            return
        path_clicked = self.model()._nodes[clicked_idx.row()]
        self.model().stage_model.select_and_frame(path_clicked)

    def setModel(self, model):
        """Sets up headers.
        """
        super(BuildTable, self).setModel(model)
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        header.setDefaultSectionSize(28)
        header.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        if header.count():
            column = BuildModel.PATH_COLUMN
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.Stretch)
            self.hideColumn(BuildModel.START_COLUMN)
            self.hideColumn(BuildModel.NEXT_RUN_COLUMN)
        if not model:
            return
        model.stage_model.build_idx_changed.connect(self.on_build_idx_changed)

    def scroll_to_path(self, node_path):
        """Bring the row for a node path into view.

        :param node_path: node to scroll to
        :type node_path: str
        :return: whether the path was in the build at all
        :rtype: bool
        """
        build_model = self.model()
        if not build_model:
            return False
        try:
            row = build_model._nodes.index(node_path)
        except ValueError:
            return False
        model_index = build_model.index(row, BuildModel.PATH_COLUMN)
        # Top rather than centre: what you want to read after jumping to a
        # node is that node and what runs after it, and centring spends
        # half the view on what already ran.
        self.scrollTo(model_index, self.ScrollHint.PositionAtTop)
        # The table selects nothing by design, so the current index is what
        # marks where you were sent.
        self.setCurrentIndex(model_index)
        return True

    def on_build_idx_changed(self, build_idx):
        if self.model().stage_model.can_build_run():
            model_index = self.model().index(build_idx, 0)
        else:
            model_index = self.model().index(0, 0)
        self.scrollTo(model_index, self.ScrollHint.PositionAtCenter)


class BuildModel(QtCore.QAbstractTableModel):
    """A model of a series of nodes that reflects execution information
    including break status, start status, and which node is next to be run.
    """
    SKIP_COLUMN = 0
    BREAK_COLUMN = 1
    START_COLUMN = 2
    PATH_COLUMN = 3
    NEXT_RUN_COLUMN = 4

    def __init__(self, stage_model):
        super(BuildModel, self).__init__()
        """self._nodes is the execute order this build model with reflect
        answers about.
        """
        self.headers = ['Skip', 'Break', 'Start', 'Path', 'Next']
        self.stage_model = stage_model
        self._nodes = []
        self.stage_model.skips_changed.connect(self.on_skips_changed)
        self.stage_model.breaks_changed.connect(self.on_breaks_changed)
        self.stage_model.build_idx_changed.connect(self.on_build_idx_changed)

    @property
    def nodes(self):
        return self._nodes

    @nodes.setter
    def nodes(self, val):
        """Allows a direct reset of the model into a new execution order.
        """
        if val == self.nodes:
            return
        self.beginResetModel()
        self._nodes = val
        self.endResetModel()

    def on_skips_changed(self, new_skips):
        last_row = len(self.nodes) - 1
        self.dataChanged.emit(self.index(0, self.SKIP_COLUMN),
                              self.index(last_row, self.SKIP_COLUMN))

    def on_breaks_changed(self, new_breaks):
        last_row = len(self.nodes) - 1
        self.dataChanged.emit(self.index(0, self.BREAK_COLUMN),
                              self.index(last_row, self.BREAK_COLUMN))

    def on_build_idx_changed(self, new_idx):
        if not self.nodes:
            return
        last_row = len(self.nodes) - 1
        self.dataChanged.emit(self.index(0, self.PATH_COLUMN),
                              self.index(last_row, self.NEXT_RUN_COLUMN))

    def headerData(self, section, orientation, role):
        if orientation == QtCore.Qt.Horizontal:
            if role == QtCore.Qt.DisplayRole:
                return self.headers[section]

    def rowCount(self, index):
        if index.column() > 0 or not self.nodes:
            return 0
        return len(self.nodes)

    def columnCount(self, index):
        return len(self.headers)

    def data(self, index, role=None):
        row = index.row()
        column = index.column()
        idx_path = self.nodes[row]
        if role == QtCore.Qt.DisplayRole:
            if column == self.PATH_COLUMN:
                return idx_path
        next_run = False
        if self.stage_model.is_build_setup():
            next_run = row == self.stage_model.last_built_idx
        elif row == 0:
            next_run = True
        is_start = self.stage_model.get_is_node_start(idx_path)
        is_break = self.stage_model.get_is_node_breakpoint(idx_path)
        is_skip = self.stage_model.is_node_skippoint(idx_path)
        if role == QtCore.Qt.CheckStateRole:
            if column == self.START_COLUMN:
                return QtCore.Qt.Checked if is_start else QtCore.Qt.Unchecked
            if column == self.BREAK_COLUMN:
                return QtCore.Qt.Checked if is_break else QtCore.Qt.Unchecked
            if column == self.SKIP_COLUMN:
                return QtCore.Qt.Checked if is_skip else QtCore.Qt.Unchecked
            if column == self.NEXT_RUN_COLUMN:
                return QtCore.Qt.Checked if next_run else QtCore.Qt.Unchecked
        if role == QtCore.Qt.BackgroundRole:
            if column == self.BREAK_COLUMN and is_break:
                return colors.BREAK_COLOR
            if column == self.SKIP_COLUMN and is_skip:
                return colors.SKIP_COLOR
            if column == self.START_COLUMN and is_start:
                return colors.START_COLOR
            if column == self.PATH_COLUMN and next_run:
                return QtGui.QBrush(QtCore.Qt.red)
        if role == QtCore.Qt.ForegroundRole:
            if column == self.PATH_COLUMN:
                return QtGui.QBrush(QtCore.Qt.white)

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        column = index.column()
        if role != QtCore.Qt.CheckStateRole:
            return False
        path = self.nodes[index.row()]
        if column == self.BREAK_COLUMN:
            current_break = self.stage_model.get_is_node_breakpoint(path)
            self.stage_model.set_breakpoints([path], not current_break)
            return True
        if column == self.SKIP_COLUMN:
            modifiers = QtWidgets.QApplication.keyboardModifiers()
            if modifiers == QtCore.Qt.ShiftModifier:
                self.stage_model.toggle_descendant_skips([path])
            else:
                self.stage_model.toggle_skippoints([path])
            return True
        return False
