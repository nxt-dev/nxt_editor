# Built-in
import os
import sys
import logging
import subprocess
import traceback
from collections import OrderedDict
import webbrowser
from functools import partial
import time

# External
from Qt import QtWidgets
from Qt import QtGui
from Qt import QtCore

# Internal
import nxt_editor
from nxt_editor import user_dir
from nxt.session import Session
from nxt_editor.constants import EDITOR_VERSION
from nxt_editor.stage_view import StageView
from nxt_editor.stage_model import StageModel
from nxt_editor.dockwidgets import (DockWidgetBase, CodeEditor, PropertyEditor,
                                    HotkeyEditor, LayerManager, OutputLog,
                                    HistoryView, WidgetBuilder, BuildView,
                                    FindRepDockWidget)
from nxt_editor.dockwidgets.output_log import (FileTailingThread,
                                               QtLogStreamHandler)
from nxt_editor.dockwidgets.code_editor import NxtCodeEditor
from nxt import nxt_log, nxt_io, nxt_layer
from nxt_editor.dialogs import (NxtFileDialog, NxtWarningDialog,
                                UnsavedLayersDialogue, UnsavedChangesMessage)
from nxt_editor import actions, LoggingSignaler
from nxt.constants import (API_VERSION, GRAPH_VERSION, USER_PLUGIN_DIR,
                           NXT_DCC_ENV_VAR, is_standalone)
from nxt.remote.client import NxtClient
import nxt.remote.contexts
from nxt_editor import qresources


logger = logging.getLogger(nxt_editor.LOGGER_NAME)


