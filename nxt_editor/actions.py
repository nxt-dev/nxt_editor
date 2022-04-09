# Built-in
import logging
import os
import webbrowser
from functools import partial

# External
from Qt import QtCore, QtGui, QtWidgets

# Internal
from . import DIRECTIONS
from nxt_editor.constants import NXT_WEBSITE
from nxt_editor import user_dir
from nxt import nxt_layer, DATA_STATE, nxt_path
from nxt_editor import colors, finder, file_search

logger = logging.getLogger('nxt')


class NxtAction(QtWidgets.QAction):
    def __init__(self, text, parent=None):
        """Creates action that can have user defined shortcuts
        :param parent: Main window instance that will own the action.
        :param text: Name for the action that will be saved as the key
        in the hotkeys.json
        """
        super(NxtAction, self).__init__(text, parent)
        self.cached_user_shortcuts = self.cache_shortcuts()
        self.setShortcutContext(QtCore.Qt.WidgetShortcut)
        self.default_shortcut = None
        if parent:
            parent.addAction(self)
        if text in self.cached_user_shortcuts.keys():
            self.setShortcut(self.cached_user_shortcuts[text],
                             user_override=True)

    def cache_shortcuts(self):
        """Populates `self.cached_user_shortcuts` with a copy of the on-disk
        preference dictionary of shortcuts. Returns said copy.
        """
        self.cached_user_shortcuts = user_dir.hotkeys.copy()
        return self.cached_user_shortcuts

    def setShortcut(self, shortcut, user_override=False):
        self.cache_shortcuts()
        text = self.text()
        if not user_override:
            self.default_shortcut = shortcut
        if not user_override and text in self.cached_user_shortcuts.keys():
            shortcut = self.cached_user_shortcuts.get(text)
        elif user_override:
            self.save_shortcut(name=text, shortcut=shortcut)
        super(NxtAction, self).setShortcut(shortcut)

    def text(self):
        """Makes sure we get a string back at some point unicode messed us up"""
        text = super(NxtAction, self).text()
        return str(text)

    def setText(self, new_text):
        old_text = self.text()
        if not new_text:
            raise Exception('Sorry Nxt Actions must have valid text!')
        if old_text and old_text != new_text:
            # This code is only reached if somehow you change the name of
            # the action in the code, this does not retroactively update the
            # user's pref file!
            self.update_shortcut(old_text, new_text, self.shortcut())
        super(NxtAction, self).setText(new_text)

    def save_shortcut(self, name, shortcut):
        if isinstance(shortcut, QtGui.QKeySequence):
            shortcut = str(shortcut.toString())
        default_shortcut = self.default_shortcut
        if isinstance(default_shortcut, QtGui.QKeySequence):
            default_shortcut = default_shortcut.toString()
        if shortcut == default_shortcut:
            self.remove_shortcut(name)
        else:
            self.cached_user_shortcuts[name] = shortcut or None
        user_dir.hotkeys[name] = shortcut or None

    def update_shortcut(self, old_name, new_name, shortcut):
        self.cache_shortcuts()
        if isinstance(shortcut, QtGui.QKeySequence):
            shortcut = str(shortcut.toString())
        self.remove_shortcut(old_name)
        self.save_shortcut(new_name, shortcut)

    def remove_shortcut(self, name):
        if name in self.cached_user_shortcuts.keys():
            self.cached_user_shortcuts.pop(name)


class NxtActionContainer(QtWidgets.QWidget):
    def __init__(self, main_window):
        """QObject used to hold pointers to actions and organize them
        logically. In general actions in a container object should be
        ones that logically would NOT have conflicting hotkeys. For example
        you wouldn't want actions controlling the mute state of a  layer in
        the same container as actions controlling the disabled state of a node.

        Often action's triggered signal will need to be connected somewhere
        outside of the container object. Carefully consider when and where
        action is needed/used to determine if it should be connected to a
        when it is created in the container init.
        :param main_window: nxt MainWindow object
        """
        super(NxtActionContainer, self).__init__(parent=main_window)
        self.main_window = main_window
        self.main_window.tab_changed.connect(self.handle_model_change)
        self.action_display_order = []
        self.available_without_model = []
        self.prev_enabled_state = {}

    def get_action_data(self):
        """Parses the container for actions and assembles a sorted multi
        dimensional list. Each sub-list contains the following: Name, What's
        This, Tooltip, Shortcut (string), NxtAction. This data is intended to
        be used by the hotkey dockwidet.
        :return: list
        """
        action_list = []
        for action in self.actions():
            name = action.text()
            what = action.whatsThis()
            tool_tip = action.toolTip()
            shortcut = action.shortcut().toString()
            action_list += [[name, what, tool_tip, shortcut, action]]
        info = (len(action_list), self.objectName())
        logger.debug('{} action(s) found in {}'.format(*info))
        return action_list

    def actions(self):
        """Attempts to return the display order of the actions if it is
        different than the declaration order.
        :return: list
        """
        ordered_actions = self.action_display_order[:]
        for action in super(NxtActionContainer, self).actions():
            if action not in ordered_actions:
                ordered_actions += [action]
        return ordered_actions

    def handle_model_change(self):
        if not self.main_window.model:
            for action in self.actions():
                if action in self.available_without_model:
                    continue
                self.prev_enabled_state[action] = action.isEnabled()
                action.setEnabled(False)
        else:
            for action in self.actions():
                if action in self.available_without_model:
                    continue
                prev_state = self.prev_enabled_state.get(action, None)
                if prev_state is not None:
                    action.setEnabled(prev_state)
            self.prev_enabled_state = {}


class BoolUserPrefAction(NxtAction):
    """NxtAction that saves state between sessions via preference key."""
    def __init__(self, text, pref_key, default=False, parent=None):
        """NxtAction that saves state between sessions via preference key

        Note that default checked state is set during initialization, before
        signals have been hooked up. Meaning any later-connected function is not
        automatically called to "kick start" the application state. Either
        build that into the start of the UI, or call your action once manually
        to kick start.

        :param text: Action description.
        :type text: str
        :param pref_key: Preference key to save at
        :type pref_key: str
        :param default: Deafult value, loads default state from user pref, only
        falling back to this default when no save exists, defaults to False
        :type default: bool, optional
        :param parent: Action parent, defaults to None
        :type parent: QObject, optional
        """
        super(BoolUserPrefAction, self).__init__(text, parent)
        self.setCheckable(True)
        self.pref_key = pref_key
        self.setChecked(user_dir.user_prefs.get(self.pref_key, default))
        self.triggered.connect(self.on_triggered)

    def on_triggered(self):
        user_dir.user_prefs[self.pref_key] = bool(self.isChecked())


