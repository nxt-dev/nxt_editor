# Built-in
import os
import json
import traceback
import math
import socket
import pickle
import sys

# External
from Qt import QtWidgets
from Qt import QtCore

# Internal
from nxt import clean_json, nxt_io
from nxt_editor.commands import *
from nxt_editor.dialogs import NxtFileDialog
from nxt.constants import API_VERSION, is_standalone
from nxt import (nxt_path, nxt_layer, tokens, DATA_STATE,
                 NODE_ERRORS, GRID_SIZE)
import nxt_editor
from nxt_editor import DIRECTIONS, StringSignaler, user_dir
from nxt.nxt_layer import LAYERS, CompLayer, SAVE_KEY
from nxt.nxt_node import (get_node_attr, META_ATTRS, get_node_as_dict,
                          get_node_enabled)
from nxt.stage import (determine_nxt_type, INTERNAL_ATTRS,
                       get_historical_opinions)
from nxt.runtime import ExitGraph, GraphError, InvalidNodeError
from nxt_editor.dialogs import NxtConfirmDialog, NxtWarningDialog
from nxt.remote import nxt_socket

logger = logging.getLogger(nxt_editor.LOGGER_NAME)
LAYER_DATA_KEYS = ['position_data', 'enabled_data', 'execute_data' 'break_data']


class EXEC_FRAMING:
    NEVER = 0
    STEPPING = 1
    ALWAYS = 2