class MainWindow(QtWidgets.QMainWindow):

    """The main window of the nxt UI. Includes the menu bar, tool bar, and dock widgets."""

    tab_changed = QtCore.Signal()
    close_signal = QtCore.Signal()
    new_log_signal = QtCore.Signal(logging.LogRecord)

    def __init__(self, filepath=None, parent=None, start_rpc=True):
        """Create NXT window.

        :param parent: parent to attach this UI to.
        :type parent: QtWidgets.QtWidgets.QWidget
        """
        self.in_startup = True
        pixmap = QtGui.QPixmap(':icons/icons/nxt.svg')
        self.splash_screen = QtWidgets.QSplashScreen(pixmap)
        self.splash_screen.show()
        self.splash_screen.showMessage('Starting nxt...',
                                       QtCore.Qt.AlignCenter, QtCore.Qt.white)
        QtWidgets.QApplication.processEvents()
        super(MainWindow, self).__init__(parent=parent)
        self.new_log_signal.connect(self.handle_remote_log)
        old_cwd = os.getcwd()
        ui_dir = os.path.dirname(__file__)
        os.chdir(ui_dir)
        # Test to see if we're launching from a git branch, if so the title
        # bar will be updated for easy reference.

        # Used to hide the stderr from the user as it doesn't matter
        f = open(nxt_io.generate_temp_file('NxtGitErr'))
        try:
            git_out = subprocess.check_output(["git", "branch"],
                                              stderr=f).decode("utf8")
            cur = next(line for line in git_out.split("\n")
                       if line.startswith("*"))
            current_branch = cur.strip("*").strip()
        except:  # Broad because Maya
            # Failed to run git branch, attempting fallback method
            try:
                with open('../../.git/HEAD') as f:
                    head = f.read()
                _, __, current_branch = head.rpartition('/')
            except:
                # Could not determine git branch, must be pip package.
                current_branch = ''
        finally:
            f.close()
        os.chdir(old_cwd)
        if is_standalone():
            context = 'standalone'
        else:
            context = os.environ.get(NXT_DCC_ENV_VAR) or ''
        self.host_app = context
        self.setWindowTitle("nxt {} - Editor v{} | Graph v{} | API v{} "
                            "(Python {}) {}".format(self.host_app,
                                                    EDITOR_VERSION.VERSION_STR,
                                                    GRAPH_VERSION.VERSION_STR,
                                                    API_VERSION.VERSION_STR,
                                                    '.'.join([str(n) for n in sys.version_info[:3]]),
                                                    current_branch))
        self.setObjectName('Main Window')
        self.zoom_keys = QtGui.QKeySequence(QtCore.Qt.Key_Alt)
        self.zoom_keys_down = False
        self._held_keys = []
        self._closing = False
        self.last_focused_start = 0  # Start point focus tracker
        # FIXME: Fix with MV signal
        self.last_focused_tab = -1  # Tab tracker for upating the comp layer
        # set app icon
        self.app_icon = QtGui.QIcon(pixmap)
        self.setWindowIcon(self.app_icon)

        # set style sheet
        style_file = QtCore.QFile(':styles/styles/dark/dark.qss')
        style_file.open(QtCore.QFile.ReadOnly)
        self.stylesheet = str(style_file.readAll())
        self.setStyleSheet(self.stylesheet)

        # fonts
        font_db = QtGui.QFontDatabase()
        font_db.addApplicationFont(":fonts/fonts/RobotoMono/RobotoMono-Regular.ttf")
        font_db.addApplicationFont(":fonts/fonts/Roboto/Roboto-Regular.ttf")

        # nxt object in charge of loaded graphs
        self.nxt = Session()

        # APPLICATION WIDE ACTIONS
        # TODO: All the actions should be connected to functions in nxt not
        #  view
        self.splash_screen.showMessage('Setting up hotkeys...',
                                       QtCore.Qt.AlignCenter, QtCore.Qt.white)
        self.app_actions = actions.AppActions(self)
        self.addActions(self.app_actions.actions())
        # NODE ACTIONS
        self.node_actions = actions.NodeActions(self)
        # PROPERTY ACTIONS
        self.property_manager_actions = actions.PropertyEditorActions(self)
        # NODE COMMENT ACTIONS
        self.node_comment_actions = actions.NodeCommentActions(self)
        # LAYER ACTIONS
        self.layer_actions = actions.LayerActions(self)
        # ALIGNMENT ACTIONS
        self.alignment_actions = actions.AlignmentActions(self)
        # DISPLAY ACTIONS
        self.display_actions = actions.DisplayActions(self)
        # VIEW ACTIONS
        self.view_actions = actions.StageViewActions(self)
        # EXEC ACTIONS
        self.execute_actions = actions.ExecuteActions(self)
        self.addAction(self.execute_actions.stop_exec_action)
        # CODE EDITOR ACTIONS
        self.code_editor_actions = actions.CodeEditorActions(self)
        # TOOL BARS
        self.authoring_toolbar = NodeAuthoringToolBar(self)
        self.addToolBar(self.authoring_toolbar)
        self.execute_toolbar = ExecuteToolBar(self)
        self.addToolBar(self.execute_toolbar)
        self.display_toolbar = DisplayToolBar(self)
        self.addToolBar(self.display_toolbar)
        self.align_distribute_toolbar = AlignDistributeToolBar(self)
        self.addToolBar(self.align_distribute_toolbar)
        # TABS WIDGET
        self.open_files_tab_widget = OpenFilesTabWidget(parent=self)
        self.open_files = {}  # TODO: Doesn't this duplicate what Nxt does?
        self.previous_view = None
        # graph tabs
        self.open_files_tab_widget.currentChanged.connect(self.on_tab_change)
        self.setCentralWidget(self.open_files_tab_widget)
        self.splash_screen.showMessage('Setting up dockwidgets...',
                                       QtCore.Qt.AlignCenter, QtCore.Qt.white)
        # Dock Widgets
        # hotkey editor
        self.hotkey_editor = HotkeyEditor(parent=self)
        self.hotkey_editor.hide()

        # property editor
        self.property_editor = PropertyEditor(parent=self)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.property_editor)

        # code editor
        self.code_editor = CodeEditor(parent=self)
        self.code_editor.editor.viewport().installEventFilter(self)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, self.code_editor)

        # Find and Replace
        self.find_rep = FindRepDockWidget(parent=self)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.find_rep)
        self.find_rep.hide()
        # layer manager
        self.layer_manager = LayerManager(parent=self)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.layer_manager)

        # history view
        self.history_view = HistoryView(parent=self)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.history_view)

        # build View
        self.build_view = BuildView(parent=self)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.build_view)

        # output log
        self.output_log = OutputLog(parent=self)
        self.output_log.hide()
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.output_log)

        # workflow tools
        self.workflow_tools = WidgetBuilder(parent=self)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.workflow_tools)

        self.setCorner(QtCore.Qt.BottomRightCorner,
                       QtCore.Qt.RightDockWidgetArea)
        self.setCorner(QtCore.Qt.BottomLeftCorner,
                       QtCore.Qt.LeftDockWidgetArea)
        self.setTabPosition(QtCore.Qt.AllDockWidgetAreas,
                            QtWidgets.QTabWidget.North)

        # status bar
        self.status_bar = QtWidgets.QStatusBar()
        self.status_bar.setSizeGripEnabled(False)
        self.status_bar.setContentsMargins(4, 4, 4, 4)
        self.status_bar.setStyleSheet('color: lightGrey; background-color: #232323; border: 4px solid #3E3E3E')
        self.setStatusBar(self.status_bar)

        self.log_button = QtWidgets.QPushButton("Show Log")
        self.log_button.setMinimumWidth(75)
        self.log_button.setStyleSheet(self.stylesheet)
        self.output_log.visibilityChanged.connect(self.refresh_log_button)
        self.log_button.clicked.connect(self.log_button_clicked)
        self.status_bar.addPermanentWidget(self.log_button)
        self.refresh_log_button()

        self.logger = logging.getLogger('nxt')
        self.logger.addHandler(StatusBarHandler(self.status_bar))

        self.state_last_hidden = None
        # TODO set and load default geometry
        # TODO determine and create sensible default position and size for the window, perhaps 80% of available screen?
        # print QDesktopWidget.availableGeometry(self)
        self.resize(1600, 800)
        self.resizeDocks([self.property_editor, self.code_editor], [400, 300], QtCore.Qt.Vertical)

        if filepath:
            self.load_file(filepath=filepath)
        else:
            self.new_tab()
        # menu bar
        # TODO: Depends on dock widgets this should change
        self.menu_bar = MenuBar(self)
        self.setMenuBar(self.menu_bar)
        self.menuBar().setNativeMenuBar(False)
        self.display_actions.resolve_action.setChecked(True)
        # Rpc startup
        self.rpc_log_tail = None
        if start_rpc:
            self.startup_rpc_server(join=False)
        # Should this be a signal? Like Startup done, now you can refresh?
        self.splash_screen.finish(self)
        self.in_startup = False
        t = QtCore.QTimer()
        t.setInterval(256)

        def failure_check():
            if self.view:
                self.view.failure_check()
            t.stop()
        t.timeout.connect(failure_check)
        t.start()

        app = QtWidgets.QApplication.instance()
        app.aboutToQuit.connect(self.shutdown_rpc_server)

    # RPC
    def startup_rpc_server(self, join=True):
        t = StartRPCThread(self)
        t.start()
        if join:
            t.wait()
        else:
            txt = 'Waiting on rpc server...'
            txt_len = len(txt)
            self.count = 0

            def tick():
                self.splash_screen.showMessage(txt[:self.count % -txt_len],
                                               QtCore.Qt.AlignCenter,
                                               QtCore.Qt.white)
                self.count += 1
            timer = QtCore.QTimer()
            timer.setInterval(100)
            timer.timeout.connect(tick)
            t.finished.connect(timer.stop)
            timer.start()
            while not t.isFinished():
                QtWidgets.QApplication.processEvents()

    @staticmethod
    def handle_remote_log(record):
        logger.handle(record)

    def shutdown_rpc_server(self):
        if self.model:
            self.model.processing.emit(True)
        self.safe_stop_rpc_tailing()
        self.nxt.shutdown_rpc_server()
        if self.model:
            self.model.processing.emit(False)
        if not self.rpc_log_tail:
            return
        wait_started = time.time()
        while not self.rpc_log_tail.isFinished():
            QtWidgets.QApplication.processEvents()
            if time.time() - wait_started > 5:
                logger.error('Failed to stop rpc log tail!')
                return
        self.rpc_log_tail = None

    def safe_stop_rpc_tailing(self):
        if not self.rpc_log_tail:
            return
        self.handle_rpc_tailing_signals(False)
        self.rpc_log_tail.requestInterruption()

    def handle_rpc_tailing_signals(self, state):
        if not self.rpc_log_tail:
            return
        raw_write_func = self.output_log._write_raw_output
        rich_write_func = self.output_log.write_rich_output
        if state:
            self.rpc_log_tail.new_text.connect(raw_write_func)
            self.rpc_log_tail.new_text.connect(rich_write_func)
        else:
            self.rpc_log_tail.new_text.disconnect(raw_write_func)
            self.rpc_log_tail.new_text.disconnect(rich_write_func)

    def event(self, event):
        if event.type() == QtCore.QEvent.WindowDeactivate:
            self._held_keys = []
            self.zoom_keys_down = False
        return super(MainWindow, self).event(event)

    @staticmethod
    def set_waiting_cursor(state=True):
        if state:
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        else:
            QtWidgets.QApplication.restoreOverrideCursor()

    @staticmethod
    def create_remote_context(place_holder_text='',
                              interpreter_exe=sys.executable,
                              context_graph=None, exe_script_args=()):
        cur_context = nxt.remote.contexts.get_current_context_exe_name()
        pop_up = QtWidgets.QDialog()
        pop_up.setWindowTitle('Create context for "{}"'.format(cur_context))
        v_layout = QtWidgets.QVBoxLayout()
        pop_up.setLayout(v_layout)
        label = QtWidgets.QPlainTextEdit()
        info = ('Create remote context for your host '
                'Python interpreter/DCC\n'
                'Type your desired name in the box below '
                'and click create.'.format(cur_context))
        label.setPlainText(info)
        label.setReadOnly(True)
        font_metric = QtGui.QFontMetrics(label.document().defaultFont())
        text_size = font_metric.size(QtCore.Qt.TextExpandTabs, info)
        label.setFixedSize(text_size.width() + 50, text_size.height() + 30)
        v_layout.addWidget(label)
        h_layout = QtWidgets.QHBoxLayout()
        v_layout.addLayout(h_layout)
        name = QtWidgets.QLineEdit()
        name.setPlaceholderText(str(place_holder_text))
        name.setText(str(place_holder_text))
        create_button = QtWidgets.QPushButton('Create!')
        h_layout.addWidget(name)
        h_layout.addWidget(create_button)

        def do_create():
            try:
                nxt.create_context(name.text(),
                                   interpreter_exe=interpreter_exe,
                                   context_graph=context_graph,
                                   exe_script_args=exe_script_args)
                pop_up.close()
            except (IOError, NameError) as e:
                info = str(e)
                msg = 'Failed to create context!'
                logger.error(info)
                nxt_editor.dialogs.NxtWarningDialog.show_message(msg,
                                                                 info=info)

        create_button.pressed.connect(do_create)
        pop_up.exec_()

    def get_global_actions(self):
        """Get a list of NxtActions with the WindowShortcut context
        :return: List of NxtActions
        """
        global_actions = []
        for action in self.get_all_nxt_actions():
            if action.shortcutContext() == QtCore.Qt.WindowShortcut:
                global_actions += [action]
        return global_actions

    def get_all_nxt_actions(self):
        """Get a list of all NxtActions via the NxtActionContainer objects
        :return: List of NxtActions
        """
        all_actions = []
        all_containers = self.findChildren(actions.NxtActionContainer)
        for container in all_containers:
            all_actions += container.actions()
        return all_actions

    def get_hotkey_map(self):
        """Get a map of NxtAction containers and their actions in an
        ordered dict where each key is a row row for a QAbstractTableModel.
        :return: OrderedDict
        """
        hotkeys = OrderedDict()
        # Action container objects in the order we wish to display them
        action_containers = [self.app_actions, self.alignment_actions,
                             self.display_actions, self.view_actions,
                             self.layer_actions, self.node_actions,
                             self.property_manager_actions,
                             self.node_comment_actions,
                             self.execute_actions, self.code_editor_actions]
        for container in action_containers:
            hotkeys[container.objectName()] = container.get_action_data()
        return hotkeys

    @property
    def view(self):
        return self.get_current_view()

    @property
    def model(self):
        if self.view:
            return self.view.model

    def new_tab(self, initial_stage=None, update=True):
        """Open a new graph view, optionally on a specific initial graph.
        Create necessary model, pass to nxt to connect graph to model,
        create tab for new file.
        :param initial_stage: Graph object to make new view of.
        :type initial_stage: nxt.core.Graph.Graph
        :param update: If true the different views will update
        :type update: bool
        """
        self.set_waiting_cursor(True)
        # get new graph
        if initial_stage:
            stage = initial_stage
        else:
            stage = self.nxt.new_file()
        # create model
        model = StageModel(stage=stage)
        model.processing.connect(self.set_waiting_cursor)
        model.request_ding.connect(self.ding)
        model.layer_alias_changed.connect(partial(self.update_tab_title, model))
        # create view
        view = StageView(model=model, parent=self)
        # setup tab
        tab_index = self.open_files_tab_widget.count()
        self.open_files[model.uid] = {'stage': stage, 'model': model,
                                      'view': view}
        self.open_files_tab_widget.addTab(view, stage._name)
        if update:
            self.open_files_tab_widget.setCurrentIndex(tab_index)
            self.layer_manager.set_stage_model(model)
            model.layer_color_changed.connect(self.update_target_color)
            model.target_layer_changed.connect(self.update_target_color)
            model.comp_layer_changed.connect(self.update_target_color)
            self.update_target_color()
            self.update()  # TODO: Make this better
        self.set_waiting_cursor(False)

    @staticmethod
    def ding():
        if user_dir.user_prefs.get(user_dir.USER_PREF.DING, True):
            QtWidgets.QApplication.instance().beep()

    def center_view(self):
        target_graph_view = self.get_current_view()
        if target_graph_view:
            target_graph_view.centerOn(0, 0)

    def load_file(self, filepath=None):
        """Open an NxtFileDialog to allow user to select .nxt file to open.
        Attempt to open resulting choice. If an attempt is made to open a
        file that is already open, we will just focus that  tab.
        :param filepath: path to file on disk
        :type filepath: str

        :return: bool -- whether or not the file was successfully loaded.
        :rtype: bool
        """
        if not filepath:
            # TODO: The dialog should register the last opened folder into the
            #  user_dir and use that as the starting dir for file dialogs
            #  that aren't intrinicly tied to a layers real_path
            real_path = None
            try:
                real_path = self.model.stage.top_layer.real_path
            except AttributeError:
                pass
            _dir = os.path.dirname(real_path or os.getcwd())
            potential_path = NxtFileDialog.system_file_dialog(base_dir=_dir)
            if not potential_path:
                logger.debug("No file selected to load.")
                return
        else:
            potential_path = filepath
        # Try to load the file path via nxt
        self.set_waiting_cursor(True)
        new_stage = None
        try:
            new_stage = self.nxt.load_file(potential_path)
        except IOError as e:
            NxtWarningDialog.show_message("Failed to Open", str(e))
        self.set_waiting_cursor(False)
        if new_stage:
            self.new_tab(initial_stage=new_stage, update=not self.in_startup)
            user_dir.editor_cache[user_dir.USER_PREF.LAST_OPEN] = potential_path

    def save_open_tab(self):
        """Save the file that corresponds to the currently selected tab."""
        self.nxt.save_file(self.get_current_tab_file_path())

    def save_all_layers(self):
        if not self.model:
            return
        for layer in self.model.stage._sub_layers:
            self.save_layer(layer)

    def save_layer(self, layer=None):
        if not layer:
            layer = self.model.target_layer
        if not layer:
            return
        if not layer.real_path:
            layer_saved = self.save_layer_as(layer, open_in_new_tab=False)
        else:
            self.set_waiting_cursor(True)
            self.nxt.save_layer(layer)
            layer_saved = True
            user_dir.editor_cache[user_dir.USER_PREF.LAST_OPEN] = layer.real_path
        self.view.update_filepath()
        if layer_saved:
            try:
                self.model.effected_layers.remove(layer.real_path)
            except KeyError:  # Layer may not have been changed
                pass
        self.model.layer_saved.emit(layer.real_path)
        self.set_waiting_cursor(False)

    def save_layer_as(self, layer=None, open_in_new_tab=True):
        """Prompt the user to select a save location for a layer.

        If no layer is specified the target layer is used.

        :param layer: path to prompt for, defaults to target layer.
        :type layer: nxt_layer.SpecLayer, optional
        :param open_in_new_tab: If True, open the layer in a new tab after save
        :type start: str, optional
        :return: True if save was successful, false otherwise.
        :rtype: bool
        """
        if not layer:
            layer = self.model.target_layer
        old_real_path = layer.real_path
        old_path = layer.filepath
        if not old_real_path:
            open_in_new_tab = False
            base_dir = os.path.join(user_dir.USER_DIR, layer.get_alias())
        else:
            base_dir = layer.real_path
        caption = 'Save "{}"'.format(layer.get_alias())
        save_path = NxtFileDialog.system_file_dialog(base_dir, 'save',
                                                     caption=caption)
        if not save_path:
            return False
        self.set_waiting_cursor(True)
        self.nxt.save_layer(layer, filepath=save_path)
        user_dir.editor_cache[user_dir.USER_PREF.LAST_OPEN] = layer.real_path
        layer.filepath = old_path
        if open_in_new_tab:
            self.load_file(save_path)
            layer.real_path = old_real_path
        elif layer is self.model.top_layer:
            tab_idx = self.open_files_tab_widget.currentIndex()
            self.open_files_tab_widget.setTabText(tab_idx, layer.alias)
        tab_idx = self.open_files_tab_widget.currentIndex()
        self.on_tab_change(tab_idx)
        self.set_waiting_cursor(False)
        return True

    def open_source(self, layer):
        if not layer:
            layer = self.model.display_layer
        self.load_file(layer.real_path)

    def find_startpoint(self):
        """Cycles through start points"""
        if not self.model:
            return
        start_nodes = self.model.get_start_nodes()
        start_node_len = len(start_nodes)
        if not start_node_len:
            logger.warning("No start nodes found.")
            return
        in_range = self.last_focused_start in range(start_node_len)
        if in_range:
            idx = self.last_focused_start
        else:
            idx = 0
            self.last_focused_start = idx
        self.last_focused_start += 1
        self.model.select_and_frame(start_nodes[idx])

    def align_left(self):
        logger.info('align left')

    def align_hcenter(self):
        logger.info('align hcenter')

    def align_right(self):
        logger.info('align right')

    def align_top(self):
        logger.info('align top')

    def align_vcenter(self):
        logger.info('align vcenter')

    def align_bottom(self):
        logger.info('align bottom')

    def distribute_horizontal(self):
        logger.info('distribute horizontal')

    def distribute_vertical(self):
        logger.info('distribute vertical')

    def undo(self):
        current_view = self.get_current_view()
        if current_view:
            model = current_view.model
            model.undo()

    def redo(self):
        current_view = self.get_current_view()
        if current_view:
            model = current_view.model
            model.redo()

    def refresh_log_button(self):
        if self.output_log.isVisible():
            self.log_button.setText("Hide Log")
        else:
            self.log_button.setText("Show Log")

    def log_button_clicked(self):
        if self.output_log.isVisible():
            self.output_log.hide()
            return
        self.output_log.show()
        self.output_log.raise_()

    def update_tab_title(self, model, layer_changed):
        tab_idx = self.open_files_tab_widget.currentIndex()
        view = self.open_files_tab_widget.widget(tab_idx)
        cur_model = view.model
        if model is not cur_model:
            return
        if layer_changed != model.top_layer.real_path:
            return
        new_title = model.get_layer_alias(layer_changed)
        self.open_files_tab_widget.setTabText(tab_idx, new_title)

    def on_tab_change(self, tab_index):
        """Happens every tab change. Used to keep the dock widgets aware of
        the current graph model.
        """
        view = self.open_files_tab_widget.widget(tab_index)
        if not view:
            return
        if view == self.previous_view:
            return
        self.previous_view = view
        uid = view.model.uid
        self.last_focused_start = 0
        if uid in self.open_files.keys():
            model = self.open_files[uid]['model']
            layer_path = model.get_layer_path(model.top_layer)
            title = model.get_layer_alias(layer_path)
            self.open_files_tab_widget.setTabText(tab_index, title)
            self.property_editor.set_stage_model(model)
            self.code_editor.set_stage_model(model)
            self.layer_manager.set_stage_model(model)
            self.history_view.set_stage_model(model)
            self.workflow_tools.set_stage_model(model)
            self.build_view.set_stage_model(model)
            self.find_rep.set_stage_model(model)
            self.output_log.set_stage_model(model)
            self.update_target_color()
            logger.debug("Successfully set up new tab.")
            self.last_focused_tab = tab_index
            self.update_implicit_action()
            view.toggle_grid(
                user_dir.user_prefs.get(user_dir.USER_PREF.SHOW_GRID, True)
            )
            model.destroy_cmd_port.connect(self.update_cmd_port_action)
        else:
            logger.critical("Failed to set up new tab.")
        view.setFocus()
        self.tab_changed.emit()

    def get_current_tab_file_path(self):
        """Get the file path of the currently open tab.

        :return: File path of the currently open tab.
        :rtype:str
        """
        if not self.model:
            return
        return self.model.get_layer_path(self.model.stage.top_layer)

    def get_current_tab_model(self):
        """Get the file path of the currently open tab.
        :return: File path of the currently open tab.
        """
        idx = self.open_files_tab_widget.currentIndex()
        widget = self.open_files_tab_widget.widget(idx)
        if widget:
            uid = widget.model.uid
            return self.open_files[uid]['model']

    def get_current_view(self):
        return self.open_files_tab_widget.currentWidget()

    def update_cmd_port_action(self):
        self.execute_actions.enable_cmd_port_action.blockSignals(True)
        if self.model:
            state = self.model.use_cmd_port
        else:
            state = False
        self.execute_actions.enable_cmd_port_action.setChecked(state)
        self.execute_actions.enable_cmd_port_action.blockSignals(False)

    def update_implicit_action(self):
        self.view_actions.implicit_action.blockSignals(True)
        state = self.model.implicit_connections
        self.view_actions.implicit_action.setChecked(state)
        self.view_actions.implicit_action.blockSignals(False)

    def update_target_color(self):
        disp_layer = self.model.display_layer
        color = self.model.get_layer_color(disp_layer)

        # update widgets
        self.open_files_tab_widget.setStyleSheet('padding: 1; border: 1px solid %s' % color)
        self.open_files_tab_widget.update()
        self.code_editor.update_border_color()
        self.property_editor.update_styles()

    def keyPressEvent(self, event):
        key = event.key()
        if key not in self._held_keys:
            self._held_keys.append(key)
        self.zoom_keys_down = False
        match = QtGui.QKeySequence(*self._held_keys).matches(self.zoom_keys)
        if match == QtGui.QKeySequence.SequenceMatch.ExactMatch:
            self.zoom_keys_down = True
        event.accept()

    def keyReleaseEvent(self, event):
        key = event.key()
        if key in self._held_keys:
            self._held_keys.remove(key)
        self.zoom_keys_down = False
        match = QtGui.QKeySequence(*self._held_keys).matches(self.zoom_keys)
        if match == QtGui.QKeySequence.SequenceMatch.ExactMatch:
            self.zoom_keys_down = True

    def eventFilter(self, widget, event):
        # enter editing after update_code_is_local
        if event.type() == QtCore.QEvent.MouseButtonDblClick:
            if isinstance(widget.parent(), NxtCodeEditor):
                self.code_editor.update_code_is_local()
                self.code_editor.enter_editing()

        return False

    def show(self):
        """Centering after the window is shown because the center is based on the window's size."""
        # Todo: add previous rect to the bookmarks data for the layer - use this instead of center if it exists
        super(MainWindow, self).show()
        self.center_view()

    def showEvent(self, event):
        if self.state_last_hidden:
            self.restoreState(self.state_last_hidden)
            super(MainWindow, self).showEvent(event)
            return
        state_key = user_dir.EDITOR_CACHE.WINODW_STATE
        geo_key = user_dir.EDITOR_CACHE.MAIN_WIN_GEO
        saved_state = user_dir.editor_cache.get(state_key)
        if saved_state:
            self.restoreState(QtCore.QByteArray(saved_state))
        saved_geo = user_dir.editor_cache.get(geo_key)
        if saved_geo:
            self.restoreGeometry(QtCore.QByteArray(saved_geo))
        state_key = user_dir.EDITOR_CACHE.NODE_PROPERTY_STATE
        property_state = user_dir.editor_cache.get(state_key)
        if property_state:
            self.property_editor.model.state = property_state
        if self.view:
            self.view.setFocus()
        super(MainWindow, self).showEvent(event)

    def hideEvent(self, event):
        self.state_last_hidden = self.saveState()
        super(MainWindow, self).hideEvent(event)

    def closeEvent(self, event):
        """Check for unsaved work before accepting the event. If the event
        is accepted we also save the state of the UI before closing."""
        if self._closing:
            self._closing = False
            event.ignore()
            return
        dirty_models = []
        for open_file_dict in self.open_files.values():
            unsaved = open_file_dict['model'].get_unsaved_changes()
            if unsaved:
                dirty_models += [open_file_dict['model']]
        if dirty_models:
            resp = UnsavedLayersDialogue.save_before_exit(dirty_models, self)
            if resp == QtWidgets.QDialog.Rejected:
                event.ignore()
                return
        event.accept()
        self.shutdown_rpc_server()
        # Window state
        state_key = user_dir.EDITOR_CACHE.WINODW_STATE
        geo_key = user_dir.EDITOR_CACHE.MAIN_WIN_GEO
        user_dir.editor_cache[state_key] = self.saveState()
        user_dir.editor_cache[geo_key] = self.saveGeometry()
        state_key = user_dir.EDITOR_CACHE.NODE_PROPERTY_STATE
        property_state = self.property_editor.model.state
        if property_state:
            user_dir.editor_cache[state_key] = str(property_state)

        nxt_log.stop_session_log(self.nxt.log_file)
        # Close our dock widgets.
        for child in self.children():
            if isinstance(child, DockWidgetBase):
                child.close()
        # Save closing session
        closing_session = []
        for file_dict in self.open_files.values():
            model = file_dict['model']
            real_path = model.top_layer.real_path
            if not real_path:
                continue
            closing_session += [str(real_path)]
        if closing_session:
            pref_key = user_dir.EDITOR_CACHE.LAST_CLOSED
            last_sessions = user_dir.editor_cache.get(pref_key, [])
            last_sessions += [closing_session]
            user_dir.editor_cache[pref_key] = last_sessions
        self._closing = True
        self.close_signal.emit()
        super(MainWindow, self).closeEvent(event)

    def validate_layers_saved(self, model=None, single_layer=None):
        model = model or self.model
        if single_layer:
            layers = [single_layer]
        else:
            layers = model.stage._sub_layers
        unsaved = model.get_unsaved_changes(layers=layers)
        if unsaved and not single_layer:
            resp = UnsavedLayersDialogue.save_before_exit([model], self)
            if resp == QtWidgets.QDialog.Rejected:
                return False
        elif unsaved and single_layer:
            info = 'Layer "{}" has unsaved changes!'.format(single_layer.alias)
            resp = UnsavedChangesMessage.save_before_close(info=info)
            save = UnsavedChangesMessage.Save
            cancel = UnsavedChangesMessage.Cancel
            if resp == cancel:
                return False
            if resp == save:
                self.save_layer(single_layer)
                return True
        return True