class AppActions(NxtActionContainer):
    def __init__(self, main_window):
        super(AppActions, self).__init__(main_window)
        self.setObjectName('Application Actions')
        # GENERAL ACTIONS
        context = QtCore.Qt.WindowShortcut
        # User docs

        def open_user_docs():
            webbrowser.open_new(NXT_WEBSITE)
        self.docs_action = NxtAction(text='User Docs', parent=self)
        self.docs_action.setShortcut('F1')
        self.docs_action.triggered.connect(open_user_docs)
        self.docs_action.setWhatsThis('Open user docs.')
        self.docs_action.setShortcutContext(context)
        # Undo
        self.undo_action = NxtAction(text='Undo', parent=self)
        self.undo_action.setShortcut('Ctrl+Z')
        self.undo_action.triggered.connect(self.main_window.undo)
        self.undo_action.setWhatsThis('Undo last command.')
        self.undo_action.setShortcutContext(context)

        # Redo
        self.redo_action = NxtAction(text='Redo', parent=self)
        self.redo_action.setShortcut('Ctrl+Shift+Z')
        self.redo_action.triggered.connect(self.main_window.redo)
        self.redo_action.setWhatsThis('Redo last command.')
        self.redo_action.setShortcutContext(context)

        # Close
        self.close_action = NxtAction(text='Exit', parent=self)
        self.close_action.setShortcut('Alt+F4')
        self.close_action.triggered.connect(self.main_window.close)
        self.close_action.setWhatsThis('Close nxt.')
        self.available_without_model.append(self.close_action)
        self.close_action.setShortcutContext(context)

        # New graph
        self.new_graph_action = NxtAction(text='New Graph',
                                          parent=self)
        self.new_graph_action.triggered.connect(self.main_window.new_tab)
        self.new_graph_action.setShortcut('Ctrl+N')
        self.new_graph_action.setShortcutContext(context)
        self.new_graph_action.setWhatsThis('New empty graph.')
        self.available_without_model.append(self.new_graph_action)

        # Open graph
        self.open_file_action = NxtAction(text='Open Graph',
                                          parent=self)
        self.open_file_action.triggered.connect(self.main_window.load_file)
        self.open_file_action.setShortcut('Ctrl+O')
        self.open_file_action.setShortcutContext(context)
        self.open_file_action.setWhatsThis('Open nxt file.')
        self.available_without_model.append(self.open_file_action)

        # Open Previous
        def open_previous():
            pref_key = user_dir.EDITOR_CACHE.LAST_CLOSED
            last_sessions = user_dir.editor_cache[pref_key]
            prev_session = []
            try:
                prev_session = last_sessions.pop(-1)
            except IndexError:
                logger.info("No more sessions to re-open")
            for path in prev_session:
                self.main_window.load_file(filepath=path)
            user_dir.editor_cache[pref_key] = last_sessions
        self.open_previous_action = NxtAction(text='Open Last Closed',
                                              parent=self)
        self.open_previous_action.setShortcut('Ctrl+Shift+T')
        self.open_previous_action.setShortcutContext(context)
        self.open_previous_action.setWhatsThis('Open previously closed file(s)')
        self.open_previous_action.triggered.connect(open_previous)
        self.available_without_model.append(self.open_previous_action)

        # Close Tab
        def close_tab():
            current_idx = self.main_window.open_files_tab_widget.currentIndex()
            self.main_window.open_files_tab_widget.close_tab(current_idx)

        self.close_tab_action = NxtAction(text='Close Tab',
                                          parent=self)
        self.close_tab_action.setShortcut('Ctrl+W')
        self.close_tab_action.setShortcutContext(context)
        self.close_tab_action.setWhatsThis('Close active tab')
        self.close_tab_action.triggered.connect(close_tab)

        # Open Find and Replace
        def open_find_rep():
            find_rep_widget = self.main_window.find_rep
            if not find_rep_widget.isVisible():
                find_rep_widget.show()
            find_rep_widget.raise_()

        self.find_rep_action = NxtAction(text='Find and Replace', parent=self)
        self.find_rep_action.setShortcut('Ctrl+F')
        self.find_rep_action.setShortcutContext(context)
        self.find_rep_action.setWhatsThis('Open find and replace dialog')
        self.find_rep_action.triggered.connect(open_find_rep)

        # Dock Widget Actions
        # Layer Manager
        self.layer_manager_action = NxtAction(text='Layer Manager',
                                              parent=self)
        self.layer_manager_action.setCheckable(True)
        self.layer_manager_action.setWhatsThis('Toggle the layer manager '
                                               'widget.')
        self.layer_manager_action.setShortcutContext(context)
        self.available_without_model.append(self.layer_manager_action)

        # Property editor
        self.property_editor_action = NxtAction(text='Property Editor',
                                                parent=self)
        self.property_editor_action.setCheckable(True)
        self.property_editor_action.setShortcutContext(context)
        self.property_editor_action.setWhatsThis('Toggle the property editor '
                                               'widget.')
        self.available_without_model.append(self.property_editor_action)

        # Code editor
        self.code_editor_action = NxtAction(text='Code Editor',
                                            parent=self)
        self.code_editor_action.setCheckable(True)
        self.code_editor_action.setShortcutContext(context)
        self.code_editor_action.setWhatsThis('Toggle the code editor widget.')
        self.available_without_model.append(self.code_editor_action)

        # History view
        self.history_view_action = NxtAction(text='History View',
                                             parent=self)
        self.history_view_action.setCheckable(True)
        self.history_view_action.setShortcutContext(context)
        self.history_view_action.setWhatsThis('Toggle the history view widget.')
        self.available_without_model.append(self.history_view_action)

        # Output log
        self.output_log_action = NxtAction(text='Output Log',
                                           parent=self)
        self.output_log_action.setCheckable(True)
        self.output_log_action.setShortcutContext(context)
        self.output_log_action.setWhatsThis('Toggle the output log widget.')
        self.available_without_model.append(self.output_log_action)

        # Hotkey editor
        self.hotkey_editor_action = NxtAction(text='Hotkey Editor',
                                              parent=self)
        self.hotkey_editor_action.setCheckable(True)
        self.hotkey_editor_action.setShortcutContext(context)
        self.hotkey_editor_action.setWhatsThis('Toggle the hotkey editor '
                                               'widget.')
        self.available_without_model.append(self.hotkey_editor_action)

        # Build View
        self.build_view_action = NxtAction(text='Build View',
                                           parent=self)
        self.build_view_action.setCheckable(True)
        self.build_view_action.setShortcutContext(context)
        self.build_view_action.setWhatsThis('Toggle the build view '
                                            'widget.')
        self.available_without_model.append(self.build_view_action)

        # Workflow tools
        self.workflow_tools_action = NxtAction(text='Workflow Tools',
                                               parent=self)
        self.workflow_tools_action.setCheckable(True)
        self.workflow_tools_action.setShortcutContext(context)
        self.workflow_tools_action.setWhatsThis('Workflow tools dock widget.')
        self.available_without_model.append(self.workflow_tools_action)

        def find_node():
            if not self.main_window.model:
                return
            finder.FinderWidget(self.main_window, self.main_window.model).show()

        self.find_node_action = NxtAction(text='Find Node',
                                          parent=self)
        self.find_node_action.setWhatsThis('Search for, select, and focus '
                                           'nodes in the view')
        self.find_node_action.setShortcut('/')
        self.find_node_action.triggered.connect(find_node)
        self.find_node_action.setShortcutContext(context)

        def find_and_open():
            parent = self.main_window
            width = parent.width()*.75
            window_path = self.main_window.get_current_tab_file_path()
            path = None
            if window_path:
                path = os.path.dirname(window_path)
            if not path:
                path = os.getcwd()
            filepath = file_search.Searcher.get_open_file_path(parent, width,
                                                               default=path)
            filepath = nxt_path.full_file_expand(filepath)
            if os.path.isfile(filepath):
                self.main_window.load_file(filepath)

        self.find_and_open_action = NxtAction(text='Find and Open Graph',
                                              parent=self)
        self.find_and_open_action.setShortcut('Ctrl+P')
        self.find_and_open_action.triggered.connect(find_and_open)
        self.find_and_open_action.setShortcutContext(context)
        self.available_without_model.append(self.find_and_open_action)

        def clear_logs():
            rich = self.main_window.output_log.rich_output_textedit
            raw = self.main_window.output_log.raw_output_textedit
            rich.clear()
            raw.clear()

        self.clear_logs_action = NxtAction(text='Clear All Logs',
                                           parent=self)
        self.clear_logs_action.setWhatsThis('Clear all the text from all of the output logs (raw and rich).')
        self.clear_logs_action.triggered.connect(clear_logs)
        self.clear_logs_action.setShortcutContext(context)
        self.available_without_model.append(self.clear_logs_action)

        # Toggle error ding sound
        def toggle_ding():
            pref_key = user_dir.USER_PREF.DING
            ding_state = self.toggle_ding_action.isChecked()
            user_dir.user_prefs[pref_key] = ding_state

        self.toggle_ding_action = NxtAction('Error sound', parent=self)
        self.toggle_ding_action.setWhatsThis('When enabled a "ding" sound will be played when NXT is given bad input '
                                             'or encounters and error')
        self.toggle_ding_action.setCheckable(True)
        _ding_state = user_dir.user_prefs.get(user_dir.USER_PREF.DING, True)
        self.toggle_ding_action.setChecked(_ding_state)
        self.toggle_ding_action.triggered.connect(toggle_ding)
        self.toggle_ding_action.setShortcutContext(context)
        self.available_without_model.append(self.toggle_ding_action)

        self.action_display_order = [self.find_node_action,
                                     self.new_graph_action,
                                     self.open_file_action, self.undo_action,
                                     self.redo_action,
                                     self.layer_manager_action,
                                     self.property_editor_action,
                                     self.code_editor_action,
                                     self.history_view_action,
                                     self.build_view_action,
                                     self.output_log_action,
                                     self.hotkey_editor_action,
                                     self.workflow_tools_action,
                                     self.toggle_ding_action,
                                     self.clear_logs_action,
                                     self.close_action]


class LayerActions(NxtActionContainer):
    def __init__(self, main_window):
        super(LayerActions, self).__init__(main_window)
        self.setObjectName('Layers')
        app_context = QtCore.Qt.WindowShortcut
        widget_context = QtCore.Qt.WidgetWithChildrenShortcut
        # Save
        self.save_layer_action = NxtAction(text='Save Layer',
                                           parent=self)
        self.save_layer_action.setAutoRepeat(False)
        self.save_layer_action.setData(None)
        self.save_layer_action.setShortcut('Ctrl+S')
        self.save_layer_action.setShortcutContext(app_context)
        self.save_layer_action.setToolTip('Save Layer')
        self.save_layer_action.setWhatsThis('Saves the current layer to disc')

        def save_layer():
            layer = self.save_layer_action.data()
            clear_action_data(self.actions())
            self.main_window.save_layer(layer)
        self.save_layer_action.triggered.connect(save_layer)
        # Save as
        self.save_layer_as_action = NxtAction(text='Save Layer As',
                                              parent=self)
        self.save_layer_as_action.setAutoRepeat(False)
        self.save_layer_as_action.setData(None)
        self.save_layer_as_action.setShortcut('Ctrl+Shift+S')
        self.save_layer_as_action.setShortcutContext(app_context)

        def save_layer_as():
            layer = self.save_layer_as_action.data()
            clear_action_data(self.actions())
            self.main_window.save_layer_as(layer)
        self.save_layer_as_action.triggered.connect(save_layer_as)
        # Save all layers
        self.save_all_layers_action = NxtAction(text='Save All Layers',
                                                parent=self)
        self.save_all_layers_action.setShortcutContext(app_context)
        save_all = self.main_window.save_all_layers
        self.save_all_layers_action.triggered.connect(save_all)
        # Open source
        self.open_source_action = NxtAction(text='Open Source',
                                            parent=self)
        self.open_source_action.setWhatsThis('Open target layer in new tab.')
        self.open_source_action.setAutoRepeat(False)
        self.open_source_action.setData(None)
        self.open_source_action.setShortcut('Ctrl+Shift+O')
        self.open_source_action.setShortcutContext(app_context)

        def open_source():
            layer = self.open_source_action.data()
            clear_action_data(self.actions())
            self.main_window.open_source(layer)
        self.open_source_action.triggered.connect(open_source)
        # Change color
        self.change_color_action = NxtAction(text='Change Color',
                                             parent=self)
        self.change_color_action.setAutoRepeat(False)
        self.change_color_action.setData(None)

        def change_color():
            layer = self.change_color_action.data()
            self.change_color_action.setData(None)
            if not layer:
                layer = self.main_window.model.target_layer
            if not layer:
                return
            cd = QtWidgets.QColorDialog()
            cd.setOption(QtWidgets.QColorDialog.DontUseNativeDialog)
            for i, c in enumerate(colors.LAYER_COLORS):
                cd.setCustomColor(i, c)
            cd.setCurrentColor(QtGui.QColor(layer.color))
            cd.exec_()
            color = cd.currentColor()
            if color.isValid():
                color_name = color.name()
                model = self.main_window.model
                model.set_layer_color(layer_path=layer.real_path,
                                      color=color_name)
        self.change_color_action.triggered.connect(change_color)
        # Change Alias
        self.change_alias_action = NxtAction(text='Change Alias',
                                             parent=self)
        self.change_alias_action.setAutoRepeat(False)
        self.change_alias_action.setData(None)
        # Remove layer
        self.remove_layer_action = NxtAction(text='Remove Layer',
                                             parent=self)
        self.remove_layer_action.setAutoRepeat(False)
        self.remove_layer_action.setData(None)

        def remove_layer():
            layer = self.remove_layer_action.data()
            clear_action_data(self.actions())
            if not layer:
                layer = self.main_window.model.display_layer
            if not layer:
                return
            safe = self.main_window.validate_layers_saved(single_layer=layer)
            if not safe:
                return
            self.main_window.model.remove_sublayer(layer)
        self.remove_layer_action.triggered.connect(remove_layer)
        # Mute layer
        self.mute_layer_action = NxtAction(text='Toggle Layer Mute',
                                           parent=self)
        self.mute_layer_action.setAutoRepeat(False)
        self.mute_layer_action.setData(None)
        self.mute_layer_action.setShortcut('M')
        self.mute_layer_action.setShortcutContext(widget_context)

        def mute_layer():
            layer = self.mute_layer_action.data()
            clear_action_data(self.actions())
            if not layer:
                layer = self.main_window.model.target_layer
            if not layer:
                return
            self.main_window.model.mute_toggle_layer(layer)
        self.mute_layer_action.triggered.connect(mute_layer)
        # Solo layer
        self.solo_layer_action = NxtAction(text='Toggle Layer Solo',
                                           parent=self)
        self.solo_layer_action.setAutoRepeat(False)
        self.solo_layer_action.setData(None)
        self.solo_layer_action.setShortcut('S')
        self.solo_layer_action.setShortcutContext(widget_context)

        def solo_layer():
            layer = self.solo_layer_action.data()
            clear_action_data(self.actions())
            if not layer:
                layer = self.main_window.model.target_layer
            if not layer:
                return
            self.main_window.model.solo_toggle_layer(layer)
        self.solo_layer_action.triggered.connect(solo_layer)
        # Create Above
        self.new_layer_above_action = NxtAction(text='Create Layer Above',
                                                parent=self)
        self.new_layer_above_action.setData(None)
        self.new_layer_above_action.setShortcutContext(widget_context)

        def new_above():
            layer = self.new_layer_above_action.data()
            clear_action_data(self.actions())
            if not layer:
                layer = self.main_window.model.target_layer
            if not layer:
                return
            self.main_window.model.new_layer(layer, nxt_layer.AUTHORING.CREATE,
                                             nxt_layer.AUTHORING.ABOVE)
        self.new_layer_above_action.triggered.connect(new_above)
        # Create Below
        self.new_layer_below_action = NxtAction(text='Create Layer Below',
                                                parent=self)
        self.new_layer_below_action.setData(None)
        self.new_layer_below_action.setShortcutContext(widget_context)

        def new_below():
            layer = self.new_layer_below_action.data()
            clear_action_data(self.actions())
            if not layer:
                layer = self.main_window.model.target_layer
            if not layer:
                return
            self.main_window.model.new_layer(layer, nxt_layer.AUTHORING.CREATE,
                                             nxt_layer.AUTHORING.BELOW)
        self.new_layer_below_action.triggered.connect(new_below)
        # Ref Above
        self.ref_layer_above_action = NxtAction(text='Reference Layer Above',
                                                parent=self)

        self.ref_layer_above_action.setData(None)
        self.ref_layer_above_action.setShortcutContext(widget_context)

        def ref_above():
            layer = self.ref_layer_above_action.data()
            clear_action_data(self.actions())
            if not layer:
                layer = self.main_window.model.target_layer
            if not layer:
                return
            reference = nxt_layer.AUTHORING.REFERENCE
            self.main_window.model.new_layer(layer, reference,
                                             nxt_layer.AUTHORING.ABOVE)
        self.ref_layer_above_action.triggered.connect(ref_above)
        # Ref Below
        self.ref_layer_below_action = NxtAction(text='Reference Layer Below',
                                                parent=self)
        self.ref_layer_below_action.setData(None)
        self.ref_layer_below_action.setShortcutContext(widget_context)

        def ref_below():
            layer = self.ref_layer_below_action.data()
            clear_action_data(self.actions())
            if not layer:
                layer = self.main_window.model.target_layer
            if not layer:
                return
            reference = nxt_layer.AUTHORING.REFERENCE
            self.main_window.model.new_layer(layer, reference,
                                             nxt_layer.AUTHORING.BELOW)
        self.ref_layer_below_action.triggered.connect(ref_below)
        # Layer Manager Table View
        pref_key = user_dir.USER_PREF.LAYER_TABLE
        text = 'Layer Manager as Table'
        self.lay_manger_table_action = BoolUserPrefAction(text, pref_key,
                                                          parent=self)
        self.lay_manger_table_action.setShortcut('V')
        self.lay_manger_table_action.setShortcutContext(widget_context)

        self.action_display_order = [self.save_layer_action,
                                     self.save_layer_as_action,
                                     self.save_all_layers_action,
                                     self.open_source_action,
                                     self.mute_layer_action,
                                     self.solo_layer_action,
                                     self.change_color_action,
                                     self.change_alias_action,
                                     self.new_layer_above_action,
                                     self.new_layer_below_action,
                                     self.ref_layer_above_action,
                                     self.ref_layer_below_action,
                                     self.remove_layer_action]