class StageModel(QtCore.QObject):
    destroy_cmd_port = QtCore.Signal(None)
    update_cache_dict = QtCore.Signal(dict)
    about_to_rename = QtCore.Signal()
    about_to_execute = QtCore.Signal(bool)
    executing_changed = QtCore.Signal(bool)
    build_changed = QtCore.Signal(tuple)  # new build list
    build_idx_changed = QtCore.Signal(int)
    build_paused_changed = QtCore.Signal(bool)
    processing = QtCore.Signal(bool)
    data_state_changed = QtCore.Signal(bool)
    implicit_connections_changed = QtCore.Signal(bool)
    layer_color_changed = QtCore.Signal(object)
    comp_layer_changed = QtCore.Signal(object)
    disp_layer_changed = QtCore.Signal(str)  # New display layer path
    target_layer_changed = QtCore.Signal(object)
    layer_mute_changed = QtCore.Signal(tuple)  # Layer paths whose mute changed
    layer_solo_changed = QtCore.Signal(tuple)  # Layer paths whose solo changed
    layer_alias_changed = QtCore.Signal(str)  # Layer path whose alias changed
    layer_lock_changed = QtCore.Signal(str)  # Layer path whose locked changed
    layer_removed = QtCore.Signal(str)  # Layer path who was removed
    layer_added = QtCore.Signal(str)  # Layer path who was added
    layer_saved = QtCore.Signal(str)  # Layer path that was just saved
    nodes_changed = QtCore.Signal(tuple)
    attrs_changed = QtCore.Signal(tuple)
    node_added = QtCore.Signal(str)
    node_deleted = QtCore.Signal(str)
    node_moved = QtCore.Signal(str, list)
    selection_changed = QtCore.Signal(tuple)  # new selection
    node_focus_changed = QtCore.Signal(str)
    node_name_changed = QtCore.Signal(str, str)  # old node path, new node path
    node_parent_changed = QtCore.Signal(str, str)  # old node path, new node path
    starts_changed = QtCore.Signal(tuple)  # new start point paths
    breaks_changed = QtCore.Signal(tuple)  # new break point paths
    skips_changed = QtCore.Signal(tuple)  # new skip point paths
    collapse_changed = QtCore.Signal(tuple)  # node paths where changed
    frame_items = QtCore.Signal(tuple)
    server_log = QtCore.Signal(str)
    request_ding = QtCore.Signal()

    def __init__(self, stage):
        super(StageModel, self).__init__()
        self.stage = stage
        self.clipboard = QtWidgets.QApplication.clipboard()
        self.undo_stack = NxtUndoStack(self)
        self.effected_layers = UnsavedLayerSet()

        # execution
        self.is_standalone = is_standalone()
        self.build_start_time = .0
        self.build_paused_time = .0
        self.last_step_time = .0
        self.current_build_order = []
        self._executing = False
        self._build_paused = False
        self._build_should_pause = False
        self._build_should_stop = False
        self._last_built_idx = None
        self.current_rt_layer = None
        self.framing_behavior = EXEC_FRAMING.STEPPING
        self.last_hit_break = None
        self.refresh_exec_framing_from_pref()
        # model states
        self._data_state = DATA_STATE.RESOLVED
        self._implicit_connections = True
        # graph layers
        self._comp_layer = stage.build_stage()
        self._target_layer = stage.top_layer
        self._display_layer = stage.top_layer
        # selection
        self._selection = []
        self._node_focus = None
        self.selection_changed.connect(self.update_node_focus)
        # attribute display state
        # {/node/path: STATE_INT}
        # 0 = no attributes
        # 1 = local attributes only
        # 2 = local and instanced attributes
        # 3 = local, instanced, and inherited attributes
        self._attr_display_state_data = {}
        self.about_to_execute.connect(self.process_events)
        self.cmd_port_client = None
        self.com_port_server = CommandPortListener(self)
        self.cache_filepath = None
        self.com_port_server.update_cache_dict.connect(self.load_cache_dict)
        self._use_cmd_port = False
        self._wait_for_remote = False
        self.com_port_server.destroy_cmd_port.connect(self._destroy_cmd_port)
        app = QtWidgets.QApplication.instance()
        app.aboutToQuit.connect(self._destroy_cmd_port)
        app.aboutToQuit.connect(self.com_port_server.stop)

    @property
    def use_cmd_port(self):
        return self._use_cmd_port

    @use_cmd_port.setter
    def use_cmd_port(self, state):
        keyword = 'Enabling' if state else 'Disabling'
        logger.socket('{} command port...'.format(keyword))
        if state:
            success = self._connect_cmd_port()
            if not success:
                return
        else:
            self._disconnect_cmd_port()
        self._use_cmd_port = state
        keyword = 'Enabled' if state else 'Disabled'
        logger.socket('{} command port'.format(keyword))

    def deleteLater(self):
        self.destroy_cmd_port.emit()
        super(StageModel, self).deleteLater()

    def _destroy_cmd_port(self):
        self._disconnect_cmd_port()
        self.com_port_server.socket.close()
        self._use_cmd_port = False
        logger.socket('Destroyed command port!')

    def resolve(self, node_path, value, layer_path=None):
        """Resolve a given value from the context of the given node path. If
        no layer path or object is provided the comp layer is used. If the
        node path is invalid the string is returned unchanged.
        :param node_path: string of node path
        :param value: string to resolve
        :param layer: NxtLayer or string
        :return: resolved string
        """
        layer = self.lookup_layer(layer_path or LAYERS.COMP)
        node = layer.lookup(node_path)
        if not node:
            return value
        resolved = self.stage.resolve(node, value, layer)
        return resolved

    def _set_attr_display_state(self, node_paths, state):
        """Sets the attribute display state for a given node paths. For
        convenience, if a single node path is passed it will be placed in a
        list for you.
        Note: By design this method will not update the drawing of the nodes.
        Attribute display state data is saved as follows:
            {/node/path: STATE_INT}
                0 = no attributes
                1 = local attributes only
                2 = local and instanced attributes
                3 = local, instanced, and inherited attributes
        :param node_paths: List of node path(s)
        :param state: Int of attr display state
        :return: None
        """
        if not isinstance(node_paths, (list, tuple)):
            node_paths = [node_paths]
        node_paths = node_paths
        for node_path in node_paths:
            self._attr_display_state_data[node_path] = state

    def set_attr_display_state(self, node_paths=None, state=0):
        """Sets the attribute display state for a given node path(s), if none is
        given the current selection is used. After updating the display state
        the node graphics items are re-drawn.
        :param node_paths: List of node path(s)
        :param state: Int of attr display state
        :return: None
        """
        if node_paths in (None, [], ()):
            node_paths = self.get_selected_nodes()
        self._set_attr_display_state(node_paths, state)
        self.nodes_changed.emit(node_paths)

    def get_attr_display_state(self, node_path):
        """Gets the attribute display state for a given node path if there is
        any. If there is no data None is returned.
        :param node_path: String of node path
        :return: Int or None
        """
        return self._attr_display_state_data.get(node_path)

    def remove_attr_display_state(self, node_path):
        """Attempts to remove the attribute display state for a given node path
        if there is any. If there is no data None is returned otherwise the
        remove state is returned.
        :param node_path: String of node path
        :return: Int or None
        """
        try:
            return self._attr_display_state_data.pop(node_path)
        except KeyError:
            return None

    def update_node_focus(self, new_selection):
        if not new_selection:
            self.node_focus = None
            return
        for path in reversed(new_selection):
            if path is None:
                logger.error('Could not update focus to NoneType')
                traceback.print_stack()
                return
            if nxt_path.is_attr_path(path):
                continue
            self.node_focus = path
            return
        # If this point is reached, there are no node paths selected.
        # This means that the node focus is the node path of the most
        # recently selected attribute path.
        self.node_focus = nxt_path.node_path_from_attr_path(new_selection[-1])

    def pick_walk(self, direction):
        sel_node_paths = self.get_selected_nodes()
        if not sel_node_paths:
            return
        new_selection = []
        for cur_path in sel_node_paths:
            parent_path = nxt_path.get_parent_path(cur_path)
            rt = self.comp_layer.RETURNS.Path
            children = self.comp_layer.children(cur_path, return_type=rt,
                                                   ordered=True)
            if parent_path is not nxt_path.WORLD:
                siblings = self.comp_layer.children(parent_path,
                                                       return_type=rt,
                                                       ordered=True)
            else:
                siblings = []
            if cur_path in siblings:
                current_index = siblings.index(cur_path)
            else:
                current_index = None
            next_path = None
            # select parent
            if direction is DIRECTIONS.UP:
                if parent_path is not nxt_path.WORLD:
                    next_path = parent_path

            # select first child
            elif direction is DIRECTIONS.DOWN:
                if children:
                    next_path = children[0]

            # select previous neighbor
            elif direction is DIRECTIONS.LEFT:
                if current_index is not None:
                    if current_index == 0:
                        next_path = siblings[len(siblings) - 1]
                    else:
                        next_path = siblings[current_index - 1]

            # select next neighbor
            elif direction is DIRECTIONS.RIGHT:
                if current_index is not None:
                    if current_index == len(siblings) - 1:
                        next_path = siblings[0]
                    else:
                        next_path = siblings[current_index + 1]
            if next_path:
                new_selection.append(next_path)
        if new_selection:
            self.set_selection(new_selection)

    def nudge(self, direction):
        offset_value = 20
        offset = (0, 0)
        if direction == DIRECTIONS.UP:
            offset = (0, offset_value * -1)
        elif direction == DIRECTIONS.DOWN:
            offset = (0, offset_value)
        elif direction == DIRECTIONS.LEFT:
            offset = (offset_value * -1, 0)
        elif direction == DIRECTIONS.RIGHT:
            offset = (offset_value, 0)
        self.offset_nodes_pos(self.selection, offset)

    def get_layer_alias(self, layer_path):
        """Given a layer path the layer's local alias is returned.
        :param layer_path: string of layer path
        :return: string of layer alias
        """
        layer = self.lookup_layer(layer_path)
        return layer.get_alias()

    @property
    def node_focus(self):
        return self._node_focus

    @node_focus.setter
    def node_focus(self, focus_path):
        if focus_path == self._node_focus:
            return
        self._node_focus = focus_path
        self.node_focus_changed.emit(focus_path)

    @property
    def selection(self):
        return self._selection

    @selection.setter
    def selection(self, paths):
        if self.selection == paths:
            return
        self._selection = paths
        self.selection_changed.emit(tuple(paths))

    def set_selection(self, paths):
        """Sets selection to given `paths`
        The distinction between this function and the above property is that
        this is the undo-able public interface.
        :param paths: Paths to make new selection
        :type paths: list of strings.
        """
        if paths == self.selection:
            return
        cmd = SetSelection(paths, self)
        self.undo_stack.push(cmd)

    def set_selected(self, path, is_selected):
        """Manually sets given `path` to be selected or not.
        NOTE this will ADD or REMOVE from currrent selection,
        not replace selection.

        :param path: Path to set selection state of.
        :type path: str
        :param is_selected: desired selection state
        :type is_selected: bool
        """
        if is_selected:
            self.add_to_selection([path])
        else:
            self.remove_from_selection([path])

    def is_selected(self, path):
        """Returns whether given `path` is selected or not.

        :param path: Path to query selection state of.
        :type path: str
        :return: Whether given path is selected.
        :rtype: bool
        """
        return path in self._selection

    def add_to_selection(self, paths):
        new_paths = []
        for path in paths:
            if path not in self.selection:
                new_paths += [path]
        if not new_paths:
            logger.debug("no new paths to add to selection.")
            return
        cmd = AddSelection(new_paths, self)
        self.undo_stack.push(cmd)

    def remove_from_selection(self, paths):
        rem_paths = []
        for path in paths:
            if path in self.selection:
                rem_paths += [path]
        if not rem_paths:
            logger.debug("no paths selected to remove from selection.")
            return
        cmd = RemoveFromSelection(rem_paths, self)
        self.undo_stack.push(cmd)

    def clear_selection(self):
        if self.selection == []:
            return
        cmd = SetSelection([], self)
        self.undo_stack.push(cmd)

    def get_selected_nodes(self, allow_world=False):
        sel_nodes = []
        for path in self.selection:
            # TODO this assumes that only attr and node paths can be selected.
            # This may or may not remain true.
            if nxt_path.is_attr_path(path):
                continue
            if not allow_world and path is nxt_path.WORLD:
                continue
            sel_nodes += [path]
        return sel_nodes

    def undo(self):
        self.undo_stack.undo()

    def redo(self):
        self.undo_stack.redo()

    @property
    def filepath(self):
        return self.stage.filepath

    @property
    def uid(self):
        return self.stage.uid

    @property
    def data_state(self):
        return self._data_state

    @data_state.setter
    def data_state(self, value):
        self._data_state = value
        self.data_state_changed.emit(value)

    @property
    def implicit_connections(self):
        return self._implicit_connections

    @implicit_connections.setter
    def implicit_connections(self, value):
        self._implicit_connections = value
        self.implicit_connections_changed.emit(value)

    @property
    def layer_names(self):
        return [layer.get_alias() for layer in self.stage.reference_layers]

    @property
    def top_layer(self):
        return self.stage.top_layer

    @property
    def comp_layer(self):
        return self._comp_layer

    @property
    def display_layer(self):
        return self._display_layer

    def set_display_layer(self, layer):
        self.processing.emit(True)
        idx = layer.layer_idx()
        comp_layer = self.stage.build_stage(from_idx=idx)
        self._display_layer = layer
        self.set_comp_layer(comp_layer, rebuild=False)
        self.disp_layer_changed.emit(self.get_layer_path(layer))
        self.processing.emit(False)

    def set_comp_layer(self, layer, rebuild=True, dirty=()):
        self.processing.emit(True)
        if rebuild:
            idx = layer.layer_idx()
            comp_layer = self.stage.build_stage(from_idx=idx)
            self._comp_layer = comp_layer
        else:
            self._comp_layer = layer
        safe_selection = []
        for node_path in self.selection:
            if self.comp_layer.lookup(node_path):
                safe_selection += [node_path]
        self.selection = safe_selection
        self.comp_layer_changed.emit(dirty)
        self.processing.emit(False)

    def update_comp_layer(self, rebuild=False, dirty=()):
        self.set_comp_layer(self.comp_layer, rebuild, dirty)

    @property
    def target_layer(self):
        return self._target_layer

    def _set_target_layer(self, layer):
        self._target_layer = layer
        self.target_layer_changed.emit(self.target_layer)

    def set_target_layer(self, layer_path):
        layer = self.lookup_layer(layer_path)
        if not layer:
            return
        if layer.get_locked():
            logger.warning('"{}" is a locked layer!'.format(layer.alias))
            self.request_ding.emit()
            return
        self._set_target_layer(layer)

    def set_layer_alias(self, alias, layer):
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        illegal_characters = '!"#$%&\'()*+,-./:;<=>?@[\\]^`{|}~ '
        alias = ''.join(
            [c if c not in illegal_characters else '_' for c in alias])
        if not alias:
            logger.error("No alias given, cannot set.")
            return
        cmd = SetLayerAlias(alias=alias, layer_path=layer_path, model=self)
        self.undo_stack.push(cmd)

    def set_layer_color(self, layer_path, color=None):
        """Sets the layer color for the given layer. If color is set to None
        (default) it will not be serialized and the graph default color for
        this layer's index will be used.

        :param layer_path: layer real path
        :type layer_path: str
        :param color: color hex
        :type color: str or None
        """
        layer = self.lookup_layer(layer_path)
        if not layer:
            logger.error('Cannot set color for invalid layer: {}'.format(layer))
            return
        if layer is self.top_layer:
            cur_color = layer.get_color(local=True)
        else:
            cur_color = layer.get_color()
        if cur_color == color:
            logger.error('{} already is already colored {}'.format(layer,
                                                                   color))
            return
        cmd = SetLayerColor(color, layer_path, self)
        self.undo_stack.push(cmd)

    def get_layer_colors(self, layer_list):
        layers_colors = []
        for layer in layer_list:
            layers_colors += [self.get_layer_color(layer)]
        return layers_colors

    def get_layer_color(self, layer, local=False):
        if sys.version_info[0] == 2:
            layer_is_str = isinstance(layer, basestring)
        else:
            layer_is_str = isinstance(layer, str)
        if layer_is_str:
            layer = self.stage.lookup_layer(layer)
        if not layer:
            layer = self.target_layer
        if not layer:
            return None
        color = layer.get_color(local=local)
        if color is None:
            patch_idx = API_VERSION.PATCH
            layer_idx = self.stage.reference_layers.index(layer)
            idx = patch_idx + layer_idx
            layer_color = colors.LAYER_COLORS[idx % len(colors.LAYER_COLORS)].name()
            layer.color = layer_color
            return layer_color
        return color

    def get_layer_locked(self, layer_path):
        layer = self.lookup_layer(layer_path)
        return layer.get_locked()

    def set_layer_locked(self, layer_path, lock=None):
        """Sets the layer lock for the given layer. If lock is set to None
        (default) it will not be serialized and the graph default lock for
        this layer's index will be used.

        :param layer_path: layer real path
        :type layer_path: str
        :param lock: lock state
        :type lock: bool or None
        """
        layer = self.lookup_layer(layer_path)
        if not layer:
            logger.error('Cannot set lock for invalid layer: {}'.format(layer))
            return
        if layer is self.top_layer:
            logger.warning('Cannot lock top layer!')
            self.request_ding.emit()
            return
        else:
            cur_lock = layer.get_locked()
        if cur_lock == lock:
            logger.error('{} lock is already {}'.format(layer, lock))
            return
        cmd = SetLayerLock(lock, layer_path, self)
        self.undo_stack.push(cmd)

    def get_layer(self, layer_alias):
        """Gets a layer via its alias.
        :param layer_alias:
        :return: Layer object or None
        """
        return self.stage.get_layer(layer_alias)

    def lookup_layer(self, layer_path):
        if layer_path == LAYERS.COMP:
            return self.comp_layer
        elif layer_path == LAYERS.TARGET:
            return self.target_layer
        elif layer_path == LAYERS.TOP:
            return self.top_layer
        return self.stage.lookup_layer(layer_path)

    @property
    def soloed_layers(self):
        return nxt_layer.get_soloed_layers(self.stage._sub_layers)

    @property
    def muted_layers(self):
        return nxt_layer.get_muted_layers(self.stage._sub_layers)

    def get_is_layer_active(self, layer):
        active_layers = nxt_layer.get_active_layers(self.stage._sub_layers)
        if layer in active_layers:
            return True
        return False

    @staticmethod
    def get_is_layer_muted(layer):
        return layer.get_muted()

    @staticmethod
    def get_layer_path(layer, fallback=None):
        """Quality of life function that helps you have DRY code. If the
        layer arg is None then the fallback will be used.
        :param layer: Layer object or None
        :param fallback: LAYERS constant
        :return: layer path str
        """
        if layer is not None:
            if isinstance(layer, CompLayer):
                return LAYERS.COMP
            return layer.real_path
        return fallback

    @staticmethod
    def get_is_layer_soloed(layer):
        return layer.get_soloed()

    def get_node_locked(self, node_path, local=False, layer_opinion=True):
        # TODO: Make it so nodes can be locked locally
        local_lock = False
        if local_lock is not None and all((local, not layer_opinion)):
            return local_lock
        node = self.comp_layer.lookup(node_path)
        if not node:
            return False
        src_layer = self.get_node_source_layer(node_path)
        locked = src_layer.get_locked()
        if locked is None:
            return local_lock
        return locked

    def is_top_node(self, node_path):
        parent_path = nxt_path.get_parent_path(node_path)
        if parent_path != nxt_path.WORLD:
            return False
        return True

    def get_node_sibling_paths(self, node_path, layer=None):
        layer = layer or self.comp_layer
        parent_path = nxt_path.get_parent_path(node_path)
        node = layer.lookup(node_path)
        if not node:
            return []
        sibiling_paths = layer.children(parent_path, layer.RETURNS.Path)
        return sibiling_paths

    def get_layers_with_opinion(self, node_path, attr_name=None):
        """Returns all layer paths in the current comp that contain the given
        node. Ordered with the top layer at 0.

        :param node_path: path to find layers for.
        :type node_path: str
        :param attr_name: Optional: name of specific attr that must have an
        opinion at the given node path.
        :type attr_name: str
        :return: list of layer paths
        :rtype: list
        """
        s, e = self.comp_layer._layer_range
        comp_layers = self.stage._sub_layers[s:e]
        layers = nxt_layer.get_active_layers(comp_layers)
        layers = self.stage.get_layers_with_opinion(node_path, layers,
                                                    attr_name)
        return [self.get_layer_path(l) for l in layers]

    def get_node_color(self, node_path, layer=None):
        if sys.version_info[0] == 2:
            layer_is_str = isinstance(layer, basestring)
        else:
            layer_is_str = isinstance(layer, str)
        if layer_is_str:
            layer = self.lookup_layer(layer)
        layer = layer or self.target_layer
        if self.node_exists(node_path):
            node = layer.lookup(node_path)
            source_layer = self.stage.get_node_source_layer(node)
            return self.get_layer_color(source_layer)
        elif self.node_is_implied(node_path):
            for path in self.get_descendants(node_path, layer=layer,
                                             include_implied=True):
                if self.node_exists(path):
                    return self.get_node_color(path, layer=layer)

    def get_node_attr_color(self, node_path, attr_name, layer):
        node = layer.lookup(node_path)
        layer_path, n_path = self.stage.get_node_attr_source(node, attr_name)
        color = self.get_layer_color(layer_path)
        return color

    def node_is_instance_child(self, node_path, layer=None,
                               include_real_children=False):
        '''
        Checks if given node path on a layer is a child of an instance node. Will return True if any ancestor
        is an instance, by default real children will return False as they do not exist as a result of an instance
        :param node_path: String or list of node names ie "node.childNode" or ["node", "childNode"]
        :param layer: Layer to lookup the node under, defaults to the target layer
        :param include_real_children: If true child nodes that are real (exist in the tree even without an instance)
        are considered to be instance children
        :return: bool
        '''
        parent_path = nxt_path.get_parent_path(node_path)
        layer = layer or self.target_layer
        parent_inst = self.get_node_instance(parent_path, layer)
        if parent_inst and include_real_children:
            return True
        elif parent_inst:
            is_proxy = self.get_node_is_proxy(node_path)
            if is_proxy:
                return True
        return False

    def node_attr_is_instance(self, node_path, attr_name, layer=None):
        layer = layer or self.target_layer
        node = layer.lookup(node_path)
        if node:
            inst_attrs = self.get_node_instanced_attr_names(node_path, layer)
            inst = attr_name in inst_attrs
            return inst
        return False

    def get_ancestors(self, node_path, layer=None, include_implied=False):
        """Get a list of ancestor paths.
        :param node_path: String of node path
        :param layer: The layer to search the node path in. Default: comp_layer.
        :param include_implied: Whether to include implied children or not.
        :return: list of node paths"""
        layer = layer or self.comp_layer
        return layer.ancestors(node_path, layer.RETURNS.Path,
                               include_implied=include_implied)

    def get_descendants(self, node_path, layer=None, include_implied=False):
        """Get a list of descendants.
        :param node_path: Namespace or Path to node
        :param layer: The layer to search the node path in. If not given falls
        back to comp layer
        :param include_implied: Whether to include implied children or not.
        :return: list of node paths"""
        layer = layer or self.comp_layer
        return layer.descendants(node_path, layer.RETURNS.Path,
                                 include_implied=include_implied)

    def get_descendant_colors(self, base_path):
        """Get colors of the given base_path's descendant nodes. The color of
        the base path is not included in the list.
        :param base_path: string of node path
        :return: list of colors ie ['#00a5e6', '#119B77']
        """
        layer_colors = []
        base_node = self.comp_layer.lookup(base_path)
        if base_node is None:
            return layer_colors
        layers = []
        des = self.get_descendants(base_path, self.comp_layer, True)
        for d in des:
            node = self.comp_layer.lookup(d)
            if node is not None:
                layer = self.get_node_source_layer(d, self.comp_layer)
                if layer in layers:
                    continue
                layers += [layer]
                color = self.get_layer_color(layer)
                layer_colors += [color]
        return layer_colors

    def get_node_ancestors(self, node_path, layer=None):
        layer = layer or self.comp_layer
        all_ancestors = layer.ancestors(node_path)
        return all_ancestors

    def get_historical_opinions(self, node_path, attr_name):
        node = self.comp_layer.lookup(node_path)
        if node:
            return get_historical_opinions(comp_node=node, attr=attr_name,
                                           comp_layer=self.comp_layer)

    def get_instance_trace(self, node_path):
        """Get the instance trace of a node a return it as a list of source
        and value where source is the instance node path and value is that
        nodes INTERNAL_ATTRS.INSTANCE_PATH value.
        :param node_path: String of node path
        :return: [{META_ATTRS.SOURCE: source, META_ATTRS.VALUE: val}]
        """
        node = self.comp_layer.lookup(node_path)
        node_trace = []
        if node:
            self.stage.get_instance_sources(node, node_trace, self.comp_layer)
        historicals = []
        for inst_node in node_trace:
            path = self.comp_layer.get_node_path(inst_node)
            source = self.get_node_attr_source(path,
                                               INTERNAL_ATTRS.INSTANCE_PATH,
                                               self.comp_layer)
            val = get_node_attr(inst_node, INTERNAL_ATTRS.INSTANCE_PATH)
            historical = {META_ATTRS.SOURCE: source, META_ATTRS.VALUE: val}
            if historical not in historicals:
                historicals += [historical]
        return historicals

    def add_node(self, name='node', data=None, parent_path=None, pos=None,
                 layer=None):
        """Add a new node under the given parent on the given layer. If no parent is provided the
        given layer is used as the parent. If not layer is given the current target layer is used.

        The given name will be modified if it contains illegal characters or clashes with and
        existing node name under the given parent.

        :param name: desired name of the new node ("node")
        :type name: str

        :param data: data to include on the new node (None)
        :type data: dict | None

        :param parent_path: new node's parent path
        :type parent_path: str

        :param pos: position for new node
        :type pos: list | tuple

        :param layer: layer to add node to
        :type layer: comptree.CompTreeNode
        """
        layer = layer or self.target_layer
        parent_path = parent_path or nxt_path.WORLD
        if layer.get_muted():
            logger.error("Cannot add node to muted layer!")
            return
        if pos is None:
            potential_node_path = nxt_path.join_node_paths(parent_path, name)
            pos = self.top_layer.positions.get(potential_node_path)
        cmd = AddNode(name=name, data=data, parent_path=parent_path,
                      pos=pos, model=self, layer_path=layer.real_path)
        self.undo_stack.push(cmd)
        new_node_path = cmd.node_path
        return new_node_path

    def delete_nodes(self, node_paths=(), layer=None, recursive=False):
        if not node_paths:
            node_paths = self.selection
        layer = layer or self.target_layer
        valid_nodes = []
        node_is_implied = False
        for node_path in node_paths:
            node = layer.lookup(node_path)
            node_is_implied = self.node_is_implied(node_path, layer)
            if node or (recursive and node_is_implied):
                valid_nodes += [node_path]
            else:
                msg = '{} not found on target layer and cannot be deleted!'
                logger.warning(msg.format(node_path), links=[node_path])
        node_count = len(valid_nodes)
        if not node_count:
            return
        descendants = {}
        all_rm_paths = valid_nodes[:]
        if recursive:
            for node_path in valid_nodes:
                des = layer.descendants(node_path, ordered=True,
                                        include_implied=True)
                node_count += len(des)
                descendants[node_path] = des
                all_rm_paths += des
        if node_is_implied:
            msg = 'Delete {} and implied descendant(s).'.format(node_paths)
        elif node_count > 1:
            msg = ('Delete {} and '
                   '{} other(s)'.format(node_paths[0], node_count - 1))
        else:
            msg = 'Delete {}'.format(node_paths[0])
        # It may be possible that there are actually no valid nodes. So we
        # queue up the commands to avoid opening an empty macro.
        cmd_queue = []
        for node_path in valid_nodes:
            if recursive:
                des = descendants.get(node_path, [])
                for d in reversed(des):
                    if self.node_exists(d, layer):
                        cmd = DeleteNode(node_path=d, model=self,
                                         layer_path=layer.real_path,
                                         other_removed_nodes=all_rm_paths)
                        cmd_queue += [cmd]
            if self.node_exists(node_path, layer):
                cmd = DeleteNode(node_path=node_path, model=self,
                                 layer_path=layer.real_path,
                                 other_removed_nodes=all_rm_paths)
                cmd_queue += [cmd]
        if not cmd_queue:
            logger.warning("No deletable nodes found "
                           "based on {}".format(valid_nodes),
                           links=valid_nodes)
            return
        self.undo_stack.beginMacro(msg)
        for cmd in cmd_queue:
            self.undo_stack.push(cmd)
        self.undo_stack.endMacro()

    def remove_from_layer_data(self, node_path, key, layer=None):
        layer = layer or self.target_layer
        if hasattr(layer, 'data'):
            if key in layer.data:
                if node_path in layer.data[key]:
                    layer.data[key].pop(node_path)
                if not layer.data[key]:
                    layer.data.pop(key)

    def duplicate_nodes(self, node_paths=(), descendants=True,
                        source_layer=None, target_layer=None):
        if not node_paths:
            node_paths = self.get_selected_nodes(allow_world=True)
        source_layer_path = self.get_layer_path(source_layer,
                                                fallback=LAYERS.COMP)

        target_layer_path = self.get_layer_path(target_layer,
                                                fallback=LAYERS.TARGET)
        for path in node_paths[:]:
            if not self.node_exists(path, self.comp_layer):
                node_paths.remove(path)

        if not node_paths:
            logger.error("No real node paths selected to duplicate.")
            return
        # duplicate
        cmd = DuplicateNodes(node_paths=node_paths,
                             descendants=descendants,
                             model=self,
                             source_layer_path=source_layer_path,
                             target_layer_path=target_layer_path)
        self.undo_stack.push(cmd)

        return cmd.new_node_paths

    def instance_nodes(self, node_paths=(), source_layer=None,
                       target_layer=None):
        if not node_paths:
            node_paths = self.get_selected_nodes()
        if not node_paths:
            logger.error("No node paths selected to instance.")
            return
        source_layer_path = self.get_layer_path(source_layer,
                                                fallback=LAYERS.COMP)
        target_layer_path = self.get_layer_path(target_layer,
                                                fallback=LAYERS.TARGET)
        new_nodes = []
        self.undo_stack.beginMacro("Instance node(s)")
        for node_path in node_paths:
            cmd = InstanceNode(node_path=node_path,
                               model=self,
                               source_layer_path=source_layer_path,
                               target_layer_path=target_layer_path)
            self.undo_stack.push(cmd)
            new_nodes += [cmd.return_value]
        if new_nodes:
            self.selection = new_nodes
        self.undo_stack.endMacro()

    def localize_nodes(self, node_paths=()):
        if not node_paths:
            node_paths = self.selection
        if not node_paths:
            return
        new_nodes = []
        for node_path in node_paths:
            display_node = self.comp_layer.lookup(node_path)
            if not display_node:
                name = nxt_path.node_name_from_node_path(node_path)
                parent_path = nxt_path.get_parent_path(node_path)
                pos = self.top_layer.positions.get(node_path, [0, 0])
                cmd = AddNode(name=name, data=None, parent_path=parent_path,
                              pos=pos, model=self, layer_path=LAYERS.TARGET)
                new_nodes.append(cmd)
        if new_nodes:
            self.undo_stack.beginMacro('Localize {}'.format(node_paths))
        for cmd in new_nodes:
            self.undo_stack.push(cmd)
        cmd = LocalizeNodes(node_paths=node_paths, model=self)
        self.undo_stack.push(cmd)
        if new_nodes:
            self.undo_stack.endMacro()

    def localize_node_attrs(self, node_path, attr_names):
        if not self.comp_layer.lookup(node_path):
            logger.error('Invalid node ' + node_path + attr_names,
                         links=[node_path])
            return
        self.undo_stack.beginMacro('Localize attr(s) {}'.format(attr_names))
        for attr_name in attr_names:
            cmd = LocalizeUserAttr(node_path=node_path, attr_name=attr_name,
                                   model=self, layer_path=LAYERS.TARGET)
            self.undo_stack.push(cmd)
        self.undo_stack.endMacro()

    def localize_node_code(self, node_path):
        if not self.comp_layer.lookup(node_path):
            logger.error('Invalid node ' + node_path, links=[node_path])
            return
        cmd = LocalizeCompute(node_path=node_path, model=self,
                              layer_path=LAYERS.TARGET)
        self.undo_stack.push(cmd)

    def revert_nodes(self, node_paths=(), layer=None):
        if not node_paths:
            node_paths = self.selection
        if layer is not None:
            layer_path = layer.real_path
        else:
            layer_path = LAYERS.TARGET
        safe_node_paths = []
        for node_path in node_paths:
            node = layer.lookup(node_path)
            if node:
                safe_node_paths += [node_path]
            else:
                msg = '{} not found on target layer. Cannot be reverted!'
                logger.warning(msg.format(node_path), links=[node_path])
        self.undo_stack.beginMacro('Revert node(s) {}'.format(safe_node_paths))
        for node_path in safe_node_paths:
            cmd = RevertNode(node_path=node_path, model=self,
                             layer_path=layer_path,
                             others=safe_node_paths[:])
            self.undo_stack.push(cmd)
        self.undo_stack.endMacro()

    def revert_node_attrs(self, node_path, attr_names):
        node = self.target_layer.lookup(node_path)
        if node is None:
            msg = '{} not found on target layer.Its attrs cannot be reverted!'
            logger.warning(msg.format(node_path), links=[node_path])
            return
        local_attrs = self.get_node_local_attr_names(node_path)
        safe_attrs = []
        for attr_name in attr_names:
            if attr_name in local_attrs:
                safe_attrs += [attr_name]
            else:
                logger.warning('{} is not a local '
                               'attr on {}'.format(attr_name, node_path),
                               links=[node_path])
        self.undo_stack.beginMacro('Delete Attributes(s) '
                                   '{} on {}'.format(safe_attrs, node_path))
        for attr_name in safe_attrs:
            cmd = DeleteAttribute(node_path=node_path, attr_name=attr_name,
                                  model=self, layer_path=LAYERS.TARGET)
            self.undo_stack.push(cmd)
        self.undo_stack.endMacro()

    def revert_node_code(self, node_path, layer=None):
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        layer = layer or self.lookup_layer(layer_path)
        node = layer.lookup(node_path)
        if node is None:
            msg = '{} not found on target layer. Compute cannot be reverted!'
            logger.warning(msg.format(node_path), links=[node_path])
            return
        cmd = RevertCompute(node_path=node_path, model=self,
                            layer_path=layer_path)
        self.undo_stack.push(cmd)

    def copy_nodes(self, node_paths=(), cut=False, layer=None):
        if not node_paths:
            node_paths = self.selection
        node_copy_data = []
        for node_path in node_paths:
            _layer = layer or self.comp_layer
            node = _layer.lookup(node_path)
            if node:
                data = get_node_as_dict(self.stage.get_node_spec(node))
                data = {node_path: data}
                node_copy_data.append(json.dumps(data, indent=4,
                                                 sort_keys=False))

        if cut:
            self.delete_nodes(node_paths, layer or self.target_layer)

        output = ',\n'.join(node_copy_data)
        output = '\t' + '\t'.join(output.splitlines(True))
        output = '[\n{}\n]'.format(output)
        self.clipboard.setText(output)
        return True

    def copy_attrs_val(self, node_path, attr_names, data_state):
        if not attr_names:
            return
        vals = []
        for attr_name in attr_names:
            val = self.get_node_attr_value(node_path, attr_name,
                                           self.comp_layer,
                                           data_state=data_state)
            vals += [str(val)]
        self.clipboard.setText(','.join(vals))

    def cut_nodes(self, node_paths=(), layer=None):
        if not node_paths:
            node_paths = self.selection
        return self.copy_nodes(node_paths, cut=True, layer=layer)

    def paste_nodes(self, pos=None, parent_path=None, layer=None):
        node_load_data = []
        try:
            node_load_data = clean_json.load(json.loads(self.clipboard.text(),
                                                        object_hook=clean_json._byteify))
        except ValueError:
            pass

        pos = pos or [0.0, 0.0]
        for node_data in node_load_data:
            node_path, data = list(node_data.items())[0]
            name = nxt_path.node_name_from_node_path(node_path)
            if node_path and name:
                implied_pp = nxt_path.get_parent_path(node_path)
                root = nxt_path.get_root_path(node_path)
                new_root = root + '_pasted'
                if nxt_path.get_path_depth(implied_pp) > 1:
                    new_root = new_root + nxt_path.NODE_SEP
                    root = root + nxt_path.NODE_SEP
                implied_pp = implied_pp.replace(root, new_root, 1)
                pp = parent_path or implied_pp
                if '_pasted' not in pp:
                    name += '_pasted'
                new_node_path = self.add_node(name=name,
                                              data=data,
                                              parent_path=pp,
                                              pos=pos, layer=layer)
                if new_node_path:
                    self._set_node_pos(new_node_path, pos, layer=layer)
                    pos = [pos[0] + 20, pos[1] + 20]

                    self.update_comp_layer()
                    self.node_added.emit(new_node_path)

    def get_node_attr_names(self, node_path, layer=None):
        layer = layer or self.target_layer
        node = layer.lookup(node_path)
        if not node:
            return []
        return self.stage.get_node_attr_names(node)

    def get_cached_attr_names(self, node_path):
        if not self.current_rt_layer:
            return []
        cache_layer = self.current_rt_layer.cache_layer
        frame_node = cache_layer.lookup(node_path)
        if not frame_node:
            return []
        return self.get_node_local_attr_names(node_path, cache_layer)

    def get_node_local_attr_names(self, node_path, layer=None):
        """Get the local attribute names for a given node path. If no layer
        is provided the target layer is used. Note that the target layer does
        not know about nodes with the same path from other layers.
        Technically some local attr names can be missed if using the target
        layer, this is expected behavior. If you truly want all local attr
        names (across multiple layers) pass a comp_layer as the layer arg.
        :param node_path: String of node path
        :param layer: NxtSpecLyer or CompLayer
        :return: list
        """
        layer = layer or self.target_layer
        try:
            s, e = layer._layer_range
            layer_range = self.stage._sub_layers[s:e]
        except AttributeError:
            layer_range = [layer]
        return nxt_layer.get_node_local_attr_names(node_path, layer_range)

    def get_node_instanced_attr_names(self, node_path, comp_layer=None):
        """Get the instance attribute names for a given node path. If no comp
        layer if given the display is used. Layers of type SpecLayer are
        not supported by this method.
        :param node_path: String of node path
        :param comp_layer: CompLayer
        :return: list
        """
        comp_layer = comp_layer or self.comp_layer
        node = comp_layer.lookup(node_path)
        if node:
            inst_attrs = self.stage.get_node_instanced_attr_names(node,
                                                                  comp_layer)
            return inst_attrs
        return []

    def get_node_inherited_attr_names(self, node_path, comp_layer=None):
        """Get the inherited attribute names for a given node path. If no comp
        layer if given the display is used. Layers of type SpecLayer are
        not supported by this method.
        :param node_path: String of node path
        :param comp_layer: CompLayer
        :return: list
       """
        comp_layer = comp_layer or self.comp_layer
        node = comp_layer.lookup(node_path)
        if not node:
            return []
        inherited = self.stage.get_node_inherited_attr_names(node, comp_layer)
        return inherited

    def node_has_parent(self, node_path, layer=None):
        layer = layer or self.target_layer
        node = layer.lookup(node_path)
        if node:
            parent_path = getattr(node, INTERNAL_ATTRS.PARENT_PATH)
            return bool(layer.lookup(parent_path))

    def parent_nodes(self, node_paths, parent_path):
        safe_node_paths = []
        for node_path in node_paths:
            node = self.target_layer.lookup(node_path)
            if node is None:
                msg = '{} not found on target layer and cannot be parented!'
                logger.warning(msg.format(node_path), links=[node_path])
                continue
            node_pp = getattr(node, INTERNAL_ATTRS.PARENT_PATH)
            parent_path_match_a = node_pp == parent_path
            parent_path_match_b = node_pp == nxt_path.WORLD and not parent_path
            if parent_path_match_a or parent_path_match_b:
                msg = "{} is already a child of {}".format(node_path,
                                                           parent_path)
                logger.warning(msg, links=[node_path, parent_path])
                continue
            safe_node_paths += [node_path]

        if safe_node_paths:
            cmd = ParentNodes(node_paths=node_paths,
                              parent_node_path=parent_path, model=self)
            self.undo_stack.push(cmd)
            return cmd.node_path_data

    def get_node_child_order(self, node_path, layer=None):
        layer = layer or self.comp_layer
        node = layer.lookup(node_path)
        if node:
            return self.stage.get_node_child_order(node)
        return []

    def set_node_child_order(self, node_path, child_order):
        """Sets the `child_order` on the node at the `node_path`. If an
        existing node name is not set in the child order it will be added to
        the end of the child order list in to particular order.
        :param node_path: String of node path
        :param child_order: list of strings representing child node names
        :return: None
        """
        layer_path = LAYERS.TARGET
        cmd = SetNodeChildOrder(node_path=node_path, child_order=child_order,
                                model=self, layer_path=layer_path)
        self.undo_stack.push(cmd)

    def has_children(self, node_path, layer=None):
        layer = layer or self.comp_layer
        if not self.node_exists(node_path, layer):
            return False
        return layer.children(node_path, layer.RETURNS.Boolean)

    def get_children(self, node_path, layer=None, ordered=False,
                     include_implied=False):
        layer = layer or self.comp_layer
        if not include_implied and not self.node_exists(node_path, layer):
            return []
        result_paths = layer.children(node_path, layer.RETURNS.Path,
                                      ordered=ordered,
                                      include_implied=include_implied)
        return result_paths

    def add_node_attr(self, node_path, attr='attr', value=None, layer=None):
        layer = layer or self.target_layer
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        good_name = self.stage.get_unique_attr_name(node_path, self.comp_layer,
                                                    attr)
        cmd = AddAttribute(node_path=node_path, attr_name=good_name,
                           value=value, model=self, layer_path=layer_path)
        self.undo_stack.push(cmd)
        return cmd.attr_name

    def rename_node_attr(self, node_path, attr_name, new_attr_name, layer=None):
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        node = layer.lookup(node_path)
        attr_exists = self.stage.node_attr_exists(node, attr_name)
        if not node or not attr_exists:
            info = (node_path, layer.get_alias(), attr_name)
            msg = "{} on the layer {} does not have local attr \"{}\" "
            logger.warning(msg.format(*info), links=[node_path])
            return
        cmd = RenameAttribute(node_path=node_path,
                              attr_name=attr_name,
                              new_attr_name=new_attr_name,
                              model=self,
                              layer_path=layer_path)
        self.undo_stack.push(cmd)

    def delete_node_attr(self, node_path, attr_name, layer=None):
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        layer = self.lookup_layer(layer_path)
        node = layer.lookup(node_path)
        attr_exists = self.stage.node_attr_exists(node, attr_name)
        if not node or not attr_exists:
            info = (node_path, layer.get_alias(), attr_name)
            msg = "{} on the layer {} does not have local attr \"{}\" "
            logger.warning(msg.format(*info), links=[node_path])
            return
        cmd = DeleteAttribute(node_path=node_path, attr_name=attr_name,
                              model=self, layer_path=layer_path)
        self.undo_stack.push(cmd)

    def node_attr_value_is_complex(self, node_path, attr_name, layer=None):
        data_state = DATA_STATE.RAW
        value = self.get_node_attr_value(node_path=node_path,
                                         attr_name=attr_name, layer=layer,
                                         data_state=data_state)
        value = str(value)
        refs = tokens.get_atomic_tokens(value)
        if len(refs) > 1:
            return True
        if value.startswith('${') and value.endswith('}'):
            return False
        return True

    def get_node_source_layer(self, node_path, layer=None):
        """Gets the source layer object for a given node. If no layer is
        given the comp layer is used.
        :param node_path: String of node path
        :param layer: Layer object
        :return: Layer object or None
        """
        layer = layer or self.comp_layer
        node = layer.lookup(node_path)
        if not node:
            return
        source_layer = self.stage.get_node_source_layer(node)
        return source_layer

    def get_node_attr_value(self, node_path, attr_name, layer=None,
                            data_state=DATA_STATE.RESOLVED, as_string=False):
        """Get the attr value for the given attr_name at the node_path. The
        node path is looked up on the given layer (target layer is the default).
        The attr value is resolved according to the data state, resolved is
        the default. Finally, if as_string is True the return will be
        stringed, if the attr value is None then "" is returned.
        :param node_path: String of node path
        :param attr_name: String of attr name
        :param layer: NxtLayer or None
        :param data_state: constants.DATA_STATE constant
        :param as_string: bool
        :return: any
        """
        layer = layer or self.target_layer
        resolved = data_state == DATA_STATE.RESOLVED
        if data_state is DATA_STATE.CACHED:
            if self.is_build_setup():
                # If during build and requested node has not run.
                built = self.current_build_order[:self.last_built_idx + 1]
                if node_path not in built:
                    return None
            if not self.current_rt_layer:
                return None
            layer = self.current_rt_layer.cache_layer
            resolved = False
        node = layer.lookup(node_path)
        attr_value = self.stage.get_node_attr_value(node, attr_name,
                                                    layer=layer,
                                                    resolved=resolved)
        if as_string:
            if attr_value is None:
                attr_value = ""
            else:
                attr_value = str(attr_value)
        return attr_value

    def set_node_attr_value(self, node_path, attr_name, value, layer=None):
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        cmd = SetNodeAttributeValue(node_path=node_path, attr_name=attr_name,
                                    value=value, model=self,
                                    layer_path=layer_path)
        self.undo_stack.push(cmd)

    def node_has_code(self, node_path, layer=None):
        if not node_path:
            return False
        layer = layer or self.target_layer
        node = layer.lookup(node_path)
        if node:
            try:
                code = getattr(node, INTERNAL_ATTRS.COMPUTE)
            except AttributeError:
                code = []
            if code != []:  # DO NOT SIMPLIFY
                return True
        return False

    def get_node_code_source(self, node_path):
        node = self.comp_layer.lookup(node_path)
        if node:
            _, source = self.stage.get_node_attr_source(node,
                                                        INTERNAL_ATTRS.COMPUTE)
            return source

    def get_node_code_string(self, node_path, data_state=DATA_STATE.RAW,
                             layer=None):
        if node_path is None:
            return None
        layer = layer or self.comp_layer
        if data_state in [DATA_STATE.RESOLVED, DATA_STATE.RAW]:
            node = layer.lookup(node_path)
            return self.stage.get_node_code_string(node, layer,
                                                   data_state=data_state)
        elif data_state == DATA_STATE.CACHED:
            if self.current_rt_layer is None:
                logger.info('No cache state.')
                return ''
            node = self.current_rt_layer.cache_layer.lookup(node_path)
            if node:
                return getattr(node, INTERNAL_ATTRS.CACHED_CODE, '')
            else:
                # No cached node found
                return ''
        logger.error("Unknown data state")
        return ''

    def set_node_code_lines(self, node_path, code_lines, layer=None):
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        layer = layer or self.lookup_layer(layer_path)
        node = layer.lookup(node_path)
        if code_lines is None and node is None:
            msg = ("{} not found on target layer. Setting code to None has "
                   "no effect.")
            logger.warning(msg.format(node_path), links=[node_path])
            return
        cmd = SetCompute(node_path=node_path,
                         code_lines=code_lines, model=self,
                         layer_path=layer_path)
        self.undo_stack.push(cmd)

    def get_node_attr_type(self, node_path, attr_name, layer=None):
        layer = layer or self.target_layer
        node = layer.lookup(node_path)
        if node:
            value = self.stage.get_node_attr_value(node, attr_name, layer)
            return determine_nxt_type(value)

    def get_node_attr_comment(self, node_path, attr_name, layer=None):
        layer = layer or self.target_layer
        node = layer.lookup(node_path)
        try:
            return getattr(node, attr_name + META_ATTRS.COMMENT)
        except AttributeError:
            return None

    def node_setattr_comment(self, node_path, attr_name, comment="",
                             layer=None):
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        cmd = SetAttributeComment(node_path=node_path,
                                  attr_name=attr_name,
                                  comment=comment,
                                  model=self,
                                  layer_path=layer_path)
        self.undo_stack.push(cmd)

    def get_node_attr_source_path(self, node_path, attr_name, layer=None):
        layer = layer or self.target_layer
        _, source_path = self.get_node_attr_source(node_path, attr_name, layer)
        return source_path

    def get_node_attr_source_node(self, node_path, attr_name, layer=None):
        layer = layer or self.target_layer
        _, source_node = self.get_node_attr_source(node_path, attr_name, layer)
        return source_node

    def get_node_attr_source(self, node_path, attr_name, layer):
        node = layer.lookup(node_path)
        if not node:
            # Good for debugging:
            # if isinstance(layer, CompLayer):
            #     layer = 'composed layer(range {})'.format(layer._layer_range)
            # else:
            #     layer = {'spec layer {}'}.format(layer.real_path)
            # logger.error('Node {} node not found in {}'.format(node_path,
            #                                                    layer))
            return '', ''
        source_path, source_node = self.stage.get_node_attr_source(node,
                                                                   attr_name)
        return source_path, source_node

    def get_node_instance(self, node_path, layer=None):
        layer = layer or self.target_layer
        node = layer.lookup(node_path)
        instance_node, instance_path = self.stage.safe_get_node_instance(node,
                                                                         layer)
        return instance_node

    def get_node_instance_path(self, node_path, layer=None, expand=True):
        layer = layer or self.target_layer
        node = layer.lookup(node_path)
        instance_path = None
        attr = INTERNAL_ATTRS.INSTANCE_PATH
        if node is None:
            return instance_path
        if expand:
            instance_path = get_node_attr(node, attr)
            if not instance_path:
                return instance_path
            real_path = nxt_path.expand_relative_node_path(instance_path,
                                                           node_path)
            return real_path
        return get_node_attr(node, attr)

    def set_node_instance(self, node_path, instance_path, layer=None):
        if str(node_path) == str(instance_path):
            msg = "Cannot set node's instance to itself {}"
            logger.error(msg.format(node_path), links=[node_path])
            return
        if instance_path == nxt_path.WORLD:
            logger.error("Cannot set a node's instance path to the world.")
            return
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        if instance_path is None:
            logger.error('You should use revert instance path, you can not '
                         'set an instance path to NoneType.')
            return
        expanded_inst_path = nxt_path.expand_relative_node_path(instance_path,
                                                                node_path)
        return_path = self.comp_layer.RETURNS.Path
        ancestors = self.comp_layer.ancestors(node_path,
                                              return_type=return_path,
                                              include_implied=True)
        if expanded_inst_path in ancestors:
            logger.error('Can not instance an ancestor!')
            return
        dependants = self.comp_layer.get_node_dirties(node_path)
        if expanded_inst_path in dependants:
            logger.error('Can not instance a dependant node!')
            return
        cmd = SetNodeInstance(node_path=node_path,
                              instance_path=instance_path, model=self,
                              layer_path=layer_path)
        self.undo_stack.push(cmd)

    def localize_node_instance(self, node_path):
        cmd = LocalizeInstancePath(node_path=node_path, model=self,
                                   layer_path=LAYERS.TARGET)
        self.undo_stack.push(cmd)

    def revert_node_instance(self, node_path, layer=None):
        layer = layer or self.target_layer
        node = layer.lookup(node_path)
        if node is None:
            msg = "Cannot revert {} instance path. Not on target layer"
            logger.warning(msg.format(node_path), links=[node_path])
            return False
        cmd = RevertInstancePath(node_path=node_path, model=self,
                                 layer_path=LAYERS.TARGET)
        self.undo_stack.push(cmd)
        return True

    def get_inst_is_broken(self, node_path, layer=None):
        if not node_path:
            return False
        layer = layer or self.target_layer
        node = layer.lookup(node_path)
        if node:
            instance_path = getattr(node, INTERNAL_ATTRS.INSTANCE_PATH, None)
            instance = layer.lookup(instance_path)
            if instance:
                return False
            elif instance_path == '':
                return False
            elif instance is None and not instance_path:
                return False
        return True

    def node_exec_exists(self, node_path, layer):
        if not node_path:
            return False
        node = layer.lookup(node_path)
        parent_path = getattr(node, INTERNAL_ATTRS.PARENT_PATH)
        has_parent = parent_path != nxt_path.WORLD
        if node:
            exec_source_path = self.get_node_exec_in(node_path, layer)
            if not has_parent and exec_source_path:
                exec_source = self.comp_layer.lookup(exec_source_path)
                if not exec_source:
                    return False
        return True

    def get_node_comment(self, node_path, layer=None):
        layer = layer or self.target_layer
        node = layer.lookup(node_path)
        if node:
            return self.stage.get_node_comment(node)

    def get_node_comment_source(self, node_path):
        node = self.comp_layer.lookup(node_path)
        if node:
            src = self.stage.get_node_attr_source(node,
                                                  INTERNAL_ATTRS.COMMENT +
                                                  META_ATTRS.SOURCE)
            return src

    def set_node_comment(self, node_path, comment, layer=None):
        layer = layer or self.target_layer
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        cmd = SetNodeComment(node_path=node_path, comment=comment,
                             model=self, layer_path=layer_path)
        self.undo_stack.push(cmd)

    def get_node_parent_name(self, node_path, layer=None):
        layer = layer or self.comp_layer
        parent_path = nxt_path.get_parent_path(node_path)
        node = layer.lookup(parent_path)
        if node:
            return getattr(node, INTERNAL_ATTRS.NAME)
        return ''

    def get_node_enabled(self, node_path, layer=None, allow_none=False):
        enabled = True
        if sys.version_info[0] == 2:
            layer_is_str = isinstance(layer, basestring)
        else:
            layer_is_str = isinstance(layer, str)
        if layer_is_str:
            layer = self.lookup_layer(layer)
            if not layer:
                logger.error('Invalid layer path {}, unable to detect '
                             'enabled state for {}'.format(layer, node_path))
        layer = layer or self.comp_layer
        node = layer.lookup(node_path)
        if node:
            enabled = get_node_enabled(node)
        if not allow_none and enabled is None:
            enabled = True
        return enabled

    def get_node_parent_enabled(self, node_path, layer=None):
        layer = layer or self.comp_layer
        parent_path = nxt_path.get_parent_path(node_path)
        node = layer.lookup(parent_path)
        if node:
            return get_node_enabled(node)
        return True

    def get_node_ancestor_enabled(self, node_path, layer=None):
        layer = layer or self.comp_layer
        ancestors = layer.ancestors(node_path)
        for ancestor in ancestors:
            if not self.get_node_enabled(ancestor, layer=layer):
                return False
        return True

    def revert_node_enabled(self, node_paths, layer=None):
        if not node_paths:
            node_paths = self.get_selected_nodes()
        if not node_paths:
            return
        if not isinstance(node_paths, (list, tuple)):
            node_paths = [node_paths]
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        layer = self.lookup_layer(layer_path)
        for path in node_paths[:]:
            if layer.lookup(path) is None:
                node_paths.remove(path)
                logger.warning("Can't revert enabled on {}, is not on the "
                               "target layer {}".format(path, layer.alias),
                               links=[path])
        if not node_paths:
            return
        self.set_node_enabled(node_paths, None, layer)

    def toggle_nodes_enabled(self, node_paths=(), layer=None):
        if not node_paths:
            node_paths = self.get_selected_nodes()
        if not node_paths:
            return
        tgt_layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        disp_layer_path = self.get_layer_path(self.comp_layer)
        enabled = []
        disabled = []
        for path in node_paths[:]:
            if not self.node_exists(path, self.comp_layer):
                continue
            state = self.get_node_enabled(path, disp_layer_path,
                                          allow_none=True)
            if state is None or state is True:
                disabled += [path]
            else:
                enabled += [path]
        node_count = len(enabled) + len(disabled)
        if node_count == 0:
            return
        if node_count > 1:
            msg = ('Set enabled state for {} and '
                   '{} other(s)'.format(node_paths[0], node_count - 1))
        else:
            msg = 'Set enabled state for {}'.format(node_paths[0])
        self.undo_stack.beginMacro(msg)
        if enabled:
            for node_path in enabled:
                cmd = SetNodeEnabledState(node_path=node_path, value=True,
                                          model=self, layer_path=tgt_layer_path)
                self.undo_stack.push(cmd)
        if disabled:
            for node_path in disabled:
                cmd = SetNodeEnabledState(node_path=node_path, value=False,
                                          model=self, layer_path=tgt_layer_path)
                self.undo_stack.push(cmd)
        self.undo_stack.endMacro()

    def set_node_enabled(self, node_paths=(), value=None, layer=None):
        if not node_paths:
            node_paths = self.get_selected_nodes()
        if not node_paths:
            return
        if not isinstance(node_paths, (list, tuple)):
            node_paths = [node_paths]
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        layer = self.lookup_layer(layer_path)
        require_checkbox_update = []
        for path in node_paths[:]:
            node = layer.lookup(path)
            if node is None:
                continue
            state = self.get_node_enabled(path, layer_path, allow_none=True)
            if state == value:
                node_paths.remove(path)
                require_checkbox_update.append(path)
                logger.warning('Enabled state for {} is already "{}" on the '
                               'target layer {}'.format(path, value,
                                                        layer.alias),
                               links=[path])
        node_count = len(node_paths)
        if not node_count:
            self.nodes_changed.emit(require_checkbox_update)
            return
        if value is not None:
            mode = 'Set'
        else:
            mode = 'Reverted'
        if node_count > 1:
            msg = ('{} enabled state for {} and '
                   '{} other(s)'.format(mode, node_paths[0], node_count - 1))
        else:
            msg = '{} enabled state for {}'.format(mode, node_paths[0])
        self.undo_stack.beginMacro(msg)
        for node_path in node_paths:
            cmd = SetNodeEnabledState(node_path=node_path, value=value,
                                      model=self, layer_path=layer_path)
            self.undo_stack.push(cmd)
        self.undo_stack.endMacro()

    def get_node_collapse(self, node_path, layer=None):
        layer = layer or self.comp_layer
        return layer.collapse.get(node_path, False)

    def set_node_collapse(self, node_paths, value, recursive_down=False,
                          recursive_up=False, layer=None):
        """Sets the collapse sate of the given node paths.
        :param node_paths: list of node paths
        :param value: Bool of desired collapse state
        :param recursive_down: If true all nodes below (descendants) the each
        node path in the node paths will be collapsed/-un-collapsed
        :param recursive_up: If true all nodes above (ancestors) the each node
        path in the node paths will be collapsed/-un-collapsed
        :param layer: Layer object defaults to the top layer
        :return: None
        """
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TOP)
        if not isinstance(node_paths, (list, tuple)):
            node_paths = [node_paths]
        node_path_copy = node_paths[:]
        if recursive_up:
            for node_path in node_path_copy:
                node_paths += self.get_ancestors(node_path, self.comp_layer,
                                                 include_implied=True)
        if recursive_down:
            for node_path in node_path_copy:
                node_paths += self.get_descendants(node_path, self.comp_layer,
                                                   include_implied=True)
        cmd = SetNodeCollapse(node_paths=node_paths, value=value, model=self,
                              layer_path=layer_path)
        self.undo_stack.push(cmd)

    def toggle_node_collapse(self, node_paths, recursive_down=False,
                             recursive_up=False, layer_path=None):
        layer = self.lookup_layer(layer_path) or self.top_layer
        comp_layer = self.comp_layer
        set_true = []
        set_false = []
        for node_path in node_paths:
            prev_state = self.get_node_collapse(node_path, layer)
            if prev_state:
                set_false.append(node_path)
            else:
                set_true.append(node_path)
            if recursive_down:
                all_descendants = self.get_descendants(node_path, comp_layer)
                for descendant_path in all_descendants:
                    prev_state = self.get_node_collapse(descendant_path, layer)
                    if prev_state:
                        set_false.append(descendant_path)
                    else:
                        set_true.append(descendant_path)
            if recursive_up:
                all_ancestors = comp_layer.ancestors(node_path)
                for ancestor_node in all_ancestors:
                    ancestor_path = comp_layer.get_node_path(ancestor_node)
                    prev_state = self.get_node_collapse(ancestor_path, layer)
                    if prev_state:
                        set_false.append(ancestor_path)
                    else:
                        set_true.append(ancestor_path)
        if set_true or set_false:
            count = len(set_true + set_false)
            self.undo_stack.beginMacro('Toggle collapse for {} '
                                       'node(s)'.format(count))
        else:
            return
        if set_true:
            self.set_node_collapse(set_true, value=True)
        if set_false:
            self.set_node_collapse(set_false, value=False)
        self.undo_stack.endMacro()

    def get_collapsed_ancestor(self, node_path):
        """Loops over ancestor paths of node path (from world downward) and
        returns the topmost ancestor path that is collapsed, or None if all
        ancestors are expanded.

        :param node_path: path to parse ancestors of
        :type node_path: str
        :return: ancestor path that is collapsed, or None
        :rtype: str or None
        """
        ancestors = nxt_path.all_ancestor_paths(node_path)
        for ancestor in reversed(ancestors):
            if self.get_node_collapse(ancestor, self.comp_layer):
                return ancestor
        return None

    def select_and_frame(self, node_path):
        if not (self.node_exists(node_path) or self.node_is_implied(node_path)):
            return
        self.undo_stack.beginMacro('Select and frame {}'.format(node_path))
        if self.get_collapsed_ancestor(node_path):
            parent = nxt_path.get_parent_path(node_path)
            self.set_node_collapse([parent], False, recursive_up=True)
        self.set_selection([node_path])
        self.frame_items.emit((node_path,))
        self.undo_stack.endMacro()

    def set_nodes_pos(self, node_positions, layer=None):
        if not layer:
            layer = self.top_layer
        clean_positions = {}
        for node_path, pos in node_positions.items():
            if len(nxt_path.str_path_to_node_namespace(node_path)) > 1:
                continue
            clean_positions[node_path] = pos
        if not clean_positions:
            return
        cmd = SetNodesPosition(node_positions=clean_positions, model=self,
                               layer_path=layer.real_path)
        self.undo_stack.push(cmd)

    def get_node_pos(self, node_path):
        default = [0.0, 0.0]
        node_ns = nxt_path.str_path_to_node_namespace(node_path)
        len_node_ns = len(node_ns)
        if len_node_ns > 1:
            return default
        pos = self.comp_layer.positions.get(node_path, default)
        return pos

    def _set_node_pos(self, node_path, pos, layer=None):
        if nxt_path.get_root_path(node_path) != node_path:
            try:
                layer.positions.pop(node_path)
            except KeyError:
                pass
            try:
                self.stage._sub_layers[0].positions.pop(node_path)
            except KeyError:
                pass
            return
        if layer:
            layer.positions[node_path] = pos
            self.comp_layer.positions[node_path] = pos
        self.stage._sub_layers[0].positions[node_path] = pos
        self.node_moved.emit(node_path, pos)

    def offset_nodes_pos(self, node_paths, offset, layer=None):
        """Offset the list of node paths by the given offset value. Respects
        grid snapping.
        :param node_paths: list of node path strings
        :param offset: offset [x, y]
        :param layer: NxtLayer or None, defaults to top layer
        """
        if not layer:
            layer = self.top_layer
        clean_positions = {}
        for node_path in node_paths:
            if nxt_path.get_root_path(node_path) != node_path:
                continue
            clean_positions[node_path] = self.get_pos_offset(node_path,
                                                             offset, layer)
        if not clean_positions:
            return
        cmd = SetNodesPosition(node_positions=clean_positions, model=self,
                               layer_path=layer.real_path)
        self.undo_stack.push(cmd)

    def _offset_node_pos(self, node_path, offset, layer=None):
        """Offset a node pos without an undo
        :param node_path: list of node path strings
        :param offset: offset [x, y]
        :param layer: NxtLayer or LayerPath string
        """
        if sys.version_info[0] == 2:
            layer_is_str = isinstance(layer, basestring)
        else:
            layer_is_str = isinstance(layer, str)
        if layer and layer_is_str:
            layer = self.lookup_layer(layer)
        if layer and nxt_path.get_root_path(node_path) != node_path:
            try:
                layer.positions.pop(node_path)
            except KeyError:
                pass
            try:
                self.stage._sub_layers[0].positions.pop(node_path)
            except KeyError:
                pass
            return
        if sys.version_info[0] == 2:
            layer_is_str = isinstance(layer, basestring)
        else:
            layer_is_str = isinstance(layer, str)
        if layer and layer_is_str:
            layer = self.lookup_layer(layer)
        if layer:
            new_layer_pos = self.get_pos_offset(node_path, offset, layer)
            layer.positions[node_path] = new_layer_pos
        cur_pos = self.stage._sub_layers[0].positions.get(node_path, [0, 0])
        new_pos = [c1 + c2 for c1, c2 in zip(cur_pos, offset)]
        self.stage._sub_layers[0].positions[node_path] = new_pos
        self.node_moved.emit(node_path, new_pos)

    def get_pos_offset(self, node_path, offset, layer):
        """Given a node path and an offset (x,y) return the new absolute
        position of the node.
        :param node_path: String of node path
        :param offset: offset (x, y)
        :param layer: NxtLayer object
        :return: [float, float]
        """
        if isinstance(offset, (int, float)):
            offset = [offset, offset]
        layer_pos = layer.positions.get(node_path, [0, 0])
        new_layer_pos = [c1 + c2 for c1, c2 in zip(layer_pos, offset)]
        key = user_dir.USER_PREF.GRID_SNAP
        if user_dir.user_prefs.get(key, False):
            new_layer_pos = self.snap_pos_to_grid(new_layer_pos)
        return new_layer_pos

    @staticmethod
    def snap_pos_to_grid(pos):
        """Given a posistion find the nearest grid point based on the grid size
        :param pos: [x, y]
        :return: [float, float]
        """
        grid_size = GRID_SIZE
        x = math.floor(pos[0] / grid_size) * grid_size
        y = math.floor(pos[1] / grid_size) * grid_size
        snapped_pos = [x, y]
        return snapped_pos

    def get_node_exec_in(self, node_path, layer=None):
        layer = layer or self.comp_layer
        node = layer.lookup(node_path)
        # If node and parent is not world we return
        if (node is None or
                getattr(node, INTERNAL_ATTRS.PARENT_PATH) != nxt_path.WORLD):
            return
        return self.stage.get_node_exec_in(node)

    def set_node_exec_in(self, node_path, source_node_path, layer=None):
        if str(node_path) == str(source_node_path):
            msg = "Cannot set node's exec in to itself {}"
            logger.error(msg.format(node_path), links=[node_path])
            return False
        if source_node_path == nxt_path.WORLD:
            logger.error("Cannot set node exec in to the world")
            return
        if source_node_path in self.get_exec_order(node_path):
            logger.error('Cannot connect exec in from {} (would cycle)'.format(source_node_path),
                         links=[source_node_path])
            return
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        node_ns = nxt_path.str_path_to_node_namespace(node_path)
        if len(node_ns) > 1:
            msg = 'Cannot connect to exec in of child node: {}'
            logger.error(msg.format(node_path), links=[node_path])
            return False
        layer = self.lookup_layer(layer_path)
        node = layer.lookup(node_path)
        if node and getattr(node, INTERNAL_ATTRS.EXECUTE_IN) == source_node_path:
            msg = ("Node {} execute in path is " 
                  "already set to {}".format(node_path, source_node_path))
            links = [node_path]
            if source_node_path:
                links += [source_node_path]
            logger.error(msg, links=links)
            return False
        cmd = SetNodeExecuteSources(node_path=node_path,
                                    exec_source=source_node_path,
                                    model=self,
                                    layer_path=layer_path)
        self.undo_stack.push(cmd)
        return True

    def localize_node_in_exec_source(self, node_path):
        parent_path = nxt_path.get_parent_path(node_path)
        if parent_path != nxt_path.WORLD:
            logger.error("{} is not a root node".format(node_path),
                         links=[node_path])
            return
        cmd = LocalizeExecPath(node_path=node_path, model=self,
                               layer_path=LAYERS.TARGET)
        self.undo_stack.push(cmd)

    def revert_node_in_exec_source(self, node_path):
        node = self.target_layer.lookup(node_path)
        if not node:
            msg = "Cannot revert {} exec in path. Not on target layer"
            logger.error(msg.format(node_path), links=[node_path])
            return
        cmd = RevertExecPath(node_path=node_path, model=self,
                             layer_path=LAYERS.TARGET)
        self.undo_stack.push(cmd)

    def get_is_node_breakpoint(self, node_path, layer=None):
        layer = layer or self.top_layer
        layer_breaks = user_dir.breakpoints.get(layer.real_path, [])
        return node_path in layer_breaks

    def get_node_is_proxy(self, node_path):
        node = self.comp_layer.lookup(node_path)
        try:
            is_proxy = getattr(node, INTERNAL_ATTRS.PROXY)
        except AttributeError:
            is_proxy = False
        return is_proxy

    def set_breakpoints(self, node_paths=(), value=None, layer=None):
        if not node_paths:
            node_paths = self.selection
        if not node_paths:
            return
        layer_path = self.get_layer_path(layer,
                                         fallback=self.top_layer.real_path)
        if not layer_path:
            logger.warning('Please save your graph to use breaks.')
            self.request_ding.emit()
            return
        on = []
        off = []
        for node_path in node_paths:
            current_state = self.get_is_node_breakpoint(node_path)
            if value is None:
                node_val = not current_state
            else:
                node_val = value
            if node_val:
                on += [node_path]
            else:
                off += [node_path]
        node_count = len(node_paths)
        if node_count > 1:
            msg = ('Set breakpoint state for {} and '
                   '{} other(s)'.format(node_paths[0], node_count - 1))
        else:
            msg = 'Set breakpoint state for {}'.format(node_paths[0])
        self.undo_stack.beginMacro(msg)
        if on:
            cmd = SetNodeBreakPoint(node_paths=on, value=True, model=self,
                                    layer_path=layer_path)
            self.undo_stack.push(cmd)
        if off:
            cmd = SetNodeBreakPoint(node_paths=off, value=False, model=self,
                                    layer_path=layer_path)
            self.undo_stack.push(cmd)
        self.undo_stack.endMacro()

    def clear_breakpoints(self, layer=None):
        layer = layer or self.top_layer
        cmd = ClearBreakpoints(model=self, layer_path=layer.real_path)
        self.undo_stack.push(cmd)
        self.breaks_changed.emit([])

    def _add_breakpoint(self, node_path, layer):
        """Adds the node_path as breakpoint to the layer's breakpoint list.
        :param node_path: String of a node path
        :param layer: Layer object
        :return: None
        """
        if not node_path:
            return
        node_path = str(node_path)
        layer_path = str(layer.real_path)
        layer_breaks = user_dir.breakpoints.get(layer_path, [])
        if node_path in layer_breaks:
            # no need to re-write existing data to pref
            return
        layer_breaks.append(node_path)
        user_dir.breakpoints[layer_path] = layer_breaks
        self.breaks_changed.emit(layer_breaks)

    def _remove_breakpoint(self, node_path, layer):
        """Removes the node_path breakpoint based on the layer's real_path.
        If node_path is None all breakpoints for the layer will be removed.
        :param node_path: String of a node path
        :param layer: Layer object
        :return: None
        """
        layer_path = layer.real_path
        layer_breaks = user_dir.breakpoints.get(layer_path)
        if not layer_breaks:
            return
        if not node_path:
            user_dir.breakpoints.pop(layer_path)
            return
        try:
            layer_breaks.remove(node_path)
        except ValueError:
            # Can return without the below save in this case. If the node
            # path is not present, it's already "removed"
            return
        user_dir.breakpoints[layer_path] = layer_breaks
        self.breaks_changed.emit(layer_breaks)

    def toggle_skippoints(self, node_paths, layer_path=None):
        """Reverse the skip status of all given node paths.

        :param node_paths: Node paths to toggle.
        :type node_paths: iterable
        :param layer_path: Layer to set skips on, defaults to top layer.
        :type layer_path: str, optional
        """
        if not layer_path:
            layer_path = self.top_layer.real_path
        if not layer_path:
            logger.warning('Please save your graph to use skips.')
            self.request_ding.emit()
            return
        on = []
        off = []
        for node_path in node_paths:
            current_state = self.is_node_skippoint(node_path, layer_path)
            node_val = not current_state
            if node_val:
                on += [node_path]
            else:
                off += [node_path]
        node_count = len(node_paths)
        if node_count > 1:
            msg = ('Set skippoint for {} and '
                   '{} other(s)'.format(node_paths[0], node_count - 1))
        else:
            msg = 'Set skippoint for {}'.format(node_paths[0])
        self.undo_stack.beginMacro(msg)
        if on:
            self.set_skippoints(on, True, layer_path)
        if off:
            self.set_skippoints(off, False, layer_path)
        self.undo_stack.endMacro()

    def toggle_descendant_skips(self, node_paths, layer_path=None):
        """Reverse the skip point status of each node given, applying the same
        status to all descendant nodes.

        :param node_paths: Root node(s) to change skip status of.
        :type node_paths: iterable
        :param layer_path: Layer to set skips on, defaults to top layer.
        :type layer_path: str, optional
        """
        if not layer_path:
            layer_path = self.top_layer.real_path
        if not layer_path:
            logger.warning('Please save your graph to use skips.')
            self.request_ding.emit()
            return
        node_count = len(node_paths)
        if node_count > 1:
            msg = ('Set skippoint for {} and '
                   '{} other(s)'.format(node_paths[0], node_count - 1))
        else:
            msg = 'Set skippoint for {}'.format(node_paths[0])
        self.undo_stack.beginMacro(msg)
        for node_path in node_paths:
            to_skip = not self.is_node_skippoint(node_path)
            descendants = self.get_descendants(node_path)
            self.set_skippoints(descendants + [node_path], to_skip, layer_path)
        self.undo_stack.endMacro()

    def set_skippoints(self, node_paths, to_skip, layer_path=None):
        """Set the skip status of given nodes.

        :param node_paths: Nodes to set skip status of.
        :type node_paths: iterable
        :param to_skip: Whether to set nodes to skip or not.
        :type to_skip: bool
        :param layer_path: Layer to set skips on, defaults to top layer.
        :type layer_path: str, optional
        """
        if not layer_path:
            layer_path = self.top_layer.real_path
        if not layer_path:
            logger.warning('Please save your graph to use skips.')
            self.request_ding.emit()
            return
        cmd = SetNodesAreSkipPoints(node_paths, to_skip, layer_path, self)
        self.undo_stack.push(cmd)

    def is_node_skippoint(self, node_path, layer_path=None):
        """Returns True/False based on whether a node is currently a skippoint.

        :param node_path: Node to check.
        :type node_path: str
        :param layer_path: Layer path to check within, defaults to top layer.
        :type layer_path: str, optional
        :return: Whether given node is a skip.
        :rtype: bool
        """
        if not layer_path:
            layer_path = self.top_layer.real_path
        layer_skips = user_dir.skippoints.get(layer_path, [])
        return node_path in layer_skips

    def _add_skippoint(self, node_path, layer_path):
        """Internal(not undo-able) method to make a node a skip point.

        :param node_path: Node to make a skip point.
        :type node_path: str
        :param layer_path: Layer to set skip for.
        :type layer_path: str
        :raises ValueError: If inputs are not complete.
        """
        if not (node_path and layer_path):
            raise ValueError("Must provide node and layer path.")
        node_path = str(node_path)
        layer_path = str(layer_path)
        layer_skips = user_dir.skippoints.get(layer_path, [])
        if node_path in layer_skips:
            # no need to re-write existing data to pref
            return
        layer_skips.append(node_path)
        user_dir.skippoints[layer_path] = layer_skips
        if layer_path == self.top_layer.real_path:
            self.skips_changed.emit([])

    def _remove_skippoint(self, node_path, layer_path):
        """Internal(not undo-able) method to make a node not a skip point.

        :param node_path: Node to remove as a skip point.
        :type node_path: str
        :param layer_path: Layer to set skip for.
        :type layer_path: str
        :raises ValueError: If inputs are not complete.
        """
        if not (node_path and layer_path):
            raise ValueError("Must provide node and layer path.")
        node_path = str(node_path)
        layer_path = str(layer_path)
        layer_skips = user_dir.skippoints.get(layer_path, [])
        if not layer_skips:
            return
        try:
            layer_skips.remove(node_path)
        except ValueError:
            # Can return without the below save in this case. If the node
            # path is not present, it's already "removed"
            if layer_path == self.top_layer.real_path:
                self.skips_changed.emit([])
            return
        user_dir.skippoints[layer_path] = layer_skips
        if layer_path == self.top_layer.real_path:
            self.skips_changed.emit([])

    def get_is_node_start(self, node_path, layer=None):
        """Gets the start node state of a given node.
        :param node_path: String node path
        :param layer: LayerSpecLayer
        :return: bool
        """
        start_attr = INTERNAL_ATTRS.START_POINT
        layer = layer or self.top_layer
        node = layer.lookup(node_path)
        if node is None:
            return None
        state = getattr(node, start_attr)
        return state

    def get_start_nodes(self, layer=None):
        """Get a list of all of the start nodes in a given layer.
        :param layer: Layer
        :return: list of node paths
        """
        layer = layer or self.comp_layer
        return tuple([n for n in layer.descendants() if
                      self.get_is_node_start(n, layer)])

    def set_startpoints(self, node_paths=None, state=None, layer=None,
                        toggle=False):
        if not node_paths:
            node_paths = self.get_selected_nodes()
        if not isinstance(node_paths, (list, tuple)):
            node_paths = [node_paths]
        if not len(node_paths):
            return
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        safe_node_paths = []
        for node_path in node_paths:
            parent_path = nxt_path.get_parent_path(node_path)
            if parent_path == nxt_path.WORLD:
                safe_node_paths += [node_path]
                continue
            logger.warning('{} is not a root node.'.format(node_path),
                           links=[node_path])
        if not safe_node_paths:
            logger.error('No valid nodes to set start points on!')
            return
        if toggle:
            current_state = self.get_is_node_start(node_paths[0],
                                                   self.target_layer)
            if current_state is None:
                current_state = self.get_is_node_start(node_paths[0],
                                                       self.comp_layer)
            state = not current_state
        self.undo_stack.beginMacro('Set multiple start points')
        for node_path in node_paths:
            cmd = SetNodeStartPoint(node_path=node_path, value=state,
                                    model=self, layer_path=layer_path)
            self.undo_stack.push(cmd)
        self.undo_stack.endMacro()
        self.starts_changed.emit(self.get_start_nodes())

    def _revert_start_node(self, node_path, layer):
        node = layer.lookup(node_path)
        if not node:
            logger.error('Failed to revert {} startpoint'.format(node_path),
                         links=[node_path])
            return
        # Fixme: Use universal set attr from stage (coming soon)
        self.stage.node_setattr_data(node, INTERNAL_ATTRS.START_POINT,
                                     layer, respect_protected=False,
                                     create=True, value=None)
        self.starts_changed.emit(self.get_start_nodes())

    def _remove_start_node(self, node_path, layer):
        node = layer.lookup(node_path)
        if not node:
            logger.error('Failed to remove {} startpoint'.format(node_path),
                         links=[node_path])
            return
        # Fixme: Use universal set attr from stage (coming soon)
        self.stage.node_setattr_data(node, INTERNAL_ATTRS.START_POINT,
                                     layer, respect_protected=False,
                                     create=True, value=False)
        self.starts_changed.emit(self.get_start_nodes())

    def _add_start_node(self, node_path, layer):
        node = layer.lookup(node_path)
        if node is None:
            logger.error('Failed to set startpoint at {}'.format(node_path),
                         links=[node_path])
            return
        # Fixme: Use universal set attr from stage (coming soon)
        self.stage.node_setattr_data(node, INTERNAL_ATTRS.START_POINT,
                                     layer, respect_protected=False,
                                     create=True, value=True)
        self.starts_changed.emit(self.get_start_nodes())

    def get_exec_order(self, start_path, layer=None):
        layer = layer or self.comp_layer
        node = layer.lookup(start_path)
        if not node:
            msg = "Cannot find exec order for {}, doesn't exist"
            logger.error(msg.format(start_path))
        return layer.get_exec_order(start_path)

    def get_node_attr_external_sources(self, node_path, attr_name, layer=None):
        layer = layer or self.target_layer
        node = layer.lookup(node_path)
        if node:
            return self.stage.get_node_attr_external_sources(node,
                                                             attr_name, layer)

    def get_node_code_external_sources(self, node_path, layer=None):
        layer = layer or self.target_layer
        node = layer.lookup(node_path)
        return self.stage.get_node_code_external_sources(node, layer)

    def get_node_path(self, node_path, as_string=True):
        node = self.stage.lookup(node_path, self.target_layer)
        if node:
            return self.stage.get_node_path(node, as_string=as_string)
        else:
            return ""

    def node_is_implied(self, node_path, layer=None):
        if not layer:
            layer = self.comp_layer
        if self.node_exists(node_path, layer=layer):
            return False
        if node_path == nxt_path.WORLD:
            # If we're in a graph, the world node is always at least implied.
            return True
        parent_path = nxt_path.get_parent_path(node_path)
        children = self.get_children(parent_path, layer=layer,
                                     include_implied=True)
        return node_path in children

    def node_exists(self, node_path, layer=None):
        if not node_path:
            return False
        if not layer:
            layer = self.comp_layer
        return layer.node_exists(node_path)

    def node_attr_exists(self, node_path, attr_name, layer=None):
        """Checks if a node has an attr. Returns True or False
        :param node_path: Node path
        :param attr_name: String of an attribute name
        :param layer: Layer to lookup node path on, if None the target layer
        will be used
        :returns: bool
        """
        if not attr_name and node_path:
            return False
        node = None
        if isinstance(node_path, str):
            layer = layer or self.target_layer
            node = layer.lookup(node_path)
        if node is None:
            return False
        return self.stage.node_attr_exists(node, attr_name)

    def get_node_error(self, node_path, layer=None):
        layer = layer or self.comp_layer
        node = layer.lookup(node_path)
        errors = []
        if not node:
            return errors
        # instance error
        if self.get_inst_is_broken(node_path, layer):
            errors += [NODE_ERRORS.INSTANCE]
        # exec in error
        if not self.node_exec_exists(node_path, layer):
            errors += [NODE_ERRORS.EXEC]
        # orphans error
        returns = layer.RETURNS.Path
        children_names = [nxt_path.node_name_from_node_path(p)
                          for p in layer.children(node_path, returns,
                                                  include_implied=True)]
        child_order = getattr(node, INTERNAL_ATTRS.CHILD_ORDER)
        for child_name in child_order:
            if child_name not in children_names:
                errors += [NODE_ERRORS.ORPHANS]
                break
        return errors

    def set_node_name(self, node_path, name, layer=None):
        """This is to set the "short name" it will be validated to remove any illegal characters
        and to prevent clashing node names.

        :param node_path:
        :param name:
        :param layer:
        """
        layer = layer or self.target_layer
        node = layer.lookup(node_path)
        existing_name = nxt_path.node_name_from_node_path(node_path)
        if existing_name == name:
            return
        if not node:
            logger.error('Node {} not found on target layer'
                         ' {}'.format(node_path, layer.get_alias()),
                         links=[node_path])
            parent_path = nxt_path.get_parent_path(node_path)
            self.undo_stack.beginMacro('Re-name implied '
                                       'node {} -> {}'.format(node_path, name))
            self.add_node(existing_name, parent_path=parent_path, layer=layer)

        cmd = RenameNode(node_path=node_path, name=name, model=self,
                         layer_path=layer.real_path)
        self.undo_stack.push(cmd)
        if not node:
            self.undo_stack.endMacro()
        return cmd.return_value

    def revert_child_order(self, node_path=None):
        """Reverts the child order on the node at the `node_path`. If the
        node path is None the focused node will be used. If an existing node
        name is not set in the child order it will be added to the end of the
        child order list in to particular order.
        :param node_path: String of node path
        :return: None
        """
        if not node_path:
            node_path = self.node_focus
        node = self.target_layer.lookup(node_path)
        if not node:
            logger.error(node_path + " is not on the target layer!",
                         links=[node_path])
            return
        cmd = SetNodeChildOrder(node_path=node_path,
                                child_order=[],
                                model=self,
                                layer_path=LAYERS.TARGET)
        self.undo_stack.push(cmd)

    def reorder_child_nodes(self, node_paths, direction=False):
        """Reorder the node at the given node path under the parent at the
        given parent path. The direction (-1, 1) nudges the valid child name
        (from the node_path) higher or lower in the list effectively changing
        the order in which it will be executed.
        :param node_paths: node path
        :type node_paths: str
        :param direction: up (-1) or down (1) in the list
        :type direction: int
        :return: None
        """
        if not node_paths:
            logger.error('Nothing selected to re-order')
            return
        # get parent node path
        parent_node_paths = set()
        for node_path in node_paths:
            parent_path = nxt_path.get_parent_path(node_path)
            if not self.node_exists(parent_path):
                logger.error('Node must have a parent. Cannot reorder.')
                return
            parent_node_paths.add(parent_path)
        len_parent_node_paths = len(parent_node_paths)
        if len_parent_node_paths > 1:
            logger.error(
                'Node selection must have a common parent. Cannot reorder.')
            return
        elif not len_parent_node_paths:
            logger.error('No parent paths found.')
            return

        parent_node_path = parent_node_paths.pop()

        # get current child order
        child_order = self.get_node_child_order(parent_node_path)

        # get ordered node names by the current child order
        node_names = [nxt_path.node_name_from_node_path(n) for n in node_paths]
        ordered_node_names = []
        for node_name in child_order:
            if node_name in node_names:
                ordered_node_names.append(node_name)
        if not ordered_node_names:
            child_order = child_order + node_names
            ordered_node_names = node_names
        # get insert index for clean child order
        first_node_name = ordered_node_names[0 if direction < 0 else -1]
        current_index = child_order.index(first_node_name)

        # get child order
        next_index = current_index + direction
        if next_index > len(child_order) - 1:
            next_index = 0
        elif next_index < 0:
            next_index = len(child_order) - 1
        if next_index <= 0:
            for node_name in reversed(ordered_node_names):
                node_index = child_order.index(node_name)
                child_order.insert(0, child_order.pop(node_index))
        elif next_index >= len(child_order) - 1:
            for node_name in ordered_node_names:
                node_index = child_order.index(node_name)
                child_order.append(child_order.pop(node_index))
        else:
            index = next_index
            for node_name in ordered_node_names:
                node_index = child_order.index(node_name)
                child_order.insert(index, child_order.pop(node_index))
                index = child_order.index(node_name) + (
                    0 if direction > 0 else 1)

        # set child order
        self.set_node_child_order(node_path=parent_node_path,
                                  child_order=child_order)

    def new_layer(self, ref_layer, mode=nxt_layer.AUTHORING.CREATE,
                  direction=nxt_layer.AUTHORING.BELOW):
        if mode not in (nxt_layer.AUTHORING.CREATE,
                        nxt_layer.AUTHORING.REFERENCE):
            logger.error("Unknown new layer mode '{}'".format(mode))
            return
        if (mode == nxt_layer.AUTHORING.CREATE and
                direction == nxt_layer.AUTHORING.ABOVE and
                not ref_layer.real_path):
            logger.error('Unable to create layer above an unsaved layer!')
            return
        base_dir = user_dir.USER_DIR
        top_layer_path = self.top_layer.real_path
        if top_layer_path:
            base_dir = os.path.dirname(top_layer_path)
        if mode == nxt_layer.AUTHORING.CREATE:
            proposed_file_name = 'NewGraph.nxt'
            base_dir = os.path.join(base_dir, proposed_file_name)
            file_path = NxtFileDialog.system_file_dialog(base_dir=base_dir,
                                                         mode='save')
        elif mode == nxt_layer.AUTHORING.REFERENCE:
            proposed_file_name = ''
            base_dir = os.path.join(base_dir, proposed_file_name)
            file_path = NxtFileDialog.system_file_dialog(base_dir=base_dir,
                                                         mode='open')
        if not file_path:
            return
        file_name = os.path.splitext(os.path.basename(file_path))[0]
        if not file_name:
            logger.error("No file name!")
            return

        real_path = ref_layer.real_path
        if real_path is None:
            cwd = os.getcwd()
        else:
            cwd = os.path.dirname(real_path)
        idx = ref_layer.layer_idx() + direction
        if idx < 0:
            idx = 0
        if mode == nxt_layer.AUTHORING.CREATE:
            self.create_layer(file_path, file_name, idx=idx, chdir=cwd)
        else:
            self.reference_layer(file_path, idx=idx, chdir=cwd)

    def create_layer(self, file_path, file_name, idx=0, chdir=None):
        cmd = NewLayer(file_path=file_path, file_name=file_name,
                       idx=idx, model=self, chdir=chdir)
        self.undo_stack.push(cmd)
        return

    def reference_layer(self, file_path, idx=0, chdir=None):
        cmd = ReferenceLayer(file_path=file_path, idx=idx, model=self,
                             chdir=chdir)
        self.undo_stack.push(cmd)
        return

    def remove_sublayer(self, layer):
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        cmd = RemoveLayer(layer_path=layer_path, model=self)
        self.undo_stack.push(cmd)
        return

    def mute_toggle_layer(self, layer):
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        cmd = MuteToggleLayer(layer_path=layer_path, model=self)
        self.undo_stack.push(cmd)

    def solo_toggle_layer(self, layer):
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        cmd = SoloToggleLayer(layer_path=layer_path, model=self)
        self.undo_stack.push(cmd)

    def execute_hierarchy(self):
        sel_node_paths = self.get_selected_nodes()
        if len(sel_node_paths) != 1:
            logger.error('Invalid number of nodes selected. You must '
                         'select exactly 1 node when executing a hierarchy.')
            return
        start_path = sel_node_paths[0]
        descendants = self.comp_layer.descendants(start_path, ordered=True)
        exec_order = [start_path] + descendants
        self.execute_nodes(exec_order)

    def execute_from_selected(self):
        sel_node_paths = self.get_selected_nodes()
        if len(sel_node_paths) != 1:
            logger.error('Invalid number of nodes selected. You must '
                         'select exactly 1 node when executing from selected.')
            return
        start_path = sel_node_paths[0]
        exec_order = self.comp_layer.get_exec_order(start_path)
        self.execute_nodes(exec_order)

    def execute_selected(self):
        sel_node_paths = self.get_selected_nodes()
        if not sel_node_paths:
            logger.error("No nodes selected to execute.")
            return
        self.execute_nodes(sel_node_paths)

    def execute_snippet(self, code_string, node_path, rt_layer=None,
                        globally=False):
        """Execute the given code_string as though it were the compute of the
        given node_path. If no runtime layer is given one will be created
        from the current comp layer. By default the code is run in the
        context of a node, meaning it has access to the 'self' keyword and
        local variables are not accessible in the global scope (other nodes).
        You can force a new runtime layer to be generated using the
        force_new_rt_env flag, however by default the current
        `self.current_rt_layer` is used.
        :param code_string: String of code to run.
        :param node_path: String of node path the code is from.
        :param rt_layer: Runtime CompLayer object
        :type rt_layer: CompLayer
        :param globally: If True code will be run in the global scope.
        :return: None
        """
        if not code_string:
            logger.warning('No code to execute!')
            return
        self.about_to_execute.emit(True)
        rt_layer = rt_layer or self.current_rt_layer
        np = [node_path]
        valid, bad_paths = self.validate_runtime_layer(rt_layer=rt_layer,
                                                       node_paths=np)
        if not rt_layer or not valid:
            new_rt = self.prompt_runtime_rebuild(must_rebuild=bool(bad_paths))
            if new_rt:
                rt_layer = new_rt
                self.current_rt_layer = new_rt
            elif not rt_layer:
                return
        if not rt_layer or not hasattr(rt_layer, '_console'):
            logger.grapherror('Tried to execute snippet from {} '
                              'in invalid runtime layer!'.format(node_path),
                              links=[node_path])
            return
        rt_layer._console.run_as_global = globally
        self._set_executing(True)
        try:
            self.stage.execute_custom_code(code_string, node_path, rt_layer)
        except GraphError as err:
            logger.grapherror(str(err), links=[node_path])
        self._set_executing(False)

    def validate_runtime_layer(self, rt_layer=None,
                               comp_layer=None, node_paths=()):
        rt_layer = rt_layer or self.current_rt_layer
        comp_layer = comp_layer or self.comp_layer
        paths_match = False
        invalid_nodes = []
        node_paths = list(node_paths)
        if rt_layer and comp_layer:
            rt_paths = set(rt_layer.descendants())
            comp_paths = set(comp_layer.descendants())
            path_diff = comp_paths.symmetric_difference(rt_paths)
            paths_match = not bool(path_diff)
            if not paths_match:
                for p in node_paths:
                    if bool(rt_layer.lookup(p)):
                        invalid_nodes += [p]
        all_nodes_valid = not invalid_nodes
        if not all_nodes_valid:
            logger.error("{} invalid node(s) in the runtime layer."
                         "".format(len(invalid_nodes)))
        valid = paths_match and all_nodes_valid
        return valid, invalid_nodes

    def prompt_runtime_rebuild(self, must_rebuild=False):
        rt_layer = None
        title = "Invalid runtime node(s)!"

        if must_rebuild:
            cancel_text = 'Ignore and Continue'
            info = ("Some nodes from the runtime layer are invalid.\n"
                    "Would you like to rebuild the runtime layer?\n"
                    "Cache data will be lost!\n\n"
                    "Ignoring this warning may result in graph errors!")
        else:
            info = ("Some node(s) are not present in the current runtime "
                    "layer.\nWould you like to rebuild the runtime "
                    "layer?\nCache data will be lost!")
            cancel_text = 'Cancel Execute'
        button_text = {QtWidgets.QMessageBox.Ok: 'Rebuild',
                       QtWidgets.QMessageBox.Cancel: cancel_text}
        icon = NxtConfirmDialog.Icon.Warning
        confirm = NxtConfirmDialog.show_message(title, info,
                                                button_text=button_text,
                                                icon=icon)
        if confirm:
            temp_comp = self.stage.build_stage(self.comp_layer.layer_idx())
            rt_layer = self.stage.setup_runtime_layer(temp_comp)
            self.current_rt_layer = rt_layer
        return rt_layer

    def validate_socket_connection(self):
        """Attempts a round trip, if the client gets its message and returns
        a ping you should see it in the logger.DEBUG level.
        :return: None
        """
        # if self.cmd_port_client and self.com_port_server.connected:
        self._send_cmd('{MODEL}.ping()'.format(MODEL=nxt_socket.MODEL_VAR))

    def _connect_cmd_port(self):
        """Private method for connecting to remote command port and starting
        the communication port listener thread.
        :return: True if connection was successful
        """
        # TODO: I think we want to make a base remote client object that has
        #  this and other bound methods. Some bits need to change depending
        #  on the context that is connected as a client. An example would be the
        #  need to suppress visual refreshes, the code for Maya is going to
        #  be totally different than Nuke, but they should have a central
        #  method name and signature.
        self.processing.emit(True)
        if not self.cmd_port_client:
            self.cache_filepath = nxt_io.generate_temp_file()
            try:
                self.cmd_port_client = socket.socket(socket.AF_INET,
                                                     socket.SOCK_STREAM)
                self.cmd_port_client.connect((nxt_socket.HOST,
                                              nxt_socket.CMD_PORT))
                self.cmd_port_client.setsockopt(socket.SOL_SOCKET,
                                                socket.SO_REUSEADDR, 1)
                cmd = 'import nxt.remote.nxt_socket'
                self._send_cmd(cmd)
                cmd = '{MODEL} = nxt.remote.nxt_socket.SocketClientModel(None)'
                cmd = cmd.format(MODEL=nxt_socket.MODEL_VAR)
                self._send_cmd(cmd)
            except socket.error as e:
                if e.errno == 10061:
                    logger.warning('Could not connect to cmd port server '
                                   '({}:{})! Please ensure the nxt cmd port is '
                                   'enabled in your external app.'
                                   ''.format(nxt_socket.HOST,
                                             nxt_socket.CMD_PORT))
                else:
                    logger.error(e)
                self.processing.emit(False)
                return False
        try:
            cmd = "{MODEL} = nxt.remote.nxt_socket.get_nxt_model()"
            cmd = cmd.format(MODEL=nxt_socket.MODEL_VAR)
            self._send_cmd(cmd)
            cmd = '{MODEL}.cache_filepath = "{cache_file}"'
            cmd = cmd.format(MODEL=nxt_socket.MODEL_VAR,
                             cache_file=self.cache_filepath)
            self._send_cmd(cmd)
        except Exception as e:
            self.processing.emit(False)
            self.destroy_cmd_port.emit()
            logger.exception('Failed to connect to cmd port server!')
            return False
        self.com_port_server.kill = False
        listening = True
        if not self.com_port_server.isRunning():
            listening = False
            logger.socket('Starting com sever...')
            self.com_port_server.start()
            logger.socket('Telling remote to connect to com port...')
            self._send_cmd('{MODEL}.open()'.format(MODEL=nxt_socket.MODEL_VAR))
            i = 0
            while i < 20:
                if self.com_port_server.listening:
                    listening = True
                    break
                time.sleep(.5)
                i += 1
        if not listening:
            self.process_events()
            self.destroy_cmd_port.emit()
            logger.error('Failed to start com server!')
            self.processing.emit(False)
            return False

        self.processing.emit(False)
        return True

    def _disconnect_cmd_port(self):
        """Attempt to gracefully shutdown the command port and the com port
        listener."""
        if self.cmd_port_client:
            self.cmd_port_client.shutdown(socket.SHUT_WR)
            self.cmd_port_client.close()
            self.cmd_port_client = None
        if self.com_port_server.client:
            self.com_port_server.client.shutdown(socket.SHUT_RDWR)
            self.com_port_server.client.close()
            self.com_port_server.client = None
        self.com_port_server.stop()
        if self.com_port_server.isRunning():
            self.com_port_server.terminate()

    def _send_cmd(self, cmd, wait=False):
        """Send command to the socket client. If wait is True we block the
        main thread until the server has received the command and responded.
        WARNING: Only set wait to True if the command you are sending is
        handled by nxt_socket.IPCWait context manager. Otherwise the
        application will be stuck in an infinite loop.
        :param cmd: string of command to be run by the client
        :param wait: bool
        :return: None
        """
        print('sending {}'.format(cmd))
        if not self.cmd_port_client:
            logger.error('No socket server connected!')
        byte_data = bytes(str(cmd) + '\n')
        self._wait_for_remote = wait
        if wait:
            with IPCWait(self):
                self.cmd_port_client.sendall(byte_data)
        else:
            self.cmd_port_client.sendall(byte_data)

    def update_remote_comp(self):
        """Save editor state to a temp location and command the socket client
        to load that data.
        :return: None
        """
        logger.debug('Dumping editor to temp file...')
        graph_path = self.stage.save_to_temp(self.comp_layer)
        logger.debug('Updating remote...')
        cmd = '{MODEL}.load("{GRAPH}")'.format(GRAPH=graph_path,
                                               MODEL=nxt_socket.MODEL_VAR)
        self._send_cmd(cmd)

    def execute_nodes(self, node_paths, rt_layer=None, safe_exec=True):
        """Executes given node paths in the given runtime layer. If no rt
        layer is given a new one is built.

        :param node_paths: list of node paths
        :param rt_layer: CompLayer (must have self.runtime set to True)
        :param safe_exec: If True the rt layer is validated against the comp
        :return: CompLayer (the runtime layer that ran)
        """
        if not node_paths:
            logger.error("No node paths specified for execution")
            return
        self.about_to_execute.emit(True)
        self.setup_build(node_paths, rt_layer=rt_layer)
        self.resume_build()
        return rt_layer

    def _execute_node(self, node_path):
        t = ExecuteNodeThread(self, node_path)
        if self.is_standalone:
            self.processing.emit(True)
            t.start()
            while not t.isFinished():
                self.process_events()
            self.processing.emit(False)
        else:
            # DCCs aren't thread safe, we need to get attached working so we
            # can know we're in a thread safe environment.
            t._run()
            self.process_events()
        if t.raised_exception:
            if isinstance(t.raised_exception, InvalidNodeError):
                details = ("To resolve this try navigating to "
                           "'Execute > Clear cache'. \n\n"
                           "This error is raised when layers"
                           " are muted or nodes are deleted and then execute "
                           "is called without clearing the cache.")
                NxtWarningDialog.show_message(text='NXT attempted to execute '
                                                   'an invalid node!',
                                              info=str(t.raised_exception),
                                              details=details)
                raise BuildStop
            raise t.raised_exception

    def execute_stage(self, start=None):
        self.about_to_execute.emit(True)
        start_paths = self.get_start_nodes()
        if not start and start_paths:
            start = start_paths[0]
        if not start:
            logger.error('No start path given or found in the file!')
            return
        if not self.node_exists(start):
            logger.error("Cannot start at {}, doesn't exist".format(start))
            return
        node_paths = self.get_exec_order(start)
        self.execute_nodes(node_paths)

    def load_cache_dict(self, file_data):
        self._load_cache(file_data=file_data)

    def load_cache_file(self, filepath=None):
        if not filepath:
            filepath = self.cache_filepath
        self._load_cache(filepath=filepath)

    def _load_cache(self, file_data=None, filepath=None):
        """Attempt to load cache data from the file_data, if none is provided
        we attempt to load data from file at self.cache_filepath.
        :param file_data: Optional save data dict
        :return: True if cache data was loaded
        """
        if not file_data and not filepath:
            logger.error('Must provide a cache dict or filepath to load!')
        logger.debug('Loading cache layer...')
        if not self.current_rt_layer:
            self.current_rt_layer = nxt_layer.CompLayer()
        if not file_data:
            fp = filepath
            try:
                cache = nxt_layer.CacheLayer.load_from_filepath(fp)
            except Exception as e:
                logger.exception('Failed to load cache file: "{}"'.format(fp))
                return
        else:
            try:
                cache = nxt_layer.CacheLayer.load_from_layer_data(file_data)
            except Exception as e:
                logger.exception('Failed to load cache data!')
                return
        logger.debug('Loaded cache layer!')
        self.current_rt_layer.cache_layer = cache
        self.data_state_changed.emit(True)
        return True

    def refresh_exec_framing_from_pref(self):
        pref_key = user_dir.USER_PREF.EXEC_FRAMING
        pref_val = user_dir.user_prefs.get(pref_key)
        if pref_val is not None:
            self.framing_behavior = pref_val

    def is_build_setup(self):
        order = self.current_build_order is not None
        rt_layer = self.current_rt_layer is not None or self.use_cmd_port
        idx = self.last_built_idx is not None
        return all([order, rt_layer, idx])

    def can_build_run(self):
        if not self.is_build_setup():
            return False
        next_idx = self.last_built_idx + 1
        try:
            self.current_build_order[next_idx]
        except IndexError:
            return False
        return True

    def setup_build(self, node_paths, rt_layer=None):
        # Reset once_sec_timer vars
        self.build_start_time = time.time()
        self.build_paused_time = .0
        self.last_step_time = .0

        self.current_build_order = node_paths
        self.build_changed.emit(node_paths)
        self.refresh_exec_framing_from_pref()
        if self.use_cmd_port:
            # TODO: Only run this if we actually have to
            self.update_remote_comp()
            self.current_rt_layer = self.comp_layer
        elif rt_layer:
            self.current_rt_layer = rt_layer
        else:
            rt_build = self.stage.build_stage(self.comp_layer.layer_idx())
            try:
                self.current_rt_layer = self.stage.setup_runtime_layer(rt_build)
            except GraphError as err:
                logger.error("World node failed, cannot execute.\n" + str(err),
                             links=[nxt_path.WORLD])
                self.finish_build()
                return
        self.last_built_idx = -1
        self.last_hit_break = None
        self._set_executing(True)
        self._set_build_paused(True, focus=False)

    def get_build_focus(self):
        """Build "focus" is the currently running node.

        :return: node path currently running, if running.
        :rtype: str
        """
        if not self.can_build_run():
            return ''
        return self.current_build_order[self.last_built_idx]

    @property
    def last_built_idx(self):
        return self._last_built_idx

    @last_built_idx.setter
    def last_built_idx(self, val):
        if val != self._last_built_idx:
            changed = True
        else:
            changed = False
        self._last_built_idx = val
        if changed:
            self.build_idx_changed.emit(val)

    def step_build(self):
        # Handle any offsets
        if self.last_step_time:
            step_delta = self.last_step_time - time.time()
            self.build_start_time -= step_delta
        if self.build_paused_time:
            pause_delta = self.build_paused_time - time.time()
            self.build_start_time -= pause_delta
        # Always reset the paused time as a build step is the same as paused
        # in regard to the build once_sec_timer
        self.build_paused_time = .0
        if not self.can_build_run():
            logger.error("Cannot step execution. Build is not ready.")
            return
        self.last_built_idx += 1
        next_node = self.current_build_order[self.last_built_idx]
        try:
            self._execute_node(next_node)
        except BuildStop:
            self.finish_build()
            return
        if not self.can_build_run():
            self.finish_build()
            return
        next_node = self.get_build_focus()
        if self.framing_behavior == EXEC_FRAMING.STEPPING:
            self.frame_items.emit([next_node])
        self.data_state_changed.emit(True)
        self.last_step_time = time.time()
        if self._use_cmd_port:
            self.get_remote_cache()

    def resume_build(self):
        if not self.can_build_run():
            logger.error("Cannot resume build.")
            return
        # Handle any offsets
        if self.build_paused_time:
            pause_delta = self.build_paused_time - time.time()
            self.build_start_time -= pause_delta
        if self.last_step_time:
            step_delta = self.last_step_time - time.time()
            self.build_start_time -= step_delta
        # Reset offset vars as we just subtracted them from the total time
        self.build_paused_time = .0
        self.last_step_time = .0
        start = self.last_built_idx+1
        stop = len(self.current_build_order)

        breaks = user_dir.breakpoints.get(self.top_layer.real_path, [])[:]
        skips = user_dir.skippoints.get(self.top_layer.real_path, [])[:]
        first_path = self.current_build_order[start]
        skip_pref_key = user_dir.USER_PREF.SKIP_INITIAL_BREAK
        skip_first_break = user_dir.user_prefs.get(skip_pref_key, True)
        if skip_first_break and first_path in breaks:
            logger.info("Ignoring breakpoint on first node " + first_path,
                        links=[first_path])
            breaks.remove(first_path)
        if self.last_hit_break is not None:
            if self.last_hit_break in breaks:
                breaks.remove(self.last_hit_break)
        self._set_build_paused(False)
        for i in range(start, stop):
            node_path = self.current_build_order[i]
            # Skips before breaks, that's the current flow.
            # This assumption is in 2 places, here and in
            # NodeExecutionPlug, where it draws skips instead of breaks
            if node_path in skips:
                self.last_built_idx = i
                skip_msg = "Skippoint triggers skip of {}".format(node_path)
                logger.execinfo(skip_msg, links=[node_path])
                continue
            if node_path in breaks:
                break_msg = " !! Breakpoint hit at: {}".format(node_path)
                logger.execinfo(break_msg, links=[node_path])
                self.last_hit_break = node_path
                self.frame_items.emit([node_path])
                self._set_build_paused(True)
                return
            self.last_built_idx = i
            try:
                self._execute_node(node_path)
            except BuildStop:
                logger.execinfo("Stopping execution loop.")
                self.finish_build()
                return
            if self._build_should_pause:
                logger.execinfo("Pausing execution loop.")
                self._set_build_paused(True)
                return
        self.finish_build()

    @property
    def build_paused(self):
        return self._build_paused

    def pause_build(self):
        if not self.executing:
            return
        if not self.build_paused:
            self._build_should_pause = True

    def _set_build_paused(self, paused, focus=True):
        self.last_step_time = .0
        if paused:
            self._build_should_pause = False
        if self._build_paused is paused:
            return
        self._build_paused = paused
        self.build_paused_changed.emit(paused)
        if paused and focus:
            curr_focus = self.get_build_focus()
            if curr_focus:
                self.frame_items.emit([curr_focus])
        if self._use_cmd_port:
            if paused:
                self.get_remote_cache()
            self.suspend_remote_visual_refreshes(suspend=not paused)

        # Mark the time we paused at so we can subtract its delta from the
        # total build time
        self.build_paused_time = time.time()

    @property
    def executing(self):
        return self._executing

    def stop_build(self):
        if not self.executing:
            return
        if self.build_paused:
            self.finish_build()
        else:
            self._build_should_stop = True

    def _set_executing(self, executing):
        if not executing:
            self._build_should_stop = False
        if self._executing == executing:
            return
        self._executing = executing
        self.executing_changed.emit(self._executing)

    def finish_build(self, verbose=True):
        build_seconds = round(time.time() - self.build_start_time)
        if verbose:
            logger.execinfo("Build exec time: "
                            "{} second(s).".format(build_seconds))
        self.last_built_idx = None
        self.last_hit_break = None
        self.current_build_order = None
        self.build_changed.emit([])
        self._set_build_paused(False)
        self._set_executing(False)
        self.data_state_changed.emit(True)
        if self._use_cmd_port:
            self.get_remote_cache()
            self.suspend_remote_visual_refreshes(False)

    def suspend_remote_visual_refreshes(self, suspend=True):
        """Tell the remote to suspend visual updates.
        Currently only supports Maya!
        """
        self._send_cmd('cmds.refresh(suspend={})'.format(suspend))
        if suspend is False:
            self._send_cmd('cmds.refresh()')

    def get_remote_cache(self):
        """Tells the remote client to send its cache data over the socket.
        If successful self.load_cache() will be called via the com port
        listener thread.
        :return: None
        """
        cmd = '{MODEL}.get_cache()'.format(MODEL=nxt_socket.MODEL_VAR)
        self._send_cmd(cmd, wait=True)

    def clear_cache(self):
        self.finish_build()
        self.current_rt_layer = None
        self.data_state_changed.emit(True)

    def get_unsaved_changes(self, layers=(), deep_check=False):
        self.processing.emit(True)
        layers = layers or self.stage._sub_layers
        unsaved_layers = []
        if deep_check:
            for layer in layers:
                logger.info("Checking for unsaved "
                            "changes in: \"{}\"".format(layer.real_path))
                if not os.path.isfile(str(layer.real_path)):
                    world_node = layer.lookup(nxt_path.WORLD)
                    other_nodes = layer.descendants()
                    alias = layer.get_alias(local=True)
                    refs = layer.get_references()
                    if (alias == nxt_layer.UNTITLED
                            and not world_node
                            and not other_nodes
                            and not refs):
                        # This is an empty untitled layer so don't worry about it
                        continue
                    unsaved_layers.add(layer)
                    continue
                # If the minor version number on disc is the same as the current
                # version we can disregard the bug fix number as it will not
                # effect the save file.
                live_data = layer.get_save_data()
                disc_data = nxt_io.load_file_data(layer.real_path)
                disc_data.pop(SAVE_KEY.FILEPATH)
                disc_data.pop(SAVE_KEY.REAL_PATH)
                disc_data.pop(SAVE_KEY.NAME)
                live_data = json.dumps(live_data, indent=4, sort_keys=True)
                disc_data = json.dumps(disc_data, indent=4, sort_keys=True)
                if live_data != disc_data:
                    unsaved_layers.add(layer)
        elif self.undo_stack.count():
            for layer_path in self.effected_layers:
                layer = self.lookup_layer(layer_path)
                if layer and layer not in unsaved_layers:
                    unsaved_layers.append(layer)
        self.processing.emit(False)
        return unsaved_layers

    @staticmethod
    def process_events():
        QtCore.QCoreApplication.processEvents()