class ToolBar(QtWidgets.QToolBar):

    def __init__(self, parent=None):
        super(ToolBar, self).__init__(parent=parent)
        self.setFixedHeight(32)
        self.setIconSize(QtCore.QSize(19, 19))


class NodeAuthoringToolBar(ToolBar):

    def __init__(self, parent=None):
        super(NodeAuthoringToolBar, self).__init__(parent=parent)
        self.setObjectName('Node Authoring')
        self.main_window = parent
        self.node_actions = self.main_window.node_actions
        self.main = QtWidgets.QWidget()
        self.addWidget(self.main)

        self.layout = QtWidgets.QGridLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.main.setLayout(self.layout)
        # add node
        self.addAction(self.node_actions.add_node_action)
        # delete node
        self.addAction(self.node_actions.delete_node_action)
        self.addSeparator()
        # duplicate node
        self.addAction(self.node_actions.duplicate_node_action)
        # instance node
        self.addAction(self.node_actions.instance_node_action)
        # remove instance node
        self.addAction(self.node_actions.remove_instance_action)
        self.addSeparator()
        # cut node
        self.addAction(self.node_actions.cut_node_action)
        # copy node
        self.addAction(self.node_actions.copy_node_action)
        # paste node
        self.addAction(self.node_actions.paste_node_action)
        self.addSeparator()

        # localize node
        self.addAction(self.node_actions.localize_node_action)
        # revert node
        self.addAction(self.node_actions.revert_node_action)
        self.addSeparator()
        # select all
        self.addAction(self.node_actions.select_all_action)