class NodeActions(NxtActionContainer):
    def __init__(self, main_window):
        super(NodeActions, self).__init__(main_window)
        self.setObjectName('Nodes')
        # add node
        self.add_node_action = NxtAction(text='Add Node',
                                         parent=self)
        self.add_node_action.setShortcut('N')
        self.add_node_action.setAutoRepeat(False)
        self.add_node_action.setToolTip('Add Node')
        self.add_node_action.setWhatsThis('Add a new node to the current '
                                          'graph')
        add_icon = QtGui.QIcon()
        add_pixmap_on = QtGui.QPixmap(':icons/icons/add_node.png')
        add_pixmap_hov = QtGui.QPixmap(':icons/icons/add_node_hover.png')
        add_icon.addPixmap(add_pixmap_hov, QtGui.QIcon.Active, QtGui.QIcon.On)
        add_icon.addPixmap(add_pixmap_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        self.add_node_action.setIcon(add_icon)

        def add_node():
            self.main_window.view.add_node()
        self.add_node_action.triggered.connect(add_node)

        # delete nodes
        def del_nodes(recursive=False):
            self.main_window.model.delete_nodes(recursive=recursive)
        self.delete_node_action = NxtAction(text='Delete Node', parent=self)
        self.delete_node_action.setShortcut('Del')
        self.delete_node_action.setWhatsThis('Delete the selected node(s).')
        self.delete_node_action.triggered.connect(partial(del_nodes, False))
        del_icon = QtGui.QIcon()
        del_pixmap_on = QtGui.QPixmap(':icons/icons/delete_node.png')
        del_pixmap_hov = QtGui.QPixmap(':icons/icons/delete_node_hover.png')
        del_icon.addPixmap(del_pixmap_hov, QtGui.QIcon.Active, QtGui.QIcon.On)
        del_icon.addPixmap(del_pixmap_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        self.delete_node_action.setIcon(del_icon)
        # Recursive delete node
        self.recursive_delete_node_action = NxtAction(text='Recursive Delete '
                                                           'Node', parent=self)
        self.recursive_delete_node_action.setWhatsThis('Delete selected node '
                                                       'and all of its '
                                                       'descendants '
                                                       'recursively.')
        self.recursive_delete_node_action.setShortcut('Shift+Del')
        self.recursive_delete_node_action.triggered.connect(partial(del_nodes,
                                                                    True))

        # duplicate node
        self.duplicate_node_action = NxtAction(text='Duplicate Node',
                                               parent=self)
        self.duplicate_node_action.setShortcut('Ctrl+D')
        self.duplicate_node_action.setAutoRepeat(False)

        def dupe_nodes():
            self.main_window.model.duplicate_nodes()
        self.duplicate_node_action.triggered.connect(dupe_nodes)
        dupe_icon = QtGui.QIcon()
        dupe_pixmap_on = QtGui.QPixmap(':icons/icons/duplicate_node.png')
        dupe_pixmap_hov = QtGui.QPixmap(':icons/icons/duplicate_node_hover.png')
        dupe_icon.addPixmap(dupe_pixmap_hov, QtGui.QIcon.Active, QtGui.QIcon.On)
        dupe_icon.addPixmap(dupe_pixmap_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        self.duplicate_node_action.setIcon(dupe_icon)

        # instance node
        self.instance_node_action = NxtAction(text='Instance Node',
                                              parent=self)
        self.instance_node_action.setShortcut('Ctrl+I')
        self.instance_node_action.setAutoRepeat(False)

        def inst_nodes():
            self.main_window.model.instance_nodes()
        self.instance_node_action.triggered.connect(inst_nodes)
        inst_icon = QtGui.QIcon()
        inst_pixmap_on = QtGui.QPixmap(':icons/icons/instance_node.png')
        inst_pixmap_hov = QtGui.QPixmap(':icons/icons/instance_node_hover.png')
        inst_icon.addPixmap(inst_pixmap_hov, QtGui.QIcon.Active,
                            QtGui.QIcon.On)
        inst_icon.addPixmap(inst_pixmap_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        self.instance_node_action.setIcon(inst_icon)

        # remove instance node
        self.remove_instance_action = NxtAction(text='Remove Instance',
                                                parent=self)
        self.remove_instance_action.setShortcut('Ctrl+Shift+I')
        self.remove_instance_action.setAutoRepeat(False)
        self.remove_instance_action.setToolTip('Removes Instance')
        self.remove_instance_action.setWhatsThis('Removes instance path from '
                                                 'node overloading weaker '
                                                 'layer instance opinions.')
        rm_inst_icon = QtGui.QIcon()
        rm_inst_pixmap_on = QtGui.QPixmap(':icons/icons/uninstance_node.png')
        rm_inst_pixmap_hov = QtGui.QPixmap(':icons/icons/uninstance_node_hover.png')
        rm_inst_icon.addPixmap(rm_inst_pixmap_hov, QtGui.QIcon.Active,
                            QtGui.QIcon.On)
        rm_inst_icon.addPixmap(rm_inst_pixmap_on, QtGui.QIcon.Normal,
                             QtGui.QIcon.On)
        self.remove_instance_action.setIcon(rm_inst_icon)

        def rm_inst():
            model = self.main_window.model
            for node_path in model.selection:
                self.main_window.model.set_node_instance(node_path, '',
                                                         model.target_layer)
        self.remove_instance_action.triggered.connect(rm_inst)
        # self.addSeparator()

        # cut node
        self.cut_node_action = NxtAction(text='Cut', parent=self)
        self.cut_node_action.setShortcut('Ctrl+X')

        def cut_nodes():
            self.main_window.model.cut_nodes()
        self.cut_node_action.triggered.connect(cut_nodes)
        cut_icon = QtGui.QIcon()
        cut_pixmap_on = QtGui.QPixmap(':icons/icons/cut_node.png')
        cut_pixmap_hov = QtGui.QPixmap(':icons/icons/cut_node_hover.png')
        cut_icon.addPixmap(cut_pixmap_hov, QtGui.QIcon.Active, QtGui.QIcon.On)
        cut_icon.addPixmap(cut_pixmap_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        self.cut_node_action.setIcon(cut_icon)

        # copy node
        self.copy_node_action = NxtAction(text='Copy', parent=self)
        self.copy_node_action.setShortcut('Ctrl+C')
        self.copy_node_action.setShortcutContext(QtCore.Qt.WidgetShortcut)

        def copy_nodes():
            self.main_window.model.copy_nodes()
        self.copy_node_action.triggered.connect(copy_nodes)
        copy_icon = QtGui.QIcon()
        copy_pixmap_on = QtGui.QPixmap(':icons/icons/copy_node.png')
        copy_pixmap_hov = QtGui.QPixmap(':icons/icons/copy_node_hover.png')
        copy_icon.addPixmap(copy_pixmap_hov, QtGui.QIcon.Active, QtGui.QIcon.On)
        copy_icon.addPixmap(copy_pixmap_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        self.copy_node_action.setIcon(copy_icon)

        # paste node
        self.paste_node_action = NxtAction(text='Paste', parent=self)
        self.paste_node_action.setShortcut('Ctrl+V')

        def paste_nodes():
            self.main_window.view.paste_nodes()
        self.paste_node_action.triggered.connect(paste_nodes)
        paste_icon = QtGui.QIcon()
        paste_pixmap_on = QtGui.QPixmap(':icons/icons/paste_node.png')
        paste_pixmap_hov = QtGui.QPixmap(':icons/icons/paste_node_hover.png')
        paste_icon.addPixmap(paste_pixmap_hov, QtGui.QIcon.Active,
                             QtGui.QIcon.On)
        paste_icon.addPixmap(paste_pixmap_on, QtGui.QIcon.Normal,
                             QtGui.QIcon.On)
        self.paste_node_action.setIcon(paste_icon)

        # self.addSeparator()

        # localize node
        self.localize_node_action = NxtAction(text='Localize Node',
                                              parent=self)

        def localize_nodes():
            self.main_window.model.localize_nodes()
        self.localize_node_action.triggered.connect(localize_nodes)
        localize_icon = QtGui.QIcon()
        localize_pixmap_on = QtGui.QPixmap(':icons/icons/localize_node.png')
        localize_pixmap_hov = QtGui.QPixmap(':icons/icons/localize_node_hover.png')
        localize_icon.addPixmap(localize_pixmap_hov, QtGui.QIcon.Active,
                             QtGui.QIcon.On)
        localize_icon.addPixmap(localize_pixmap_on, QtGui.QIcon.Normal,
                             QtGui.QIcon.On)
        self.localize_node_action.setIcon(localize_icon)
        # revert node
        self.revert_node_action = NxtAction(text='Revert Node', parent=self)

        def revert_nodes():
            tgt = self.main_window.model.target_layer
            self.main_window.model.revert_nodes(layer=tgt)
        self.revert_node_action.triggered.connect(revert_nodes)
        revert_icon = QtGui.QIcon()
        revert_pixmap_on = QtGui.QPixmap(':icons/icons/clean_node.png')
        revert_pixmap_hov = QtGui.QPixmap(':icons/icons/clean_node_hover.png')
        revert_icon.addPixmap(revert_pixmap_hov, QtGui.QIcon.Active,
                                QtGui.QIcon.On)
        revert_icon.addPixmap(revert_pixmap_on, QtGui.QIcon.Normal,
                                QtGui.QIcon.On)
        self.revert_node_action.setIcon(revert_icon)
        # Select all

        def select_all():
            self.main_window.view.select_all()
        self.select_all_action = NxtAction(text='Select All Nodes',
                                           parent=self)

        self.select_all_action.setShortcut('Ctrl+A')
        self.select_all_action.triggered.connect(select_all)
        self.select_all_action.setIconText('Select All')

        # Rename node

        def rename_node():
            self.main_window.view.rename_node()
        self.rename_node_action = NxtAction(text='Rename Node', parent=self)
        self.rename_node_action.triggered.connect(rename_node)
        # Disable node

        def toggle_disable():
            self.main_window.model.toggle_nodes_enabled()
        self.disable_node_action = NxtAction(text='Enable/Disable Node',
                                             parent=self)
        self.disable_node_action.setShortcut('D')
        self.disable_node_action.setAutoRepeat(False)
        self.disable_node_action.triggered.connect(toggle_disable)
        # Revert child order

        def revert_child_order():
            self.main_window.model.revert_child_order()
        self.revert_child_order_action = NxtAction(text='Revert child order',
                                                   parent=self)
        self.revert_child_order_action.triggered.connect(revert_child_order)

        # move up in child order

        def up_child_order():
            model = self.main_window.model
            if model:
                model.reorder_child_nodes(model.get_selected_nodes(), -1)
        self.up_child_order_action = NxtAction(text='Move up in child '
                                                    'order', parent=self)
        self.up_child_order_action.triggered.connect(up_child_order)
        self.up_child_order_action.setShortcut('Ctrl+Up')
        # move down in child order
        self.down_child_order_action = NxtAction(text='Move down in child '
                                                      'order', parent=self)

        def down_child_order():
            model = self.main_window.model
            if model:
                model.reorder_child_nodes(model.get_selected_nodes(), 1)

        self.down_child_order_action.triggered.connect(down_child_order)
        self.down_child_order_action.setShortcut('Ctrl+Down')

        # Parent node action

        def parent_nodes():
            sel_node_paths = self.main_window.model.get_selected_nodes()
            if len(sel_node_paths) > 1:
                node_paths = sel_node_paths[:-1]
                parent_path = sel_node_paths[-1]
            else:
                logger.info("Not enough nodes selected for parent command.")
                return
            self.main_window.model.parent_nodes(node_paths=node_paths,
                                                parent_path=parent_path)
        self.parent_nodes_action = NxtAction(text='Parent', parent=self)
        self.parent_nodes_action.setShortcut('P')
        self.parent_nodes_action.setAutoRepeat(False)
        self.parent_nodes_action.triggered.connect(parent_nodes)
        self.parent_nodes_action.setWhatsThis('Parent node(s).')
        # Un-Parent node action

        def unparent_nodes():
            model = self.main_window.model
            model.parent_nodes(node_paths=model.get_selected_nodes(),
                               parent_path=nxt_path.WORLD)
        self.unparent_nodes_action = NxtAction(text='Un-Parent', parent=self)
        self.unparent_nodes_action.setShortcut('Shift+P')
        self.unparent_nodes_action.setAutoRepeat(False)
        self.unparent_nodes_action.triggered.connect(unparent_nodes)
        self.unparent_nodes_action.setWhatsThis('Un-parent node(s).')

        # Toggle Collapse
        def toggle_collapse(recursive):
            model = self.main_window.model
            model.toggle_node_collapse(model.get_selected_nodes(),
                                       recursive_down=recursive)
        self.toggle_collapse_action = NxtAction(text='Toggle Node Collapse',
                                                parent=self)
        self.toggle_collapse_action.setShortcut('Alt+C')
        self.toggle_collapse_action.setAutoRepeat(False)
        self.toggle_collapse_action.setWhatsThis('Toggle the collapse state '
                                                 'for the selected node(s).')
        self.toggle_collapse_action.triggered.connect(partial(toggle_collapse,
                                                              False))

        self.toggle_recursive_collapse_action = NxtAction(text='Recursive '
                                                               'Toggle Node '
                                                               'Collapse',
                                                          parent=self)
        self.toggle_recursive_collapse_action.setShortcut('Shift+Alt+C')
        self.toggle_recursive_collapse_action.setAutoRepeat(False)
        self.toggle_recursive_collapse_action.setWhatsThis('Recursively toggle '
                                                           'the collapse '
                                                           'state for the '
                                                           'selected node(s).')
        func = partial(toggle_collapse, True)
        self.toggle_recursive_collapse_action.triggered.connect(func)

        self.action_display_order = [self.select_all_action,
                                     self.add_node_action,
                                     self.delete_node_action,
                                     self.recursive_delete_node_action,
                                     self.cut_node_action,
                                     self.copy_node_action,
                                     self.paste_node_action,
                                     self.duplicate_node_action,
                                     self.instance_node_action,
                                     self.remove_instance_action,
                                     self.localize_node_action,
                                     self.revert_node_action,
                                     self.disable_node_action,
                                     self.parent_nodes_action,
                                     self.unparent_nodes_action,
                                     self.up_child_order_action,
                                     self.down_child_order_action,
                                     self.toggle_collapse_action,
                                     self.toggle_recursive_collapse_action]


class PropertyEditorActions(NxtActionContainer):
    def __init__(self, main_window):
        super(PropertyEditorActions, self).__init__(main_window)
        self.setObjectName('Property Editor')
        context = QtCore.Qt.WidgetWithChildrenShortcut
        # localize instance path action
        self.localize_inst_path_action = NxtAction(text='Localize '
                                                        'Instance Path',
                                                   parent=self)
        self.localize_inst_path_action.setShortcutContext(context)
        self.localize_inst_path_action.setAutoRepeat(False)
        # revert instance path action
        self.revert_inst_path_action = NxtAction(text='Revert Instance Path',
                                                 parent=self)
        self.revert_inst_path_action.setShortcutContext(context)
        self.revert_inst_path_action.setAutoRepeat(False)
        # localize exec connection action
        self.localize_exec_path_action = NxtAction(text='Localize Exec Path',
                                                   parent=self)
        self.localize_exec_path_action.setShortcutContext(context)
        self.localize_exec_path_action.setAutoRepeat(False)
        # revert exec connection action
        self.revert_exec_path_action = NxtAction(text='Revert Exec Path',
                                                 parent=self)
        self.revert_exec_path_action.setShortcutContext(context)
        self.revert_exec_path_action.setAutoRepeat(False)
        # Add attr action
        self.add_attr_action = NxtAction(text='Add Attribute', parent=self)
        self.add_attr_action.setShortcut('Ctrl+A')
        self.add_attr_action.setShortcutContext(context)
        self.add_attr_action.setAutoRepeat(False)
        # Remove attr action
        self.remove_attr_action = NxtAction(text='Remove Attribute',
                                            parent=self)
        self.remove_attr_action.setShortcutContext(context)
        self.remove_attr_action.setAutoRepeat(False)
        # Localize attr action
        self.localize_attr_action = NxtAction(text='Localize Attribute',
                                              parent=self)
        self.localize_attr_action.setShortcutContext(context)
        self.localize_attr_action.setAutoRepeat(False)
        # Revert attr action
        self.revert_attr_action = NxtAction(text='Revert Attribute',
                                            parent=self)
        self.revert_attr_action.setShortcutContext(context)
        self.revert_attr_action.setAutoRepeat(False)
        # Copy actions
        self.copy_raw_action = NxtAction(text='Copy Raw')
        self.copy_raw_action.setShortcutContext(context)
        self.copy_raw_action.setAutoRepeat(False)
        self.copy_resolved_action = NxtAction(text='Copy Resolved')
        self.copy_resolved_action.setShortcutContext(context)
        self.copy_resolved_action.setAutoRepeat(False)
        self.copy_cached_action = NxtAction(text='Copy Cached')
        self.copy_cached_action.setShortcutContext(context)
        self.copy_cached_action.setAutoRepeat(False)


class NodeCommentActions(NxtActionContainer):
    def __init__(self, main_window):
        super(NodeCommentActions, self).__init__(main_window)
        self.setObjectName('Node Comment')
        self.accept_comment_action = NxtAction('Accept Node Comment',
                                               parent=self)
        self.accept_comment_action.setWhatsThis('Accepts the current text in '
                                                'the comment box as the node '
                                                'comment.')
        self.accept_comment_action.setShortcut('Ctrl+Return')

        self.cancel_comment_action = NxtAction('Cancel Node Comment',
                                               parent=self)
        self.cancel_comment_action.setWhatsThis('Cancels the edit of the node '
                                                'comment.')
        self.cancel_comment_action.setShortcut('Esc')


class AlignmentActions(NxtActionContainer):
    def __init__(self, main_window):
        super(AlignmentActions, self).__init__(main_window)
        self.setObjectName('Alignment')

        def toggle_grid_snap():
            pref_key = user_dir.USER_PREF.GRID_SNAP
            state = self.snap_action.isChecked()
            user_dir.user_prefs[pref_key] = state
        self.snap_action = NxtAction(text='Toggle Grid Snapping',
                                     parent=self)
        self.snap_action.setShortcut('Ctrl+G')
        self.snap_action.setToolTip('Toggle snap to grid')
        self.snap_action.setWhatsThis('Toggles grid snapping while moving '
                                      'nodes.')
        self.snap_action.setCheckable(True)
        self.snap_action.toggled.connect(toggle_grid_snap)
        snap_state = user_dir.user_prefs.get(user_dir.USER_PREF.GRID_SNAP,
                                             False)
        self.snap_action.setChecked(snap_state)
        snap_icon = QtGui.QIcon()
        snap_pixmap_on = QtGui.QPixmap(':icons/icons/gridsnap_on.png')
        snap_pixmap_off = QtGui.QPixmap(':icons/icons/gridsnap_off.png')
        snap_pixmap_hov = QtGui.QPixmap(':icons/icons/gridsnap_on_hover.png')
        snap_icon.addPixmap(snap_pixmap_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        snap_icon.addPixmap(snap_pixmap_hov, QtGui.QIcon.Active, QtGui.QIcon.Off)
        snap_icon.addPixmap(snap_pixmap_off, QtGui.QIcon.Active, QtGui.QIcon.On)
        snap_icon.addPixmap(snap_pixmap_off, QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.snap_action.setIcon(snap_icon)

        self.action_display_order = [self.snap_action]


class DisplayActions(NxtActionContainer):
    def __init__(self, main_window):
        super(DisplayActions, self).__init__(main_window)
        self.setObjectName('Display')
        # This action group is uses to toggle these actions inside of the
        # code editor so they don't trigger when you type Q,W,E

        def set_data_state(state, *args):
            self.main_window.model.data_state = state
        self.ag_data_state = QtWidgets.QActionGroup(self)
        # RAW
        self.raw_action = NxtAction(text='Raw View', parent=self)
        self.raw_action.setShortcut('Q')
        self.raw_action.setShortcutContext(QtCore.Qt.WindowShortcut)
        self.raw_action.setToolTip('Toggle editor view')
        self.raw_action.setWhatsThis('Displays raw editor values for this tab.')
        self.raw_action.setCheckable(True)
        self.ag_data_state.addAction(self.raw_action)
        self.raw_action.triggered.connect(partial(set_data_state,
                                                  DATA_STATE.RAW))
        raw_icon = QtGui.QIcon()
        raw_icn_on = QtGui.QPixmap(':icons/icons/global_unresolved_hover.png')
        raw_icn_off = QtGui.QPixmap(':icons/icons/global_unresolved.png')
        raw_icn_hov = QtGui.QPixmap(':icons/icons/global_unresolved_hover.png')
        raw_icon.addPixmap(raw_icn_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        raw_icon.addPixmap(raw_icn_hov, QtGui.QIcon.Active, QtGui.QIcon.Off)
        raw_icon.addPixmap(raw_icn_off, QtGui.QIcon.Active, QtGui.QIcon.On)
        raw_icon.addPixmap(raw_icn_off, QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.raw_action.setIcon(raw_icon)
        # RESOLVE
        self.resolve_action = NxtAction(text='Resolved View',
                                        parent=self)
        self.resolve_action.setShortcut('W')
        self.resolve_action.setShortcutContext(QtCore.Qt.WindowShortcut)
        self.resolve_action.setToolTip('Toggle resolved view')
        self.resolve_action.setWhatsThis('Displays resolved values for this '
                                         'tab.')
        self.resolve_action.setCheckable(True)
        self.ag_data_state.addAction(self.resolve_action)
        self.resolve_action.triggered.connect(partial(set_data_state,
                                                    DATA_STATE.RESOLVED))
        resolve_icon = QtGui.QIcon()
        resolve_icn_on = QtGui.QPixmap(':icons/icons/global_resolved_hover.png')
        resolve_icn_off = QtGui.QPixmap(':icons/icons/global_resolved.png')
        resolve_icn_hov = QtGui.QPixmap(':icons/icons/global_resolved_hover.png')
        resolve_icon.addPixmap(resolve_icn_on, QtGui.QIcon.Normal,
                               QtGui.QIcon.On)
        resolve_icon.addPixmap(resolve_icn_hov, QtGui.QIcon.Active,
                               QtGui.QIcon.Off)
        resolve_icon.addPixmap(resolve_icn_off, QtGui.QIcon.Active,
                               QtGui.QIcon.On)
        resolve_icon.addPixmap(resolve_icn_off, QtGui.QIcon.Normal,
                               QtGui.QIcon.Off)
        self.resolve_action.setIcon(resolve_icon)
        # CACHED
        self.cached_action = NxtAction(text='Cached View',
                                       parent=self)
        self.cached_action.setShortcut('E')
        self.cached_action.setShortcutContext(QtCore.Qt.WindowShortcut)
        self.cached_action.setToolTip('Toggle cached view')
        self.cached_action.setWhatsThis('Displays cached values for this '
                                        'tab.')
        self.cached_action.setCheckable(True)
        self.ag_data_state.addAction(self.cached_action)
        self.cached_action.triggered.connect(partial(set_data_state,
                                                   DATA_STATE.CACHED))
        cache_icon = QtGui.QIcon()
        cache_icn_on = QtGui.QPixmap(':icons/icons/cache_hover.png')
        cache_icn_off = QtGui.QPixmap(':icons/icons/cache.png')
        cache_icn_hov = QtGui.QPixmap(':icons/icons/cache_hover.png')
        cache_icon.addPixmap(cache_icn_on, QtGui.QIcon.Normal,
                             QtGui.QIcon.On)
        cache_icon.addPixmap(cache_icn_hov, QtGui.QIcon.Active,
                             QtGui.QIcon.Off)
        cache_icon.addPixmap(cache_icn_off, QtGui.QIcon.Active,
                             QtGui.QIcon.On)
        cache_icon.addPixmap(cache_icn_off, QtGui.QIcon.Normal,
                             QtGui.QIcon.Off)
        self.cached_action.setIcon(cache_icon)

        self.action_display_order = [self.raw_action, self.resolve_action,
                                     self.cached_action]


class StageViewActions(NxtActionContainer):
    def __init__(self, main_window):
        super(StageViewActions, self).__init__(main_window)
        self.setObjectName('Graph')
        # TOGGLE GRID

        def toggle_grid():
            state = self.grid_action.isChecked()
            self.main_window.view.toggle_grid(state)

        self.grid_action = BoolUserPrefAction('Toggle Grid',
                                              user_dir.USER_PREF.SHOW_GRID,
                                              default=True,
                                              parent=self)
        self.grid_action.setShortcut('Ctrl+;')
        self.grid_action.setToolTip('Show / Hide the Grid')
        self.grid_action.setWhatsThis('Shows or hides the grid for all tabs.')
        self.grid_action.triggered.connect(toggle_grid)
        grid_icon = QtGui.QIcon()
        grid_icn_on = QtGui.QPixmap(':icons/icons/grid_pressed.png')
        grid_icn_off = QtGui.QPixmap(':icons/icons/grid.png')
        grid_icn_hov = QtGui.QPixmap(':icons/icons/grid_hover.png')
        grid_icon.addPixmap(grid_icn_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        grid_icon.addPixmap(grid_icn_hov, QtGui.QIcon.Active,
                            QtGui.QIcon.Off)
        grid_icon.addPixmap(grid_icn_off, QtGui.QIcon.Active, QtGui.QIcon.On)
        grid_icon.addPixmap(grid_icn_off, QtGui.QIcon.Normal,
                            QtGui.QIcon.Off)
        self.grid_action.setIcon(grid_icon)
        # TOGGLE CONNECTION LINES

        def toggle_lines():
            state = self.implicit_action.isChecked()
            self.main_window.view.toggle_implicit_connections(state)

        self.implicit_action = NxtAction(text='Toggle Implicit Connections',
                                         parent=self)
        self.implicit_action.setShortcut('Ctrl+L')
        self.implicit_action.setToolTip('Show / Hide Implicit Connections')
        self.implicit_action.setWhatsThis('Shows or hides the implicit '
                                          'connections for this tab.')
        self.implicit_action.setCheckable(True)
        self.implicit_action.setChecked(True)
        self.implicit_action.triggered.connect(toggle_lines)
        lines_icon = QtGui.QIcon()
        lines_icn_on = QtGui.QPixmap(
            ':icons/icons/implicit_connections_pressed.png')
        lines_icn_off = QtGui.QPixmap(':icons/icons/implicit_connections.png')
        lines_icn_hov = QtGui.QPixmap(
            ':icons/icons/implicit_connections_hover.png')
        lines_icon.addPixmap(lines_icn_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        lines_icon.addPixmap(lines_icn_hov, QtGui.QIcon.Active, QtGui.QIcon.Off)
        lines_icon.addPixmap(lines_icn_off, QtGui.QIcon.Active, QtGui.QIcon.On)
        lines_icon.addPixmap(lines_icn_off, QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.implicit_action.setIcon(lines_icon)
        # FRAME
        # Frame all
        self.frame_all_action = NxtAction(text='Frame All',
                                          parent=self)
        self.frame_all_action.setShortcut(QtGui.QKeySequence(QtCore.Qt.Key_A))
        self.frame_all_action.setToolTip('Frame all nodes')
        self.frame_all_action.setWhatsThis('Frames all nodes so they are '
                                           'visible.')

        def frame_all():
            self.main_window.view.frame_all()

        self.frame_all_action.triggered.connect(frame_all)
        self.frame_all_action.setShortcutContext(QtCore.Qt.WidgetWithChildrenShortcut)
        fa_icon = QtGui.QIcon()
        fa_icn_on = QtGui.QPixmap(':icons/icons/frame_all.png')
        fa_icn_off = QtGui.QPixmap(':icons/icons/frame_all.png')
        fa_icn_hov = QtGui.QPixmap(':icons/icons/frame_all_hover.png')
        fa_icon.addPixmap(fa_icn_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        fa_icon.addPixmap(fa_icn_hov, QtGui.QIcon.Active,
                          QtGui.QIcon.Off)
        fa_icon.addPixmap(fa_icn_off, QtGui.QIcon.Active, QtGui.QIcon.On)
        fa_icon.addPixmap(fa_icn_off, QtGui.QIcon.Normal,
                          QtGui.QIcon.Off)
        self.frame_all_action.setIcon(fa_icon)

        # Frame selection
        self.frame_selection_action = NxtAction(text='Frame Selection',
                                                parent=self)
        self.frame_selection_action.setShortcut('F')
        self.frame_selection_action.setToolTip('Frame selected node')
        self.frame_selection_action.setWhatsThis('Frames the selected node.')

        def frame_selection():
            self.main_window.view.frame_selection()

        self.frame_selection_action.triggered.connect(frame_selection)
        fs_icon = QtGui.QIcon()
        fs_icn_on = QtGui.QPixmap(':icons/icons/frame_sel.png')
        fs_icn_off = QtGui.QPixmap(':icons/icons/frame_sel.png')
        fs_icn_hov = QtGui.QPixmap(':icons/icons/frame_sel_hover.png')
        fs_icon.addPixmap(fs_icn_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        fs_icon.addPixmap(fs_icn_hov, QtGui.QIcon.Active,
                          QtGui.QIcon.Off)
        fs_icon.addPixmap(fs_icn_off, QtGui.QIcon.Active, QtGui.QIcon.On)
        fs_icon.addPixmap(fs_icn_off, QtGui.QIcon.Normal,
                          QtGui.QIcon.Off)
        self.frame_selection_action.setIcon(fs_icon)

        # Attr display actions
        self.hide_attrs_action = NxtAction(text='Display No Attrs',
                                           parent=self)
        self.hide_attrs_action.setIconText('0')
        self.hide_attrs_action.setShortcut('0')
        self.hide_attrs_action.setAutoRepeat(False)
        self.hide_attrs_action.setWhatsThis('Display no attributes')

        def set_attr_disp(state):
            self.main_window.model.set_attr_display_state(state=state)

        self.hide_attrs_action.triggered.connect(partial(set_attr_disp, 0))
        # Display Local Attrs
        self.disp_local_attrs_action = NxtAction(text='Display Local Attrs',
                                                 parent=self)
        self.disp_local_attrs_action.setIconText('1')
        self.disp_local_attrs_action.setShortcut('1')
        self.disp_local_attrs_action.setAutoRepeat(False)
        self.disp_local_attrs_action.setWhatsThis('Display local '
                                                  'attributes only')
        self.disp_local_attrs_action.triggered.connect(
            partial(set_attr_disp, 1))
        # Display Local and Inst Attrs
        self.disp_inst_attrs_action = NxtAction(text='Display '
                                                     'Local+Inst Attrs',
                                                parent=self)
        self.disp_inst_attrs_action.setIconText('2')
        self.disp_inst_attrs_action.setShortcut('2')
        self.disp_inst_attrs_action.setAutoRepeat(False)
        self.disp_inst_attrs_action.setWhatsThis('Display local and instanced'
                                                 ' attributes')
        self.disp_inst_attrs_action.triggered.connect(partial(set_attr_disp, 2))
        # Display all attrs
        self.disp_all_attrs_action = NxtAction(text='Display All Attrs',
                                               parent=self)
        self.disp_all_attrs_action.setIconText('3')
        self.disp_all_attrs_action.setShortcut('3')
        self.disp_all_attrs_action.setAutoRepeat(False)
        self.disp_all_attrs_action.setWhatsThis('Display local, '
                                                'instanced, and inherited '
                                                'attributes')
        self.disp_all_attrs_action.triggered.connect(partial(set_attr_disp, 3))

        # GENERAL ACTIONS

        def pick_walk(direction):
            self.main_window.model.pick_walk(direction)

        def nudge(direction):
            self.main_window.model.nudge(direction)
        # Pick walk up
        self.pick_walk_up_action = NxtAction(text='Pick walk up', parent=self)
        self.pick_walk_up_action.setShortcut('Up')
        self.pick_walk_up_action.triggered.connect(partial(pick_walk,
                                                           DIRECTIONS.UP))
        # Pick walk down
        self.pick_walk_down_action = NxtAction(text='Pick walk down',
                                               parent=self)
        self.pick_walk_down_action.setShortcut('Down')
        self.pick_walk_down_action.triggered.connect(partial(pick_walk,
                                                             DIRECTIONS.DOWN))
        # Pick walk left
        self.pick_walk_left_action = NxtAction(text='Pick walk left',
                                               parent=self)
        self.pick_walk_left_action.setShortcut('Left')
        self.pick_walk_left_action.triggered.connect(partial(pick_walk,
                                                             DIRECTIONS.LEFT))
        # Pick walk right
        self.pick_walk_right_action = NxtAction(text='Pick walk right',
                                                parent=self)
        self.pick_walk_right_action.setShortcut('Right')
        self.pick_walk_right_action.triggered.connect(partial(pick_walk,
                                                              DIRECTIONS.RIGHT))

        # Nudge up
        self.nudge_up_action = NxtAction(text='Nudge up', parent=self)
        self.nudge_up_action.setShortcut('Shift+Up')
        self.nudge_up_action.triggered.connect(partial(nudge,
                                                       DIRECTIONS.UP))

        # Nudge down
        self.nudge_down_action = NxtAction(text='Nudge down',
                                           parent=self)
        self.nudge_down_action.setShortcut('Shift+Down')
        self.nudge_down_action.triggered.connect(partial(nudge,
                                                         DIRECTIONS.DOWN))
        # Nudge left
        self.nudge_left_action = NxtAction(text='Nudge left',
                                           parent=self)
        self.nudge_left_action.setShortcut('Shift+Left')
        self.nudge_left_action.triggered.connect(partial(nudge,
                                                         DIRECTIONS.LEFT))
        # Nudge right
        self.nudge_right_action = NxtAction(text='Nudge right',
                                            parent=self)
        self.nudge_right_action.setShortcut('Shift+Right')
        self.nudge_right_action.triggered.connect(partial(nudge,
                                                          DIRECTIONS.RIGHT))

        # Toggle node tooltips
        def toggle_tooltip():
            pref_key = user_dir.USER_PREF.NODE_TOOLTIPS
            tooltip_state = self.tooltip_action.isChecked()
            user_dir.user_prefs[pref_key] = tooltip_state
        self.tooltip_action = NxtAction(text='Display Node Tooltips',
                                        parent=self)
        self.tooltip_action.setCheckable(True)
        self.tooltip_action.toggled.connect(toggle_tooltip)
        tt_state = user_dir.user_prefs.get(user_dir.USER_PREF.NODE_TOOLTIPS,
                                           True)
        self.tooltip_action.setChecked(tt_state)
        self.action_display_order = [self.tooltip_action,
                                     self.frame_all_action,
                                     self.frame_selection_action,
                                     self.hide_attrs_action,
                                     self.disp_local_attrs_action,
                                     self.disp_inst_attrs_action,
                                     self.disp_all_attrs_action,
                                     self.grid_action, self.implicit_action,
                                     self.pick_walk_up_action,
                                     self.pick_walk_down_action,
                                     self.pick_walk_left_action,
                                     self.pick_walk_right_action,
                                     self.nudge_up_action,
                                     self.nudge_down_action,
                                     self.nudge_up_action]


class ExecuteActions(NxtActionContainer):
    def __init__(self, main_window):
        super(ExecuteActions, self).__init__(main_window)
        self.setObjectName('Graph Execution')
        # Execute graph
        self.execute_graph_action = NxtAction(text='Execute Graph',
                                              parent=self)
        self.execute_graph_action.setAutoRepeat(False)
        exec_icon = QtGui.QIcon()
        exec_pixmap_off = QtGui.QPixmap(':icons/icons/play.png')
        exec_pixmap_hov = QtGui.QPixmap(':icons/icons/play_hover.png')
        exec_icon.addPixmap(exec_pixmap_hov, QtGui.QIcon.Active, QtGui.QIcon.Off)
        exec_icon.addPixmap(exec_pixmap_off, QtGui.QIcon.Normal, QtGui.QIcon.Off)
        self.execute_graph_action.setIcon(exec_icon)

        def exec_stage():
            if not self.main_window.model:
                logger.error("No stage to execute")
                return
            self.main_window.model.execute_stage()
        self.execute_graph_action.triggered.connect(exec_stage)
        # Execute selection
        self.execute_selected_action = NxtAction(text='Execute '
                                                      'Selected', parent=self)

        self.execute_selected_action.setAutoRepeat(False)
        self.execute_selected_action.setShortcut('Enter')
        self.execute_selected_action.setIconText('Exec Sel')

        def exec_selected():
            if not self.main_window.model:
                logger.error("No stage to execute")
                return
            self.main_window.model.execute_selected()
        self.execute_selected_action.triggered.connect(exec_selected)
        # Execute from selected
        self.execute_from_action = NxtAction(text='Execute '
                                                  'From Selected', parent=self)
        self.execute_from_action.setToolTip('Execute')
        self.execute_from_action.setWhatsThis('Execute from the currently '
                                              'selected node and continue '
                                              'down the exec chain.')
        self.execute_from_action.setAutoRepeat(False)
        self.execute_from_action.setIconText('Exec From Sel')

        def exec_from_sel():
            if not self.main_window.model:
                logger.error("No stage to execute")
                return
            self.main_window.model.execute_from_selected()
        self.execute_from_action.triggered.connect(exec_from_sel)
        # Execute Hierarchy
        self.execute_hierarchy_action = NxtAction(text='Execute '
                                                       'Hierarchy',
                                                  parent=self)
        self.execute_hierarchy_action.setAutoRepeat(False)
        self.execute_hierarchy_action.setIconText('Exec Hierarchy')

        def exec_hierarchy():
            if not self.main_window.model:
                logger.error("No stage to execute")
                return
            self.main_window.model.execute_hierarchy()
        self.execute_hierarchy_action.triggered.connect(exec_hierarchy)

        # add start point
        self.add_start_action = NxtAction(text='Add Start Point',
                                          parent=self)
        self.add_start_action.setAutoRepeat(False)
        add_icon = QtGui.QIcon()
        add_pixmap_on = QtGui.QPixmap(':icons/icons/add_startpoint.png')
        add_pixmap_hov = QtGui.QPixmap(':icons/icons/add_startpoint_hover.png')
        add_icon.addPixmap(add_pixmap_hov, QtGui.QIcon.Active, QtGui.QIcon.On)
        add_icon.addPixmap(add_pixmap_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        self.add_start_action.setIcon(add_icon)

        def add_start():
            self.main_window.model.set_startpoints(state=True)
        self.add_start_action.triggered.connect(add_start)

        # remove start point
        self.remove_start_action = NxtAction(text='Remove Start Point',
                                             parent=self)
        self.remove_start_action.setAutoRepeat(False)
        remove_icon = QtGui.QIcon()
        remove_pixmap_on = QtGui.QPixmap(':icons/icons/remove_startpoint.png')
        remove_pixmap_hov = QtGui.QPixmap(':icons/icons/remove_startpoint_hover.png')
        remove_icon.addPixmap(remove_pixmap_hov, QtGui.QIcon.Active, QtGui.QIcon.On)
        remove_icon.addPixmap(remove_pixmap_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        self.remove_start_action.setIcon(remove_icon)

        def rm_start():
            self.main_window.model.set_startpoints(state=False)
        self.remove_start_action.triggered.connect(rm_start)
        # Find start point(s)
        self.find_start_action = NxtAction(text='Find Startpoint',
                                           parent=self)
        self.find_start_action.setAutoRepeat(False)
        self.find_start_action.setToolTip('Find Startpoint(s)')
        self.find_start_action.setWhatsThis('Cycles the node focus through all '
                                            'start points.')
        find_icon = QtGui.QIcon()
        find_pixmap_on = QtGui.QPixmap(':icons/icons/find_startpoint.png')
        find_pixmap_on = find_pixmap_on.scaled(QtCore.QSize(16, 16),
                                               QtCore.Qt.KeepAspectRatioByExpanding)
        find_pixmap_hov = QtGui.QPixmap(':icons/icons/find_startpoint_hover.png')
        find_icon.addPixmap(find_pixmap_hov, QtGui.QIcon.Active, QtGui.QIcon.On)
        find_icon.addPixmap(find_pixmap_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        self.find_start_action.setIcon(find_icon)
        self.find_start_action.triggered.connect(self.main_window.find_startpoint)
        # add breakpoint
        self.add_break_action = NxtAction(text='Add Breakpoint',
                                          parent=self)
        self.add_break_action.setWhatsThis('Adds the breakpoint on the '
                                           'selected node(s).')
        self.add_break_action.setAutoRepeat(False)

        # revert start point
        self.revert_start_action = NxtAction(text='Revert Start Point',
                                             parent=self)
        self.revert_start_action.setAutoRepeat(False)

        def rvt_start():
            self.main_window.model.set_startpoints(state=None)
        self.revert_start_action.triggered.connect(rvt_start)

        def add_breaks():
            self.main_window.model.set_breakpoints(value=True)
        self.add_break_action.triggered.connect(add_breaks)
        add_icon = QtGui.QIcon()
        add_pixmap_on = QtGui.QPixmap(':icons/icons/add_breakpoint.png')
        add_pixmap_hov = QtGui.QPixmap(':icons/icons/add_breakpoint_hover.png')
        add_icon.addPixmap(add_pixmap_hov, QtGui.QIcon.Active, QtGui.QIcon.On)
        add_icon.addPixmap(add_pixmap_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        self.add_break_action.setIcon(add_icon)
        # remove breakpoints
        self.remove_break_action = NxtAction(text='Remove Breakpoint',
                                             parent=self)
        self.remove_break_action.setWhatsThis('Removes the breakpoint on the '
                                              'selected node(s).')

        def rm_breaks():
            self.main_window.model.set_breakpoints(value=False)
        self.remove_break_action.triggered.connect(rm_breaks)
        self.remove_break_action.setAutoRepeat(False)
        remove_icon = QtGui.QIcon()
        remove_pixmap_on = QtGui.QPixmap(':icons/icons/remove_breakpoint.png')
        remove_pixmap_hov = QtGui.QPixmap(':icons/icons/remove_breakpoint_hover.png')
        remove_icon.addPixmap(remove_pixmap_hov, QtGui.QIcon.Active, QtGui.QIcon.On)
        remove_icon.addPixmap(remove_pixmap_on, QtGui.QIcon.Normal, QtGui.QIcon.On)
        self.remove_break_action.setIcon(remove_icon)
        # clear breakpoints
        self.clear_breaks_action = NxtAction(text='Clear All Breakpoints',
                                             parent=self)
        self.clear_breaks_action.setAutoRepeat(False)

        def clear_breaks():
            self.main_window.model.clear_breakpoints()
        self.clear_breaks_action.triggered.connect(clear_breaks)
        clear_icon = QtGui.QIcon()
        clear_pixmap_on = QtGui.QPixmap(':icons/icons/clear_breakpoints.png')
        clear_pixmap_hov = QtGui.QPixmap(':icons/icons/clear_breakpoints_hover.png')
        clear_icon.addPixmap(clear_pixmap_hov, QtGui.QIcon.Active,
                             QtGui.QIcon.On)
        clear_icon.addPixmap(clear_pixmap_on, QtGui.QIcon.Normal,
                             QtGui.QIcon.On)
        self.clear_breaks_action.setIcon(clear_icon)

        # Toggle start point

        def toggle_startpoints():
            self.main_window.model.set_startpoints(toggle=True)
        self.toggle_start_action = NxtAction(text='Toggle Start Point',
                                             parent=self)
        self.toggle_start_action.setWhatsThis('Toggles a startpoint on the '
                                              'selected node.')
        self.toggle_start_action.setShortcut('S')
        self.toggle_start_action.setAutoRepeat(False)
        self.toggle_start_action.triggered.connect(toggle_startpoints)
        # Toggle breakpoint

        def toggle_breakpoints():
            self.main_window.model.set_breakpoints()
        self.toggle_break_action = NxtAction(text='Toggle Breakpoint',
                                             parent=self)
        self.toggle_break_action.setWhatsThis('Toggles a breakpoint on the '
                                              'selected node(s).')
        self.toggle_break_action.setAutoRepeat(False)
        self.toggle_break_action.setShortcut('B')

        self.toggle_break_action.triggered.connect(toggle_breakpoints)

        self.run_build_action = NxtAction('Run Build', parent=self)
        self.run_build_action.setWhatsThis('Runs build specified by the '
                                           'current value of build view.')

        self.toggle_skip_action = NxtAction(text='Toggle Skippoint',
                                            parent=self)
        self.toggle_skip_action.setWhatsThis('Toggle skippoint on the selected'
                                             'node(s)')
        self.toggle_skip_action.setAutoRepeat(False)
        self.toggle_skip_action.setShortcut('X')

        def toggle_skip():
            node_paths = self.toggle_skip_action.data()
            self.toggle_skip_action.setData(None)
            if not node_paths:
                node_paths = self.main_window.model.get_selected_nodes()
            if not node_paths:
                logger.info("No nodes to toggle skip on.")
                return
            layer = self.main_window.model.top_layer.real_path
            self.main_window.model.toggle_skippoints(node_paths, layer)
        self.toggle_skip_action.triggered.connect(toggle_skip)

        self.set_descendent_skips = NxtAction('Toggle Skip with Descendants',
                                              parent=self)
        self.set_descendent_skips.setWhatsThis('Toggles skip of the selected '
                                               'node(s), applying the '
                                               'skip state to all descendents')
        self.set_descendent_skips.setAutoRepeat(False)
        self.set_descendent_skips.setShortcut('Shift+X')

        def toggle_descendant_skips():
            node_paths = self.set_descendent_skips.data()
            self.set_descendent_skips.setData(None)
            if not node_paths:
                node_paths = self.main_window.model.get_selected_nodes()
            if not node_paths:
                logger.info("No nodes to toggle skip on.")
                return
            self.main_window.model.toggle_descendant_skips(node_paths)
        self.set_descendent_skips.triggered.connect(toggle_descendant_skips)

        def stop():
            self.main_window.model.stop_build()
        self.stop_exec_action = NxtAction(text='Stop Execution', parent=self)
        self.stop_exec_action.setShortcutContext(QtCore.Qt.WidgetShortcut)
        self.stop_exec_action.setShortcut('Esc')
        self.stop_exec_action.setAutoRepeat(True)
        self.stop_exec_action.setEnabled(False)
        self.stop_exec_action.triggered.connect(stop)
        stop_icon = QtGui.QIcon()
        stop_pixmap_off = QtGui.QPixmap(':icons/icons/stop.png')
        stop_pixmap_hov = QtGui.QPixmap(':icons/icons/stop_hover.png')
        stop_icon.addPixmap(stop_pixmap_hov, QtGui.QIcon.Active,
                            QtGui.QIcon.Off)
        stop_icon.addPixmap(stop_pixmap_off, QtGui.QIcon.Normal,
                            QtGui.QIcon.Off)
        self.stop_exec_action.setIcon(stop_icon)

        def pause():
            self.main_window.model.pause_build()

        self.pause_exec_action = NxtAction(text='Pause Execution', parent=self)
        self.pause_exec_action.setShortcutContext(QtCore.Qt.WidgetShortcut)
        self.pause_exec_action.setAutoRepeat(True)
        self.pause_exec_action.triggered.connect(pause)

        self.pause_resume_exec_action = NxtAction(text='Pause/Resume Execution',
                                                  parent=self)
        self.pause_resume_exec_action.setShortcutContext(QtCore.Qt.WidgetShortcut)
        self.pause_resume_exec_action.setAutoRepeat(True)
        self.pause_resume_exec_action.setCheckable(True)
        self.pause_resume_exec_action.setChecked(False)
        pause_icon = QtGui.QIcon()
        pause_pixmap_on = QtGui.QPixmap(':icons/icons/pause.png')
        pause_pixmap_hov = QtGui.QPixmap(':icons/icons/pause_hover.png')
        pause_pixmap_off = QtGui.QPixmap(':icons/icons/play.png')
        pause_icon.addPixmap(pause_pixmap_on, QtGui.QIcon.Normal,
                             QtGui.QIcon.On)
        pause_icon.addPixmap(pause_pixmap_hov, QtGui.QIcon.Active,
                             QtGui.QIcon.Off)
        pause_icon.addPixmap(pause_pixmap_off, QtGui.QIcon.Active,
                             QtGui.QIcon.On)
        pause_icon.addPixmap(pause_pixmap_off, QtGui.QIcon.Normal,
                             QtGui.QIcon.Off)
        self.pause_resume_exec_action.setIcon(pause_icon)

        def step():
            self.main_window.model.step_build()
        self.step_build_action = NxtAction(text='Step Build', parent=self)
        self.step_build_action.setShortcutContext(QtCore.Qt.WidgetShortcut)
        self.step_build_action.setAutoRepeat(False)
        self.step_build_action.triggered.connect(step)
        step_icon = QtGui.QIcon()
        step_pix = QtGui.QPixmap(':icons/icons/step_forward.png')
        step_hov_pix = QtGui.QPixmap(':icons/icons/step_forward_hover.png')
        step_icon.addPixmap(step_pix, QtGui.QIcon.Normal, QtGui.QIcon.Off)
        step_icon.addPixmap(step_hov_pix, QtGui.QIcon.Active, QtGui.QIcon.Off)
        self.step_build_action.setIcon(step_icon)

        def clear_cache():
            self.main_window.model.clear_cache()

        self.clear_cache_action = NxtAction('Clear Cache', parent=self)
        self.clear_cache_action.setWhatsThis('Clears the Python interpreter '
                                             'and cached data.')
        self.clear_cache_action.setToolTip('Clear Cache Now')
        self.clear_cache_action.triggered.connect(clear_cache)
        self.clear_cache_action.setShortcutContext(QtCore.Qt.WindowShortcut)
        # Toggle workflow tools recomping
        self.wt_recomp_action = NxtAction(text='Workflow Tools Always Recomp',
                                          parent=self)
        self.wt_recomp_action.setCheckable(True)
        recomp_pref_key = user_dir.USER_PREF.RECOMP_PREF
        recomp_pref_state = user_dir.user_prefs.get(recomp_pref_key, True)
        self.wt_recomp_action.setChecked(recomp_pref_state)

        def toggle_wt_recomp():
            pref_key = user_dir.USER_PREF.RECOMP_PREF
            recomp_checked = self.wt_recomp_action.isChecked()
            user_dir.user_prefs[pref_key] = recomp_checked
        self.wt_recomp_action.toggled.connect(toggle_wt_recomp)
        # RPC
        self.startup_rpc_action = NxtAction('Startup RPC server', parent=self)
        self.startup_rpc_action.setWhatsThis('Starts RPC (if none is running)')
        self.startup_rpc_action.setToolTip('Startup RPC Server')
        startup_rpc_server = self.main_window.startup_rpc_server
        self.startup_rpc_action.triggered.connect(startup_rpc_server)
        self.startup_rpc_action.setShortcutContext(QtCore.Qt.WindowShortcut)

        self.shutdown_rpc_action = NxtAction('Kill RPC server', parent=self)
        self.shutdown_rpc_action.setWhatsThis('Kills the active rpc server if '
                                              'there is one attached to the '
                                              'main application.')
        self.shutdown_rpc_action.setToolTip('Kill RPC Server')
        shutdown_rpc_server = self.main_window.shutdown_rpc_server
        self.shutdown_rpc_action.triggered.connect(shutdown_rpc_server)
        self.shutdown_rpc_action.setShortcutContext(QtCore.Qt.WindowShortcut)
        self.shutdown_rpc_action.setShortcut('Alt+K')

        def exec_over_cmd_port():
            # TODO: Enabled cmd port entry point once multi-context works
            logger.info('This is a placeholder!')
            # state = self.enable_cmd_port_action.isChecked()
            # self.main_window.model.use_cmd_port = state
            # if state and not self.main_window.model.use_cmd_port:
            #     # Failed to open port
            #     self.enable_cmd_port_action.blockSignals(True)
            #     self.enable_cmd_port_action.setChecked(False)
            #     self.enable_cmd_port_action.blockSignals(False)

        self.enable_cmd_port_action = NxtAction('Connect Command Port',
                                                parent=self)
        self.enable_cmd_port_action.setCheckable(True)
        self.enable_cmd_port_action.setChecked(False)
        self.enable_cmd_port_action.setEnabled(False)
        self.enable_cmd_port_action.toggled.connect(exec_over_cmd_port)

        self.action_display_order = [self.run_build_action,
                                     self.execute_graph_action,
                                     self.execute_selected_action,
                                     self.execute_from_action,
                                     self.execute_hierarchy_action,
                                     self.add_start_action,
                                     self.remove_start_action,
                                     self.revert_start_action,
                                     self.find_start_action,
                                     self.add_break_action,
                                     self.remove_break_action,
                                     self.clear_breaks_action,
                                     self.wt_recomp_action,
                                     self.clear_cache_action,
                                     self.enable_cmd_port_action,
                                     self.startup_rpc_action,
                                     self.shutdown_rpc_action]


class CodeEditorActions(NxtActionContainer):
    def __init__(self, main_window):
        super(CodeEditorActions, self).__init__(main_window)
        self.setObjectName('Code Editor')
        self.indent_line = NxtAction('Indent Line', parent=self)
        self.indent_line.setWhatsThis('Indent selected line(s).')
        self.indent_line.setShortcut('Tab')
        self.unindent_line = NxtAction('Un-Indent Line', parent=self)
        self.unindent_line.setWhatsThis('Un-indent selected line(s).')
        self.unindent_line.setShortcut('Shift+Tab')
        self.new_line = NxtAction('New Line', parent=self)
        self.new_line.setWhatsThis('Insert a new line.')
        self.new_line.setShortcut('Return')
        self.comment_line = NxtAction('Comment Line', parent=self)
        self.comment_line.setWhatsThis('Comment the selected line(s).')
        self.comment_line.setShortcut('Ctrl+/')
        self.font_bigger = NxtAction('Increase Font Size', parent=self)
        self.font_bigger.setWhatsThis('Increase the code editor font size.')
        self.font_bigger.setShortcut('Ctrl+=')
        self.font_smaller = NxtAction('Decrease Font Size', parent=self)
        self.font_smaller.setWhatsThis('Decrease the code editor font size.')
        self.font_smaller.setShortcut('Ctrl+-')
        self.font_size_revert = NxtAction('Revert Font Size', parent=self)
        self.font_size_revert.setWhatsThis('Revert the code editor font size '
                                           'to default.')
        self.font_size_revert.setShortcut('Ctrl+0')
        # accept edit
        self.accept_edit_action = NxtAction('Accept Code Edit', parent=self)
        self.accept_edit_action.setWhatsThis('Accept changes and commit them '
                                             'to the node.')
        self.accept_edit_action.setAutoRepeat(False)
        self.accept_edit_action.setShortcut('Enter')
        # cancel edit
        self.cancel_edit_action = NxtAction('Cancel Code Edit', parent=self)
        self.cancel_edit_action.setWhatsThis('Discard changes to the code.')
        self.cancel_edit_action.setAutoRepeat(False)
        self.cancel_edit_action.setShortcut('Esc')
        # ACTIONS
        context = QtCore.Qt.WidgetWithChildrenShortcut
        # Copy resolved code
        self.copy_resolved_action = NxtAction('Copy Resolved Code',
                                              parent=self)
        self.copy_resolved_action.setWhatsThis('Copy the entire (resolved) '
                                               'contents of the code editor.')
        self.copy_resolved_action.setAutoRepeat(False)
        self.copy_resolved_action.setShortcut('Ctrl+Shift+C')
        self.copy_resolved_action.setShortcutContext(context)
        # Localize code
        self.localize_code_action = NxtAction('Localize Code', parent=self)
        self.localize_code_action.setWhatsThis('Localize the code to the '
                                               'target layer\'s node.')
        self.localize_code_action.setAutoRepeat(False)
        self.localize_code_action.setShortcutContext(context)
        # Revert code
        self.revert_code_action = NxtAction('Revert Code', parent=self)
        self.revert_code_action.setWhatsThis('Revert the code to the next '
                                             'strongest opinion.')
        self.revert_code_action.setAutoRepeat(False)
        self.revert_code_action.setShortcutContext(context)

        self.run_line_local_action = NxtAction('Execute Selection Locally',
                                               parent=self)
        self.run_line_local_action.setWhatsThis('Execute selected line(s) '
                                                'Locally declared variables '
                                                'fall out of scope after '
                                                'execution.')
        self.run_line_local_action.setAutoRepeat(False)
        self.run_line_local_action.setShortcutContext(context)
        self.run_line_local_action.setShortcut('Shift+Return')

        self.run_line_global_action = NxtAction('Execute Selection Globally',
                                                parent=self)
        self.run_line_global_action.setWhatsThis('Execute selected line(s)'
                                                 'All declared variable will '
                                                 'be globally available.')
        self.run_line_global_action.setAutoRepeat(False)
        self.run_line_global_action.setShortcutContext(context)
        self.run_line_global_action.setShortcut('Ctrl+Shift+Return')
        self.run_line_global_action.setShortcutContext(context)

        self.overlay_message_action = NxtAction('Show Double Click Message',
                                                parent=self)
        self.overlay_message_action.setAutoRepeat(False)
        self.overlay_message_action.setCheckable(True)
        state = user_dir.user_prefs.get(user_dir.USER_PREF.SHOW_DBL_CLICK_MSG,
                                        True)
        self.overlay_message_action.setChecked(state)

        self.show_data_state_action = NxtAction('Code Editor Data State Overlay',
                                                parent=self)
        self.show_data_state_action.setWhatsThis('When on this pref will enable a simple HUD on the top right of '
                                                 'the code editor. The HUD will update to display the current data '
                                                 'state (raw, resolved, cached).')
        self.show_data_state_action.setAutoRepeat(False)
        self.show_data_state_action.setCheckable(True)
        state = user_dir.user_prefs.get(user_dir.USER_PREF.SHOW_CE_DATA_STATE,
                                        True)
        self.show_data_state_action.setChecked(state)

        def toggle_dbl_click_msg():
            new = self.overlay_message_action.isChecked()
            user_dir.user_prefs[user_dir.USER_PREF.SHOW_DBL_CLICK_MSG] = new
            self.main_window.code_editor.overlay_widget.update()

        self.overlay_message_action.toggled.connect(toggle_dbl_click_msg)

        self.action_display_order = [self.copy_resolved_action,
                                     self.localize_code_action,
                                     self.revert_code_action,
                                     self.font_bigger, self.font_smaller,
                                     self.font_size_revert,
                                     self.overlay_message_action,
                                     self.show_data_state_action,
                                     self.new_line, self.indent_line,
                                     self.unindent_line,
                                     self.run_line_global_action,
                                     self.run_line_local_action]


def clear_action_data(action_list):
    """Resets the data for each action in the given list to None"""
    for action in action_list:
        action.setData(None)