class NxtUndoStack(QtWidgets.QUndoStack):

    def push(self, command):
        """Simple overload of push method, checks that the target layer of the given command's model is *not* locked.
        If the command does not have a model attr nothing is checked.

        :param command: Command to push to undo stack
        :type command: QUndoCommand
        :return: None
        """
        model = getattr(command, 'model', None)  # type: StageModel
        if model and model.target_layer.get_locked():
            logger.warning('The target layer is locked!')
            model.request_ding.emit()
            return
        super(NxtUndoStack, self).push(command)


class UnsavedLayerSet(set):

    def __init__(self):
        super(UnsavedLayerSet, self).__init__()
        self.signaler = StringSignaler()
        self.signal = self.signaler.signal

    def add(self, element):
        super(UnsavedLayerSet, self).add(element)
        self.signal.emit(element)

    def remove(self, element):
        super(UnsavedLayerSet, self).remove(element)
        self.signal.emit(element)


def compare_data(pre_data, post_data):
    """Compares two data stashes and returns the delta. If there is a new
    attr found on a node the delta dict will contain the following:
        {'node/path':
            {'NewAttr': [('attr_name', value)],
            'ChangedAttr': [],
            'NewNode': False}
    If an attr value changed the data will look like this:
        {'node/path':
                {'NewAttr': [],
                'ChangedAttr': [{'attr_name': (old_val, new_val)}],
                'NewNode': False}
    Lastly if the node is new the 'NewNode' key's value will be True
    :param pre_data:
    :param post_data:
    :return: Delta dict
    """
    changes = {}

    def get_changes_for_node(node_path):
        data_dict = changes.get(node_path, {'NewAttr': [], 'ChangedAttr': [],
                                            'NewNode': False})
        changes[node_path] = data_dict
        return data_dict
    # Loop pre-comp data looking for attr value changes
    for pre_path, pre_node_data in pre_data.items():
        # Check existing attrs for value changes
        try:
            new_pre_node_data = post_data[pre_path]
        except KeyError:
            new_pre_node_data = vars()
        if new_pre_node_data != pre_node_data:
            for attr, old_value in pre_node_data.items():
                try:
                    new_value = post_data[pre_path][attr]
                except KeyError:
                    new_value = object
                if new_value != old_value:
                    # Existing attr value changed
                    delta_dict = get_changes_for_node(pre_path)
                    delta_dict['ChangedAttr'] += [{attr: (old_value,
                                                          new_value)}]
    # Loop post-comp data looking for new attrs
    for post_path, post_node_data in post_data.items():
        # Check for attrs that are new
        if pre_data.get(post_path) is None:
            delta_dict = get_changes_for_node(post_path)
            delta_dict['NewNode'] = True
        for attr, new_value in post_node_data.items():
            try:
                _ = pre_data[post_path][attr]
                attr_not_found = False
            except KeyError:
                attr_not_found = True
            if attr_not_found:
                delta_dict = get_changes_for_node(post_path)
                delta_dict['NewAttr'] += [(attr, new_value)]
    return changes