class AlignDistributeToolBar(ToolBar):

    def __init__(self, parent=None):
        super(AlignDistributeToolBar, self).__init__(parent=parent)
        self.setObjectName('Alignment Tools')
        self.main_window = parent
        # ACTIONS
        self.addActions(self.main_window.alignment_actions.actions())


class ExecuteToolBar(ToolBar):

    def __init__(self, parent=None):
        super(ExecuteToolBar, self).__init__(parent=parent)
        self.setObjectName('Execute Tools')
        self.main_window = parent
        self.exec_actions = self.main_window.execute_actions
        self.addActions([self.exec_actions.execute_graph_action,
                         self.exec_actions.stop_exec_action,
                         self.exec_actions.execute_selected_action,
                         self.exec_actions.execute_from_action,
                         self.exec_actions.execute_hierarchy_action])
        self.addSeparator()
        self.addActions([self.exec_actions.add_start_action,
                         self.exec_actions.remove_start_action,
                         self.exec_actions.find_start_action])
        self.addSeparator()
        self.addActions([self.exec_actions.add_break_action,
                         self.exec_actions.remove_break_action,
                         self.exec_actions.clear_breaks_action])


class DisplayToolBar(ToolBar):

    def __init__(self, parent=None):
        super(DisplayToolBar, self).__init__(parent=parent)
        self.setObjectName('Display Tools')
        self.main_window = parent
        self.view_actions = self.main_window.view_actions
        self.display_actions = self.main_window.display_actions
        self.addAction(self.display_actions.raw_action)
        self.addAction(self.display_actions.resolve_action)
        self.addAction(self.display_actions.cached_action)
        self.addSeparator()
        # Connection view
        self.addAction(self.view_actions.grid_action)
        self.addAction(self.view_actions.implicit_action)
        self.addSeparator()
        self.addAction(self.view_actions.frame_all_action)
        self.addAction(self.view_actions.frame_selection_action)
        self.addSeparator()
        self.addAction(self.view_actions.hide_attrs_action)
        self.addAction(self.view_actions.disp_local_attrs_action)
        self.addAction(self.view_actions.disp_inst_attrs_action)
        self.addAction(self.view_actions.disp_all_attrs_action)


class MenuBar(QtWidgets.QMenuBar):

    """Menu bar for nxt main window"""

    def __init__(self, parent=None):
        super(MenuBar, self).__init__(parent=parent)
        self.main_window = parent
        self.app_actions = parent.app_actions  # type: actions.AppActions
        self.exec_actions = parent.execute_actions  # type: actions.ExecuteActions
        self.node_actions = parent.node_actions  # type: actions.NodeActions
        self.ce_actions = parent.code_editor_actions  # type: actions.CodeEditorActions
        self.display_actions = parent.display_actions  # type: actions.DisplayActions
        self.view_actions = parent.view_actions  # type: actions.StageViewActions
        self.layer_actions = parent.layer_actions  # type: actions.LayerActions
        # File Menu
        self.file_menu = self.addMenu('File')
        self.file_menu.setTearOffEnabled(True)
        # ACTIONS
        # Something of note:
        # Menu actions with multi key shortcuts are (in general) act like
        # application level shortcuts on OSX. Single key shortcuts however
        # do not work in the same way. There is a workaround for this if Qt
        # never fixes how menus are made and we get complaints from osx users.
        # https://thebreakfastpost.com/2014/06/03/single-key-menu-shortcuts-with-qt5-on-osx/
        # New tab
        self.file_menu.addAction(self.main_window.app_actions.new_graph_action)
        # Open file
        self.file_menu.addAction(self.main_window.app_actions.open_file_action)

        # Recent files
        self.load_recent_menu = RecentFilesMenu(action_target=self.main_window.load_file)
        self.file_menu.addMenu(self.load_recent_menu)
        self.file_menu.addAction(self.layer_actions.save_layer_action)
        self.file_menu.addAction(self.layer_actions.save_layer_as_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.layer_actions.save_all_layers_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.layer_actions.new_layer_above_action)
        self.file_menu.addAction(self.layer_actions.new_layer_below_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.layer_actions.ref_layer_above_action)
        self.file_menu.addAction(self.layer_actions.ref_layer_below_action)
        self.file_menu.addSeparator()
        self.builtins_menu = QtWidgets.QMenu('Reference Builtin Graph')
        self.builtins_menu.aboutToShow.connect(partial(populate_builtins_menu,
                                                       qmenu=self.builtins_menu,
                                                       main_window=self.main_window))
        self.file_menu.addMenu(self.builtins_menu)
        # Close app
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.main_window.app_actions.close_tab_action)
        self.file_menu.addAction(self.main_window.app_actions.close_action)

        # Edit Menu
        self.edit_menu = self.addMenu('Edit')
        self.edit_menu.setTearOffEnabled(True)

        self.edit_menu.addAction(self.main_window.app_actions.undo_action)
        self.edit_menu.addAction(self.main_window.app_actions.redo_action)
        self.edit_menu.addSeparator()
        self.edit_menu.addAction(self.node_actions.copy_node_action)
        self.edit_menu.addAction(self.node_actions.cut_node_action)
        self.edit_menu.addAction(self.node_actions.paste_node_action)
        self.edit_menu.addAction(self.node_actions.delete_node_action)
        self.edit_menu.addSeparator()
        self.edit_menu.addAction(self.node_actions.select_all_action)

        # view menu
        self.view_menu = self.addMenu('View')
        self.view_menu.setTearOffEnabled(True)
        self.view_menu.addAction(self.view_actions.frame_selection_action)
        self.view_menu.addAction(self.view_actions.frame_all_action)
        self.view_menu.addSeparator()
        self.view_menu.addAction(self.display_actions.raw_action)
        self.view_menu.addAction(self.display_actions.resolve_action)
        self.view_menu.addAction(self.display_actions.cached_action)
        self.view_menu.addSeparator()
        self.view_menu.addAction(self.view_actions.implicit_action)
        self.view_menu.addAction(self.view_actions.grid_action)
        self.view_opt_menu = self.view_menu.addMenu('Options')
        self.view_opt_menu.setTearOffEnabled(True)
        self.view_opt_menu.addAction(self.view_actions.tooltip_action)
        self.view_opt_menu.addAction(self.layer_actions.lay_manger_table_action)
        self.view_opt_menu.addAction(self.ce_actions.overlay_message_action)

        # graph menu
        self.graph_menu = self.addMenu('Graph')
        self.graph_menu.setTearOffEnabled(True)
        self.graph_menu.addAction(self.node_actions.add_node_action)

        # execute menu
        self.execute_menu = self.addMenu('Execute')
        self.execute_menu.setTearOffEnabled(True)
        self.execute_menu.addAction(self.exec_actions.execute_from_action)
        self.execute_menu.addAction(self.exec_actions.execute_selected_action)
        self.execute_menu.addAction(self.exec_actions.execute_hierarchy_action)
        self.execute_menu.addAction(self.exec_actions.execute_graph_action)
        self.execute_menu.addAction(self.exec_actions.clear_cache_action)
        self.execute_menu.addAction(self.exec_actions.wt_recomp_action)
        # Populate action data for window actions
        self.app_actions.layer_manager_action.setData(parent.layer_manager)
        self.app_actions.property_editor_action.setData(parent.property_editor)
        self.app_actions.code_editor_action.setData(parent.code_editor)
        self.app_actions.history_view_action.setData(parent.history_view)
        self.app_actions.build_view_action.setData(parent.build_view)
        self.app_actions.output_log_action.setData(parent.output_log)
        self.app_actions.hotkey_editor_action.setData(parent.hotkey_editor)
        self.app_actions.workflow_tools_action.setData(parent.workflow_tools)

        # window menu
        self.window_menu = self.addMenu('Window')
        self.window_menu.aboutToShow.connect(self.populate_window_menu)
        self.window_menu.triggered.connect(self.window_action_triggered)
        self.window_menu_actions = [
            self.app_actions.layer_manager_action,
            self.app_actions.property_editor_action,
            self.app_actions.code_editor_action,
            self.app_actions.history_view_action,
            self.app_actions.build_view_action,
            self.app_actions.output_log_action,
            self.app_actions.hotkey_editor_action,
            self.app_actions.workflow_tools_action
        ]
        self.populate_window_menu()
        # Remote Menu
        self.remote_menu = self.addMenu('Remote')
        remote_context_action = self.remote_menu.addAction('Create Remote '
                                                           'Context')
        remote_context_func = self.main_window.create_remote_context
        remote_context_action.triggered.connect(remote_context_func)
        if not is_standalone():
            remote_context_action.setEnabled(False)
        self.remote_menu.addSeparator()
        self.remote_menu.addAction(self.exec_actions.enable_cmd_port_action)
        self.remote_menu.addSeparator()
        self.remote_menu.addAction(self.exec_actions.startup_rpc_action)
        self.remote_menu.addAction(self.exec_actions.shutdown_rpc_action)
        self.options_menu = self.addMenu('Options')
        self.options_menu.addAction(self.app_actions.toggle_ding_action)
        self.options_view_sub = self.options_menu.addMenu('View')
        self.options_view_sub.setTearOffEnabled(True)
        self.options_view_sub.addActions(self.view_opt_menu.actions())
        # Help Menu
        self.help_menu = self.addMenu('Help')
        self.help_menu.setTearOffEnabled(True)
        prefs_dir_action = self.help_menu.addAction('Open Prefs Dir')
        prefs_dir_action.triggered.connect(self.open_prefs_dir)
        config_dir_action = self.help_menu.addAction('Open Plugins Dir')
        config_dir_action.triggered.connect(self.open_plugins_dir)
        self.help_menu.addSeparator()
        self.help_menu.addAction(self.main_window.app_actions.docs_action)
        github_action = self.help_menu.addAction('GitHub')
        url = 'https://github.com/nxt-dev/nxt_editor'
        github_action.triggered.connect(partial(webbrowser.open_new, url))
        self.help_menu.addSeparator()
        del_resources = self.help_menu.addAction('Clear UI Icon Cache')
        del_resources.triggered.connect(self.delete_resources_pyc)
        self.help_menu.addSeparator()
        # Secret Menu
        self.secret_menu = self.help_menu.addMenu('Developer Options')
        self.secret_menu.setTearOffEnabled(True)
        test_log_action = self.secret_menu.addAction('test logging')
        test_log_action.triggered.connect(self.__test_all_logging)
        print_action = self.secret_menu.addAction('test print')
        print_action.triggered.connect(self.__test_print)
        critical_action = self.secret_menu.addAction('test remove layer')
        critical_action.triggered.connect(self.__test_rm_layer)
        uncaught_exception = self.secret_menu.addAction('uncaught exception')
        uncaught_exception.triggered.connect(self.__force_uncaught_exception)
        compile_selection = self.secret_menu.addAction('compile selection')
        compile_selection.triggered.connect(self.__compile_node_code)
        save_cache = self.secret_menu.addAction('save cached')
        save_cache.triggered.connect(self.__save_cache_layer)
        load_cache = self.secret_menu.addAction('load cached')
        load_cache.triggered.connect(self.__load_cache_layer)
        rpc_ping = self.secret_menu.addAction('rpc ping')
        rpc_ping.triggered.connect(self.__rpc_ping)
        force_kill_rpc = self.secret_menu.addAction('force kill rpc')
        force_kill_rpc.triggered.connect(self.__force_kill_rpc)
        # Debugger function
        test_graph_action = self.secret_menu.addAction('Debugger')
        test_graph_action.triggered.connect(self.__debug)
        # Force redraw
        force_redraw_action = self.secret_menu.addAction(
            'Force Redraw')
        force_redraw_action.triggered.connect(self.__force_redraw)
        # Force rebuild stage
        force_build_stage_action = self.secret_menu.addAction('Force Update')
        force_build_stage_action.triggered.connect(self.__force_build_stage)
        self.help_menu.addSeparator()
        about_action = self.help_menu.addAction('About')
        about_action.triggered.connect(self.about_message)

    def eventFilter(self, widget, event):
        if event.type() == QtCore.QEvent.Type.ShortcutOverride:
            return True
        return False

    def populate_window_menu(self):
        self.window_menu.clear()
        for action in self.window_menu_actions:
            widget = action.data()
            action.setChecked(widget.isVisible())
            self.window_menu.addAction(action)
        self.window_menu.addSeparator()
        for file_dict in self.main_window.open_files.values():
            widget = file_dict['view']
            name = file_dict['model'].top_layer.get_alias()
            new_action = self.window_menu.addAction(name)
            new_action.setData(widget)

    def window_action_triggered(self, action=None):
        if not action:
            # Sometimes Qt sends us this signal with no action.
            return
        widget = action.data()
        tab_index = self.main_window.open_files_tab_widget.indexOf(widget)
        if tab_index != -1:
            self.main_window.open_files_tab_widget.setCurrentIndex(tab_index)
            return
        if action.isChecked():
            widget.show()
            widget.raise_()
        else:
            widget.close()

    @staticmethod
    def open_prefs_dir():
        d = user_dir.PREF_DIR
        if 'darwin' in sys.platform:
            os.system('open {}'.format(d))
        elif 'win' in sys.platform:
            os.startfile(d)
        else:
            try:
                os.system('xdg-open {}'.format(d))
            except:
                logger.exception('Failed to open user dir')

    @staticmethod
    def open_plugins_dir():
        d = USER_PLUGIN_DIR
        if 'darwin' in sys.platform:
            os.system('open {}'.format(d))
        elif 'win' in sys.platform:
            os.startfile(d)
        else:
            try:
                os.system('xdg-open {}'.format(d))
            except:
                logger.exception('Failed to open user config dir')

    def about_message(self):
        text = ('nxt {} \n'
                'graph v{}\n'
                'api v{}\n'
                'editor v{}\n'
                'Copyright (c) 2015-2020 '
                'The nxt Authors').format(self.main_window.host_app,
                                          GRAPH_VERSION.VERSION_STR,
                                          API_VERSION.VERSION_STR,
                                          EDITOR_VERSION.VERSION_STR)
        message_box = QtWidgets.QMessageBox()
        message_box.setWindowTitle('About nxt '
                                   '({})'.format(EDITOR_VERSION.VERSION_STR))
        message_box.setText(text)
        message_box.setStandardButtons(message_box.Close)
        message_box.setIcon(message_box.Icon.Information)
        message_box.exec_()

    @staticmethod
    def delete_resources_pyc():
        ui_dir = os.path.dirname(__file__)
        resources_file = os.path.join(ui_dir, 'qresources.py').replace(os.sep,
                                                                      '/')
        resources_file_c = os.path.join(ui_dir, 'qresources.pyc').replace(os.sep,
                                                                          '/')
        success = False
        if os.path.isfile(resources_file):
            try:
                os.remove(resources_file)
                success = True
            except:
                logger.exception('Failed to delete "{}" please do so '
                                 'manually.'.format(resources_file))
        if os.path.isfile(resources_file_c):
            try:
                os.remove(resources_file_c)
                success = True
            except:
                logger.exception('Failed to delete "{}" please do so '
                                 'manually.'.format(resources_file_c))
                success = False

        if success:
            logger.info('Cleared UI icon cache, please restart nxt.')
        from . import make_resources
        make_resources()

    def __test_print(self):
        """prints a simple message for output log debug"""
        print('Test print please ignore')

    def __test_all_logging(self):
        done = []
        for level_num in logging._levelNames:
            if not isinstance(level_num, int):
                level_num = logging.getLevelName(level_num)
            if level_num in done:
                continue
            done += [level_num]
            logger.log(level_num, 'Testing logger level '
                                  '{}'.format(logging.getLevelName(level_num)))

    def __test_rm_layer(self):
        nxt_object = self.parent().nxt
        stage_key = nxt_object._loaded_files.keys()[0]
        stage = nxt_object._loaded_files[stage_key]
        stage.remove_sublayer(1)
        model = self.parent().model
        model.update_comp_layer()

    def __force_build_stage(self):
        self.main_window.model.update_comp_layer(rebuild=True)

    def __force_redraw(self):
        view = self.parent().view
        view.update_view()

    def __force_uncaught_exception(self):
        print(foo)

    def __compile_node_code(self):
        """Test the compile of a node's compute and if it works in the console
        :return:
        """
        path = self.main_window.model.selection[0]
        comp_layer = self.main_window.model.comp_layer
        rt_layer = self.main_window.model.stage.setup_runtime_layer(comp_layer)
        rt_node = rt_layer.lookup(path)
        from runtime import GraphError, Console
        import nxt.stage as _stage
        g = {'__stage__': self.main_window.model.stage,
             'STAGE': rt_layer,
             'w': _stage.w,
             }
        func = self.main_window.model.stage.get_node_code(rt_node,
                                                                  rt_layer)
        console = Console(g, node_path=path)
        g['func'] = func
        g['self'] = rt_node
        try:
            console.runcode(func)
        except GraphError:
            pass

    def __debug(self):
        model = self.main_window.model
        stage = model.stage
        target_layer = model.target_layer
        comp_layer = model.comp_layer
        nxt_object = self.parent().nxt
        stages = []
        layers = []
        for k in nxt_object._loaded_files.keys():
            stages.append(nxt_object._loaded_files[k])
        for stage in stages:
            stage.debug = True
            for l in stage._sub_layers:
                layers.append(l)
        return

    def __load_cache_layer(self):
        filt = 'nxt files (*.nxt)'
        file_path = QtWidgets.QFileDialog.getOpenFileName(filter=filt)[0]
        if not file_path:
            return
        layer_data = nxt_io.load_file_data(file_path)
        model = self.main_window.model
        cache_layer = nxt_layer.CacheLayer.load_from_layer_data(layer_data)
        if not model.current_rt_layer:
            model.current_rt_layer = nxt_layer.CompLayer()
        model.current_rt_layer.cache_layer = cache_layer

    def __save_cache_layer(self):
        curr_rt = self.main_window.model.current_rt_layer
        if not curr_rt:
            logger.info("No cache data to save")
            return
        filt = 'nxt files (*.nxt)'
        file_path = QtWidgets.QFileDialog.getSaveFileName(filter=filt)[0]
        if not file_path:
            return
        curr_rt.cache_layer.save(file_path)

    def __rpc_ping(self):
        proxy = NxtClient()
        proxy.is_alive()

    def __force_kill_rpc(self):
        proxy = NxtClient()
        proxy.kill()