class IPCWait(object):
    ANIMATION = ["\\", "--", "/", "|"]

    def __init__(self, model):
        """
        :param model: StageModel object
        """
        self.model = model

    def __enter__(self):
        self.model.processing.emit(True)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        logger.socket('Waiting on remote...')
        c = 0
        while self.model._wait_for_remote:
            self.model.process_events()
            sys.stdout.write('\rWaiting for remote  ' + self.ANIMATION[c % -4])
            sys.stdout.flush()
            c += 1
        sys.stdout.write('\r ')
        sys.stdout.flush()
        self.model.processing.emit(False)


class CompLayerStash:
    """Context manager that stashes the comp and target layers on enter and
    exit. On exit the four stashes (pre_comp, post_comp, pre_target,
    post_target) are compared and if there is a change we do something.
    """
    # This is taking approx 115ms x 2 (29-4-2020)
    def __init__(self, model, comp_layer=None, target_layer=None):
        """If not comp layer is provided the model's comp layer is used.
        If not target layer is provided the model's target layer is used.
        :param model: StageModel object
        :param comp_layer: CompLayer object or None
        :param target_layer: SpecLayer object or None
        """
        self.model = model
        self.stage = model.stage
        self.pre_comp_data = {}
        self.post_comp_data = {}
        self.pre_target_data = {}
        self.post_target_data = {}
        self.comp_layer = comp_layer or model.comp_layer
        self.target_layer = target_layer or model.target_layer
        self.delta = {'comp': {}, 'target': {}}

    def __enter__(self):
        """Stash the comp and target layer before any code is run.
        :return: self
        """
        self.pre_comp_data = self.stage.get_stash_data(self.comp_layer)
        self.pre_target_data = self.stage.get_stash_data(self.target_layer)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stash comp and target layer again and compare to the previous
        stashes. If there is a delta in the data we do something.
        :param exc_type: Uncaught exception type
        :param exc_val: Uncaught exception value
        :param exc_tb: Uncaught exception traceback
        :return: None
        """
        self.post_comp_data = self.stage.get_stash_data(self.comp_layer)
        self.post_target_data = self.stage.get_stash_data(self.target_layer)
        self.delta['target'] = compare_data(self.pre_target_data,
                                            self.post_target_data)
        _comp_changes = compare_data(self.pre_comp_data, self.post_comp_data)
        _keys = list(self.delta['target'].keys())
        for k, v in _comp_changes.items():
            if k not in _keys:
                self.delta['comp'][k] = v
        comp_change_count = len(self.delta['comp'].keys())
        tgt_change_count = len(self.delta['target'].keys())
        change_count = comp_change_count + tgt_change_count
        logger.info('Command changed {} node(s)'.format(change_count))
        if change_count:
            # Emit signal with delta data?
            pass


class BuildStop(Exception):
    pass


class CommandPortListener(QtCore.QThread):
    update_cache_dict = QtCore.Signal(dict)
    destroy_cmd_port = QtCore.Signal()

    def __init__(self, stage_model):
        super(CommandPortListener, self).__init__()
        self.stage_model = stage_model
        self.kill = False
        self.listening = False
        self.socket = None
        self.client = None
        self.waiting = False
        self.client_addr = None
        self.stage_model.destroyed.connect(self.stop)
        self.remote_prefix = '# '
        self.setup()
        self.bound = False
        self.connected = False

    def setup(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.setblocking(1)

    def bind(self):
        self.bound = False
        logger.socket('Binding COM port server to: '
                      '{}'.format(nxt_socket.COM_PORT))
        self.socket.bind(('localhost', nxt_socket.COM_PORT))
        self.bound = True

    def run(self):
        if not self.bound:
            self.bind()
        logger.socket('Starting COM thread...')
        try:
            self.socket.listen(1)
        except Exception as e:
            if e.errno == 9:  # Stale or uninitialized socket
                self.socket.close()
                self.setup()
                self.bind()
                self.socket.listen(1)
            else:
                raise e
        self.client, self.client_addr = self.socket.accept()
        logger.socket('Connected to by: {}'.format(self.client_addr))
        logger.socket('Remote messages will be prefixed with '
                      '{}'.format(self.remote_prefix))
        self.connected = True
        self.stage_model.validate_socket_connection()
        new_msg = True
        full_msg = b''
        HEADER = nxt_socket.HEADER_SIZE
        while not self.kill:
            self.listening = True
            try:
                msg = self.client.recv(1024)
            except:
                logger.socket('COM server lost connection!')
                self.client.close()
                self.client = None
                self.connected = False
                logger.socket('Closed connection from: '
                              '{}'.format(self.client_addr))
                break
            if new_msg:
                _msg_header = msg[:nxt_socket.HEADER_SIZE]
                if not _msg_header:
                    full_msg = b''
                    continue
                msg_len = int(_msg_header)
                new_msg = False
            full_msg += msg.decode('utf-8')
            recv_len = len(full_msg) - HEADER
            if recv_len < msg_len:
                continue
            elif recv_len > msg_len:
                # Sender was too fast so we split out the next message
                base_chunk = full_msg
                _base_chunk_header = base_chunk[:HEADER]
                if not base_chunk:
                    full_msg = b''
                    continue
                next_expected = int(_base_chunk_header)
                chunk = base_chunk
                chunk_len = len(chunk)
                while chunk_len > next_expected:
                    message_bytes = chunk[HEADER:next_expected + HEADER]
                    actual_chunk_len = len(message_bytes)
                    if actual_chunk_len < next_expected:
                        chunk_len = actual_chunk_len
                        break
                    if actual_chunk_len != next_expected:
                        raise Exception('Failed to parse incoming bytes!')
                    self.handle_message(message_bytes)
                    c = chunk[next_expected + HEADER:]
                    chunk_len = len(c)
                    _chunk_header = c[:HEADER]
                    if not _chunk_header or not c:
                        full_msg = b''
                        next_expected = 0
                        chunk = c
                        break
                    next_expected = int(_chunk_header)
                    chunk = c
                if chunk_len == next_expected:
                    new_msg = True
                    data_bytes = chunk[HEADER:]
                    full_msg = b''
                    if not data_bytes:
                        continue
                    if not self.handle_message(data_bytes):
                        break
                elif chunk_len < next_expected:
                    msg_len = next_expected
                    continue
            elif recv_len == msg_len:
                new_msg = True
                data_bytes = full_msg[HEADER:]
                full_msg = b''
                if not data_bytes:
                    continue
                if not self.handle_message(data_bytes):
                    break
        self.listening = False
        self.connected = False
        self.bound = False
        if self.client:
            self.client.close()
        logger.info('Shutdown com port listener!')

    def handle_message(self, message_bytes):
        data_dict = pickle.loads(message_bytes)
        for k, v in data_dict.items():
            if k == nxt_socket.COM_TYPE.SHUTDOWN:
                logger.socket('Shutting down com port listener...')
                self.socket.settimeout(5)
                self.client.close()
                self.client = None
                self.destroy_cmd_port.emit()
                logger.socket('Closed connection from: '
                              '{}'.format(self.client_addr))
                return False
            elif k == nxt_socket.COM_TYPE.PING:
                print('Ping')
                logger.debug('Ping')
            elif k == nxt_socket.COM_TYPE.LOG:
                lvl, msg, links = v
                logger.log(lvl, self.remote_prefix + msg,
                           extra={'links': links})
            elif k == nxt_socket.COM_TYPE.CACHE:
                self.update_cache_dict.emit(v)
            elif k == nxt_socket.COM_TYPE.ERR:
                self.stage_model._wait_for_remote = False
                self.stage_model.stop_build()
            elif k == nxt_socket.COM_TYPE.WAIT:
                self.stage_model._wait_for_remote = v
                self.client.send(b'1')
        return True

    def stop(self):
        self.kill = True
        self.bound = False
        if self.client:
            self.client.close()


class ExecuteNodeThread(QtCore.QThread):
    def __init__(self, stage_mode, node_path):
        super(ExecuteNodeThread, self).__init__()
        self.stage_model = stage_mode
        self.node_path = node_path
        # Linux won't raise exceptions in threads so this is how we catch it
        # and let the model raise it in the main thread.
        self.raised_exception = None

    def run(self):
        self._run()

    def _run(self):
        if self.stage_model.framing_behavior == EXEC_FRAMING.ALWAYS:
            self.stage_model.frame_items.emit([self.node_path])
        if self.stage_model.use_cmd_port:  # Send run command over cmd port
            cmd = '{MODEL}.run(exec_order=["{NODE}"])'
            cmd = cmd.format(NODE=self.node_path, MODEL=nxt_socket.MODEL_VAR)
            self.stage_model._send_cmd(cmd, wait=True)
        else:
            try:
                layer = self.stage_model.current_rt_layer
                exec_ = self.stage_model.stage.execute_nodes
                self.stage_model.current_rt_layer = exec_([self.node_path],
                                                          layer)
            except GraphError as err:
                logger.grapherror(str(err), links=[self.node_path])
                if isinstance(err, InvalidNodeError):
                    self.raised_exception = err
                else:
                    self.raised_exception = BuildStop
                return
            except ExitGraph:
                self.raised_exception = BuildStop
                return
        if self.stage_model._build_should_stop:
            self.raised_exception = BuildStop