class OpenFilesTabWidget(QtWidgets.QTabWidget):
    def __init__(self, parent=None):
        super(OpenFilesTabWidget, self).__init__(parent=parent)
        self.main_window = parent
        self.setTabsClosable(True)
        self.setMovable(True)
        self.tabCloseRequested.connect(self.close_tab)

    def close_tab(self, index):
        model = self.widget(index).model
        safe_to_close = self.main_window.validate_layers_saved(model=model)
        if not safe_to_close:
            self.main_window.set_waiting_cursor(False)
            return
        self.main_window.set_waiting_cursor(True)
        self.widget(index).clear()
        uid = self.widget(index).model.uid
        self.parent().nxt.unload_file(uid)
        tab_data = self.parent().open_files.pop(uid)
        model = tab_data['model']
        view = tab_data['view']
        view.deleteLater()
        model.deleteLater()
        self.removeTab(index)
        self.main_window.tab_changed.emit()
        real_path = model.top_layer.real_path
        if not real_path:
            self.main_window.set_waiting_cursor(False)
            return
        pref_key = user_dir.EDITOR_CACHE.LAST_CLOSED
        last_sessions = user_dir.editor_cache.get(pref_key, [])
        last_sessions += [[str(real_path)]]
        user_dir.editor_cache[pref_key] = last_sessions
        self.main_window.set_waiting_cursor(False)


class RecentFilesMenu(QtWidgets.QMenu):
    def __init__(self, action_target=None):
        super(RecentFilesMenu, self).__init__('Open Recent')
        self.aboutToShow.connect(self.refresh_list)
        self.action_target = action_target
        self.triggered.connect(self.recent_selected)

    def refresh_list(self):
        self.clear()
        recents = user_dir.editor_cache.get(user_dir.USER_PREF.RECENT_FILES, [])
        if not recents:
            action = self.addAction('No recents found')
            action.setEnabled(False)
        for file_path in recents:
            self.addAction(str(file_path))

    def recent_selected(self, action):
        self.action_target(action.text())


class StatusBarHandler(logging.Handler):
    def __init__(self, output_log=None):
        logging.Handler.__init__(self, level=logging.DEBUG)
        self.output_template = "{level} | {module}: \"{message}\""
        self.output_log = output_log
        self.signaller = LoggingSignaler()
        self.signaller.signal.connect(self.update)

    def emit(self, record):
        return
        self.signaller.signal.emit(record)

    def update(self, record):
        out_message = self.output_template.format(level=record.levelname,
                                                  module=record.module,
                                                  message=record.getMessage())
        if self.output_log:
            self.output_log.showMessage(out_message)


class StartRPCThread(QtCore.QThread):
    def __init__(self, main_window):
        super(StartRPCThread, self).__init__()
        self.main_window = main_window

    def run(self):
        if self.main_window.model:
            self.main_window.model.processing.emit(True)
        # We setup the log file here so we're tailing it _before_ we start
        # the server up.
        rpc_log = nxt_io.generate_temp_file(suffix='.nxtlog')
        # Setup rpc server log tail
        self.main_window.safe_stop_rpc_tailing()
        self.main_window.rpc_log_tail = FileTailingThread(rpc_log)
        self.main_window.handle_rpc_tailing_signals(True)
        self.main_window.rpc_log_tail.start()
        sh = QtLogStreamHandler.get_handler(self.main_window.new_log_signal)
        try:
            self.main_window.nxt._start_rpc_server(custom_stdout=True,
                                                   rpc_log_filepath=rpc_log,
                                                   socket_log=True,
                                                   stream_handler=sh)
        except OSError:
            logger.warning('Failed to start/connect to rpc server. Please try '
                           'starting the rpc server via the UI')
            if self.main_window.model:
                self.main_window.model.processing.emit(False)
            return
        remote_rpc_log_file_path = None
        if not self.main_window.nxt.rpc_server:
            proxy = NxtClient()
            try:
                remote_rpc_log_file_path = proxy.get_log_location()
            except:
                logger.warning('Failed to tail remote rpc server log!')
        if remote_rpc_log_file_path:
            self.main_window.rpc_log_tail.watch_path = remote_rpc_log_file_path
            with open(remote_rpc_log_file_path, 'r') as fp:
                text = fp.read()
                end_pos = len(text)
            self.main_window.rpc_log_tail.last_read_pos = end_pos
        if self.main_window.model:
            self.main_window.model.processing.emit(False)


def populate_builtins_menu(qmenu, main_window, layer=None):
    """Populates a QMenu object with actions for referencing each builtin layer.
    :param qmenu: QMenu object to be filled with actions
    :param main_window: nxt MainWindow
    :param layer: Optional layer to reference builtin layer under, if none is
    supplied the target layer is used.
    :return: QMenu
    """
    qmenu.clear()
    stage_model = main_window.model
    if not stage_model:
        enable = False
        idx = -1
    else:
        enable = True
        layer = layer or stage_model.target_layer
        idx = layer.layer_idx() + 1

    for file_name in os.listdir(nxt_io.BUILTIN_GRAPHS_DIR):
        if not file_name.endswith('.nxt'):
            continue
        new_action = qmenu.addAction(file_name)
        path = '${var}/{file_name}'.format(var=nxt_io.BUILTIN_GRAPHS_ENV_VAR,
                                           file_name=file_name)
        if enable:
            new_action.triggered.connect(partial(stage_model.reference_layer,
                                                 path, idx))
        new_action.setEnabled(enable)
    return qmenu


def nxt_execpthook(typ, value, tb):
    if 'nxt' not in tb.tb_frame.f_code.co_filename:
        return og_excepthook(typ, value, tb)
    logger.error('NXT encountered an Uncaught exception!')
    traceback.print_tb(tb)
    message = ('Please copy the error details and send to an nxt '
               'developer.\n'
               'Save your work immediately.')
    # TODO: Get the last few lines from the session log and put them here
    details = ''.join(traceback.format_exception(typ, value, tb))
    logger.exception(details)
    style_file = QtCore.QFile(':styles/styles/dark/dark.qss')
    style_file.open(QtCore.QFile.ReadOnly)
    stylesheet = str(style_file.readAll())
    dialog = NxtWarningDialog('Uncaught Exception!', message, details)
    dialog.setStyleSheet(stylesheet)
    dialog.exec_()


def catch_exceptions():
    debugger_attached = 'pydevd' in sys.modules
    return not debugger_attached


if sys.excepthook is not nxt_execpthook:
    og_excepthook = sys.excepthook

if catch_exceptions():
    sys.excepthook = nxt_execpthook
