# Built-in
import os
import json
import traceback
import math
import socket
import pickle
import inspect
import sys
import time

# External
from Qt import QtWidgets
from Qt import QtCore
from Qt import QtGui

# Internal
from nxt import clean_json, nxt_io
from nxt_editor.commands import *
from nxt_editor.dialogs import NxtFileDialog
from nxt.constants import API_VERSION, is_standalone
from nxt import (nxt_path, nxt_layer, tokens, DATA_STATE,
                 NODE_ERRORS, GRID_SIZE)
import nxt_editor
from nxt_editor import DIRECTIONS, StringSignaler, color_range, theme, user_dir
from nxt_editor import backdrops
from nxt_editor import bookmarks
from nxt_editor import wires
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
#: Set to 1 to composite the graph again for each run, as the editor once
#: did, rather than run in a copy of the comp it shows.
RECOMP_ENV_VAR = 'NXT_EXEC_RECOMP'
#: How long after an edit leaves the comp stale it is built again, when
#: that is quick enough not to be noticed, in ms and seconds.
STALE_COMP_MS = 600
QUICK_COMP_SECONDS = 0.25
#: Set to 1 to check each run's copy against a fresh comp of the graph.
#: Where they differ the run is in the fresh comp, and what differs is
#: logged.
CHECK_COMP_ENV_VAR = 'NXT_EXEC_CHECK_COMP'


class EXEC_FRAMING:
    NEVER = 0
    STEPPING = 1
    ALWAYS = 2


#: The types a value has when its text reads back as itself, which is what
#: determine_nxt_type names. Anything else it calls raw.
LITERAL_TYPES = (bool, int, float, complex, list, tuple, dict, set,
                 type(None))


def cached_type_name(value):
    """The type of a cached value, named as determine_nxt_type names the
    type of the same value written out, without writing it out.

    :rtype: str
    """
    if isinstance(value, LITERAL_TYPES):
        return type(value).__name__
    return 'raw'


class StageModel(QtCore.QObject):
    destroy_cmd_port = QtCore.Signal()
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
    # Which layers are hidden in the graph changed. Nothing about the graph
    # itself did.
    layer_visibility_changed = QtCore.Signal()
    # A short message about something the editor did by itself, for the
    # graph to show.
    status_message = QtCore.Signal(str)
    layer_removed = QtCore.Signal(str)  # Layer path who was removed
    layer_added = QtCore.Signal(str)  # Layer path who was added
    # Which layers are loaded, or the order they stack in, changed.
    # Order decides whose opinion wins, so a reorder is a change
    # even though the same layers are loaded.
    layers_restacked = QtCore.Signal()
    layer_saved = QtCore.Signal(str)  # Layer path that was just saved
    nodes_changed = QtCore.Signal(tuple)
    attrs_changed = QtCore.Signal(tuple)
    node_added = QtCore.Signal(str)
    node_deleted = QtCore.Signal(str)
    node_moved = QtCore.Signal(str, list)
    # Where a root node's graphic is whenever it moves, which includes
    # every step of a drag, before the move is set on a layer when the
    # mouse is let go. Nothing goes on the undo stack for these.
    node_graphic_moved = QtCore.Signal(str, list)
    selection_changed = QtCore.Signal(tuple)  # new selection
    node_focus_changed = QtCore.Signal(str)
    node_name_changed = QtCore.Signal(str, str)  # old node path, new node path
    node_parent_changed = QtCore.Signal(str, str)  # old node path, new node path
    starts_changed = QtCore.Signal(tuple)  # new start point paths
    breaks_changed = QtCore.Signal(tuple)  # new break point paths
    skips_changed = QtCore.Signal(tuple)  # new skip point paths
    collapse_changed = QtCore.Signal(tuple)  # node paths where changed
    backdrops_changed = QtCore.Signal()
    wires_changed = QtCore.Signal()  # line style or points
    bookmarks_changed = QtCore.Signal()
    frame_items = QtCore.Signal(tuple)
    server_log = QtCore.Signal(str)
    request_ding = QtCore.Signal()
    # A node raised an error and the build stopped there. The node's path.
    build_failed = QtCore.Signal(str)

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
        # True while a node is running. Stepping runs a node with the
        # build paused, so paused alone does not mean nothing is running.
        self._running_node = False
        self._last_built_idx = None
        self.current_rt_layer = None
        self.framing_behavior = EXEC_FRAMING.STEPPING
        self.last_hit_break = None
        self.refresh_exec_framing_from_pref()
        # model states
        self._data_state = DATA_STATE.RESOLVED
        # Each tab has its own, starting from whatever was last chosen.
        self._implicit_connections = user_dir.user_prefs.get(
            user_dir.USER_PREF.SHOW_IMPLICIT, True)
        # graph layers
        # Compositing is the expensive part of opening a graph, and a graph
        # sitting in a tab nobody has selected has nobody to show it to. The
        # comp is built the first time something asks for it instead, see
        # the comp_layer property.
        self._comp_layer = None
        self._comp_generation = 0
        # Whether the comp is the same as a fresh comp of the graph, see
        # comp_is_exact.
        self._comp_exact = False
        self._comp_builds = 0
        self._comp_patches = 0
        self._drawn_layers = None
        self._drawn_specs = None
        # How long the last comp took, see refresh_stale_comp.
        self._comp_seconds = None
        # A fresh comp made for a run, to show once the run is done, see
        # new_runtime_layer.
        self._fresh_comp = None
        self.stale_comp_timer = QtCore.QTimer(self)
        self.stale_comp_timer.setSingleShot(True)
        self.stale_comp_timer.setInterval(STALE_COMP_MS)
        self.stale_comp_timer.timeout.connect(self.refresh_stale_comp)
        self.nodes_changed.connect(self.mark_comp_patched)
        self.attrs_changed.connect(self.mark_comp_patched)
        self._target_layer = stage.top_layer
        self._display_layer = stage.top_layer
        # selection
        self._selection = []
        self._node_focus = None
        self.selection_changed.connect(self.update_node_focus)
        # Break and skip points of a graph not saved yet, which has no file
        # to keep them by in the user's prefs. {'breaks': {None: [paths]}}
        self._unsaved_points = {'breaks': {}, 'skips': {}}
        self.layer_saved.connect(self._keep_unsaved_points)
        # Layers hidden in the graph, read from the cache by the graph's
        # file when first asked for. See hidden_layer_paths.
        self._hidden_layers = None
        self._hidden_graph = None
        self.layer_removed.connect(self._forget_unloaded_hidden_layers)
        self.layers_restacked.connect(self._forget_unloaded_hidden_layers)
        self.layer_saved.connect(self._check_hidden_graph)
        # When and how big each layer's file was when it was last read or
        # written here, {real_path: (mtime, size)}. A file that no longer
        # matches was changed by something else, a version control update
        # most often, and saving would write over that without a word.
        self.disk_stamps = {}
        for layer in stage._sub_layers:
            self.stamp_layer_file(layer.real_path)
        self.layer_saved.connect(self.stamp_layer_file)
        self.layer_added.connect(self._stamp_new_layer_file)
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
        """The composited graph, built the first time it is asked for.

        Opening a file no longer pays for a comp nothing has looked at yet.
        Whatever needs the graph first -- usually its tab being selected --
        pays for it, and everything after that gets the same one back until
        an edit replaces it.
        """
        if self._comp_layer is None:
            self._comp_layer = self.build_comp(
                self._display_layer.layer_idx())
            self._comp_generation += 1
            self.comp_built()
        return self._comp_layer

    def build_comp(self, from_idx):
        """A new comp of the layers from from_idx, timed."""
        start = time.time()
        comp = self.stage.build_stage(from_idx=from_idx)
        self._comp_seconds = time.time() - start
        return comp

    @property
    def comp_is_exact(self):
        """Whether the comp is the same as a fresh comp of the graph.

        It is right after it is built. Most edits change it in place, and
        some of those leave a node that inherits from the edited one as it
        was, so after one it is no longer counted on. A run copies the comp
        only while it is exact, see new_runtime_layer.
        """
        return self._comp_exact

    def comp_built(self):
        """The comp was just built from the layers."""
        self._comp_exact = True
        self._comp_builds += 1
        self._drawn_layers = self.layers_as_drawn()
        self._drawn_specs = self.specs_as_drawn()

    def specs_as_drawn(self):
        """The values of every node of the layers, as the comp was built
        from them. An edit can change a layer's node and build the comp
        again, and the old comp and the new inherit from that same node, so
        only this says it changed."""
        specs = {}
        comp = self._comp_layer
        if comp is None:
            return specs
        for table in comp._sublayer_node_tables:
            for _path, node in table:
                specs[node] = {k: (list(v) if type(v) is list else v)
                               for k, v in node.__dict__.items()}
        return specs

    def layers_as_drawn(self):
        """What of the layers, beyond their nodes, every node is drawn
        with: which there are, in order, and their colors, mute and solo.
        """
        layers = []
        for layer in self.stage._sub_layers:
            layers.append((layer.real_path, layer.get_alias(),
                           layer.get_muted(), layer.get_soloed(),
                           self.get_layer_color(layer)))
        return tuple(layers)

    def changed_since(self, old, old_layers, new, old_specs=None):
        """The nodes to draw again for the comp new, built in place of old.

        Drawing every node again, for a graph of thousands, took longer
        than anything else in the edit. Few change in a new comp of the
        same layers, so only those are drawn again: see
        nxt_layer.changed_nodes. When the layers themselves changed, or
        there is nothing to compare, every node is.

        :return: dirty node paths, or () for every node
        :rtype: list | tuple
        """
        changed_nodes = getattr(nxt_layer, 'changed_nodes', None)
        if (old is None or changed_nodes is None or
                old_layers != self.layers_as_drawn()):
            return ()
        try:
            dirty = set(changed_nodes(old, new))
        except Exception:
            logger.debug('Drawing every node again', exc_info=True)
            return ()
        edited = set()
        for spec, values in (old_specs or {}).items():
            if values != dict(spec.__dict__):
                edited.add(spec)
        if edited:
            for path, node in new._nodes_path_as_key.items():
                if not edited.isdisjoint(node.__mro__):
                    dirty.add(path)
        for name in ('positions', 'collapse'):
            before = getattr(old, name, {}) or {}
            after = getattr(new, name, {}) or {}
            for path in set(before) | set(after):
                if before.get(path) != after.get(path):
                    dirty.add(path)
        # Nothing to draw again, but something to say: the world is never
        # drawn.
        return list(dirty) or [nxt_path.WORLD]

    def mark_comp_patched(self, *_args):
        """The comp was changed in place, see comp_is_exact."""
        self._comp_exact = False
        self._comp_patches += 1
        if (self._comp_seconds is not None and
                self._comp_seconds < QUICK_COMP_SECONDS):
            self.stale_comp_timer.start()

    def refresh_stale_comp(self):
        """Build the comp again, when an edit changed it in place and that
        is quick: what the graph shows is then what the layers say, a node
        inheriting from the edited one too, and the next run can copy it.
        A graph that takes longer is built again by its next run, see
        new_runtime_layer."""
        if self._comp_exact or self._comp_layer is None or self.executing:
            return
        self.update_comp_layer(rebuild=True)

    def comp_of_every_layer(self):
        """The comp, to give to a stage call that would otherwise build one
        of every layer, when it is that and exact: see
        Stage.parent_nodes.

        :return: keyword arguments for the call
        :rtype: dict
        """
        comp = self._comp_layer
        if (comp is None or not self._comp_exact or comp.layer_idx() != 0 or
                not _takes_comp(self.stage.parent_nodes)):
            return {}
        return {'comp_layer': comp}

    def comp_stamp(self):
        """Says which comp the graph has: it is different after any
        change."""
        return (self._comp_builds, self._comp_patches)

    def show_fresh_comp(self):
        """Show the fresh comp the last run was copied from, as the comp
        shown changed in place before it was made. Not if the graph has
        changed since."""
        fresh = self._fresh_comp
        self._fresh_comp = None
        if fresh is None or self.executing:
            return
        comp, stamp = fresh
        if stamp != self.comp_stamp() or self._comp_exact:
            return
        self.processing.emit(True)
        old = self._comp_layer
        self._comp_layer = comp
        dirty = self.changed_since(old, self._drawn_layers, comp,
                                   self._drawn_specs)
        self._comp_generation += 1
        self.comp_layer_changed.emit(dirty)
        self.comp_built()
        self.processing.emit(False)

    @property
    def comp_is_built(self):
        """Whether a comp exists, without building one to find out."""
        return self._comp_layer is not None

    @property
    def comp_generation(self):
        """Counter that ticks every time the comp changes.

        Anything that derives work from the comp can remember this number
        and tell, without comparing graphs, whether what it cached still
        stands. Switching back to a tab nobody has touched then costs a
        comparison rather than a rebuild.
        """
        return self._comp_generation

    @property
    def display_layer(self):
        return self._display_layer

    def set_display_layer(self, layer):
        self.processing.emit(True)
        idx = layer.layer_idx()
        comp_layer = self.stage.build_stage(from_idx=idx)
        self._display_layer = layer
        self.set_comp_layer(comp_layer, rebuild=False)
        self.comp_built()
        self.disp_layer_changed.emit(self.get_layer_path(layer))
        self.processing.emit(False)

    def set_comp_layer(self, layer, rebuild=True, dirty=()):
        self.processing.emit(True)
        if rebuild:
            idx = layer.layer_idx()
            old = self._comp_layer
            old_layers = self._drawn_layers
            old_specs = self._drawn_specs
            comp_layer = self.build_comp(idx)
            self._comp_layer = comp_layer
            if not dirty:
                dirty = self.changed_since(old, old_layers, comp_layer,
                                           old_specs)
        else:
            self._comp_layer = layer
        safe_selection = []
        for node_path in self.selection:
            if self.comp_layer.lookup(node_path):
                safe_selection += [node_path]
        self.selection = safe_selection
        self._comp_generation += 1
        self.comp_layer_changed.emit(dirty)
        if rebuild:
            self.comp_built()
        else:
            self.mark_comp_patched()
        self.processing.emit(False)

    def update_comp_layer(self, rebuild=False, dirty=()):
        self.set_comp_layer(self.comp_layer, rebuild, dirty)

    def announce_comp_changed(self, dirty=()):
        """Say the comp changed without building a new one.

        The stage keeps the comp's nodes right as it edits them, so there
        is nothing to rebuild; what is missing is anyone being told. The
        build view and the workflow tools listen for the comp changing
        rather than for nodes changing, so without this they carry on
        describing a graph that has moved on.
        """
        if self._comp_layer is None:
            # Nothing has looked at this graph yet, so there is nothing
            # showing it that could have gone stale.
            return
        self.set_comp_layer(self._comp_layer, rebuild=False, dirty=dirty)

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
        if color is not None:
            # Exactly the color chosen; how it is shown is each user's view.
            chosen = QtGui.QColor(color)
            if chosen.isValid():
                color = chosen.name()
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

    def get_layer_references(self, layer_path):
        """The references a layer holds, as stored.

        Partial paths stay partial: what is stored is what resolves
        through the file roots later, and rewriting them as absolute would
        pin the graph to one machine.

        :param layer_path: real path of the layer
        :type layer_path: str
        :rtype: list
        """
        layer = self.lookup_layer(layer_path)
        return list(layer.get_references()) if layer else []

    def get_editable_reference_layers(self):
        """The layers whose references this session may edit.

        The top layer, and any layer open below it. Editing a layer's
        references rewrites that layer's file, so a layer that is not
        open, or is locked, is not ours to change.

        :return: layers, top first
        :rtype: list
        """
        editable = []
        for layer in self.stage._sub_layers:
            if self.get_layer_locked(layer.real_path):
                continue
            editable += [layer]
        return editable

    def set_layer_references(self, layer_path, references):
        """Replace the references a layer holds.

        :param layer_path: real path of the layer to edit
        :type layer_path: str
        :param references: references in order, as they are to be stored
        :type references: list
        :return: whether anything changed
        :rtype: bool
        """
        layer = self.lookup_layer(layer_path)
        if layer is None:
            logger.error('No layer at {}'.format(layer_path))
            return False
        if self.get_layer_locked(layer_path):
            logger.warning('{} is locked'.format(layer.alias))
            self.request_ding.emit()
            return False
        cmd = SetLayerReferences(layer_path, references, self)
        if not cmd.changed():
            return False
        self.undo_stack.push(cmd)
        return True

    def get_reference_dependencies(self, layer):
        """A layer and everything it pulls in, as deep as it goes.

        What a layer contributes to the graph is its own file plus every
        file it references, so this is the list of files behind it.

        :param layer: layer to start from
        :return: the layer first, then its references depth first
        :rtype: list
        """
        if layer is None:
            return []
        return self.stage.reference_dependencies(layer)

    def reload_layers(self, layer_paths):
        """Re-read layers from disk and composite the graph again.

        Unsaved work on these layers is thrown away, which is what
        reloading means; asking about that belongs to whoever offers it.
        It goes on the undo stack all the same, and undoing puts back
        what was in memory rather than reading the file a second time.

        :param layer_paths: real paths of the layers to reload
        :type layer_paths: list
        :return: whether a reload was asked for
        :rtype: bool
        """
        layer_paths = [p for p in layer_paths if self.lookup_layer(p)]
        if not layer_paths:
            return False
        self.undo_stack.push(ReloadLayers(layer_paths, self))
        return True

    def missing_references(self):
        """The references that did not load, by the loaded layer holding
        them. A file that could not be found or opened is kept as a
        reference with no layer behind it.

        :return: [(layer, [reference as stored, ...]), ...] in stack order,
            each file once however many times it is loaded
        :rtype: list
        """
        missing = []
        seen = set()
        for layer in self.stage._sub_layers:
            if layer.real_path in seen:
                continue
            seen.add(layer.real_path)
            references = [data.get(SAVE_KEY.FILEPATH)
                          for data in layer.sub_layers
                          if data.get('layer') is None]
            if references:
                missing.append((layer, references))
        return missing

    @staticmethod
    def read_disk_stamp(layer_path):
        """When and how big the file at layer_path is now, None when
        there is no file.

        :rtype: tuple or None
        """
        if not layer_path:
            return None
        try:
            info = os.stat(layer_path)
        except OSError:
            return None
        return info.st_mtime, info.st_size

    def stamp_layer_file(self, layer_path):
        """Note the file as it is now, as what this graph last read or
        wrote. Called once a layer is loaded, saved or reloaded.
        """
        stamp = self.read_disk_stamp(layer_path)
        if stamp is None:
            self.disk_stamps.pop(layer_path, None)
        else:
            self.disk_stamps[layer_path] = stamp

    def _stamp_new_layer_file(self, layer_path):
        # A layer referenced after the graph was opened is read as it is
        # added. A file already noted keeps its stamp: another copy of it
        # in the stack does not mean it was read again.
        if layer_path not in self.disk_stamps:
            self.stamp_layer_file(layer_path)

    def layer_file_changed_on_disk(self, layer_path):
        """Whether something else has written the layer's file since this
        graph last read or wrote it. A file that has gone away is not
        counted, saving puts it back.

        :rtype: bool
        """
        known = self.disk_stamps.get(layer_path)
        if known is None:
            return False
        now = self.read_disk_stamp(layer_path)
        return now is not None and now != known

    def layer_files_changed_on_disk(self):
        """The real paths of the loaded layers whose files have changed on
        disk, each once, in stack order. A stat of each file, cheap enough
        to ask whenever the window comes back to the front.

        :rtype: list
        """
        changed = []
        for layer in self.stage._sub_layers:
            path = layer.real_path
            if path in changed:
                continue
            if self.layer_file_changed_on_disk(path):
                changed.append(path)
        return changed

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
        # Shown as the user views layer colors, see color_range. A color
        # saved before colors were kept to ones white text reads on, or set
        # from a script, is shown as the nearest one in that.
        return color_range.shown(color).name()

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

    # -- hiding a layer's nodes ------------------------------------------
    # A view of the graph, like the layer color view: it is kept per user
    # and per graph in the editor's cache, never in the layer, so it does
    # not mark anything unsaved and is not somebody else's view too. A
    # hidden layer still comps, still runs, and is still in the Outliner.

    def hidden_layer_paths(self):
        """Real paths of the layers hidden in the graph. Only ever loaded
        layers: one taken out of the graph is forgotten, see
        _forget_unloaded_hidden_layers.

        :rtype: set
        """
        graph = self.top_layer.real_path
        if self._hidden_layers is None:
            self._hidden_layers = set(self._stored_hidden_layers(graph))
        elif graph != self._hidden_graph:
            self._move_hidden_layers(self._hidden_graph, graph)
        self._hidden_graph = graph
        return self._hidden_layers

    @staticmethod
    def _stored_hidden_layers(graph):
        stored = user_dir.editor_cache.get(
            user_dir.EDITOR_CACHE.HIDDEN_LAYERS) or {}
        return stored.get(graph, ())

    def _move_hidden_layers(self, old_graph, graph):
        """The graph was saved to a new file. What is remembered for that
        file is read, if there is anything, and otherwise what was hidden
        stays hidden and is remembered for it from now on."""
        stored = self._stored_hidden_layers(graph)
        if stored:
            self._hidden_layers = set(stored)
            return
        if old_graph in self._hidden_layers:
            # The top layer is the file that moved.
            self._hidden_layers.discard(old_graph)
            self._hidden_layers.add(graph)
        self._store_hidden_layers(graph, hide=self._hidden_layers)

    @staticmethod
    def _store_hidden_layers(graph, hide=(), show=()):
        """Change what is remembered for a graph by the paths that changed.

        Read again first: another tab on the same graph has hidden layers
        of its own, and writing this one's whole set would undo what that
        one did.
        """
        if not graph:
            # A graph that was never saved has nowhere to be remembered by.
            return
        key = user_dir.EDITOR_CACHE.HIDDEN_LAYERS
        stored = dict(user_dir.editor_cache.get(key) or {})
        paths = (set(stored.get(graph, ())) | set(hide)) - set(show)
        if paths:
            stored[graph] = sorted(paths)
        else:
            stored.pop(graph, None)
        user_dir.editor_cache[key] = stored

    def _forget_unloaded_hidden_layers(self, *args):
        """Forget hidden layers that are no longer loaded, such as a
        reference that was removed. Nothing in the Layer Manager could
        show one again."""
        if self._hidden_layers is None:
            return
        loaded = {layer.real_path for layer in self.stage._sub_layers}
        gone = self._hidden_layers - loaded
        if not gone:
            return
        self._hidden_layers -= gone
        self._store_hidden_layers(self._hidden_graph, show=gone)
        self.layer_visibility_changed.emit()

    def _check_hidden_graph(self, *args):
        """After a save, which can be to a new file. See
        _move_hidden_layers."""
        if self._hidden_layers is None:
            return
        before = set(self._hidden_layers)
        if self.hidden_layer_paths() != before:
            self.layer_visibility_changed.emit()

    def get_layer_hidden(self, layer_path):
        """Whether a layer's own nodes are hidden in the graph.

        :param layer_path: layer real path
        :type layer_path: str
        :rtype: bool
        """
        return layer_path in self.hidden_layer_paths()

    def set_layer_hidden(self, layer_path, hidden=True):
        """Hide, or show again, the nodes only this layer has.

        :param layer_path: layer real path
        :type layer_path: str
        :param hidden: True to hide
        :type hidden: bool
        """
        paths = self.hidden_layer_paths()
        if bool(hidden) == (layer_path in paths):
            return
        if hidden:
            paths.add(layer_path)
            self._store_hidden_layers(self._hidden_graph, hide=[layer_path])
        else:
            paths.discard(layer_path)
            self._store_hidden_layers(self._hidden_graph, show=[layer_path])
        self.layer_visibility_changed.emit()

    def hidden_nodes(self):
        """Paths of the nodes hidden in the graph.

        Decided a node at a time. A node is hidden when every layer that
        says anything about that node itself is hidden, and nothing under
        it is shown. So hiding a layer takes away the nodes it adds, even
        inside a tree other layers add to, while a node a layer that is
        showing also has an opinion on stays, and so does every node above
        one that is shown.

        A proxy node, made by an instance and with no opinion of its own on
        any layer, goes with the node it is stacked under: what an instance
        brings with it is shown with the instance, wherever its source is.

        Worked out in one pass over every layer's nodes, so ask once and
        look each node up in the answer.

        :rtype: frozenset
        """
        hidden_layers = self.hidden_layer_paths()
        if not hidden_layers:
            return frozenset()
        world = nxt_path.WORLD
        get_parent = nxt_path.get_parent_path
        shown = set()
        hidden = set()
        for layer in self.stage._sub_layers:
            if layer.real_path in hidden_layers:
                hidden.update(layer._nodes_path_as_key)
            else:
                shown.update(layer._nodes_path_as_key)
        # Up from every node, to take in the parents only implied by the
        # nodes under them, and to show every parent of a shown node. A
        # walk stops at a parent already known, which was or will be
        # walked up from itself.
        for found in (shown, hidden):
            for path in list(found):
                parent = get_parent(path)
                while parent != world and parent not in found:
                    found.add(parent)
                    parent = get_parent(parent)
        hidden -= shown
        hidden.discard(world)
        if not hidden:
            return frozenset()
        # Proxies, parents first, so each one's parent is decided.
        proxies = [path for path in self.comp_layer._nodes_path_as_key
                   if path != world and path not in shown and
                   path not in hidden]
        proxies.sort(key=lambda path: path.count(nxt_path.NODE_SEP))
        for path in proxies:
            if get_parent(path) in hidden:
                hidden.add(path)
        return frozenset(hidden)

    def is_node_hidden(self, node_path, hidden_nodes=None):
        """Whether a node is out of sight because its layers are hidden.
        See hidden_nodes.

        :param node_path: any node path
        :type node_path: str
        :param hidden_nodes: hidden_nodes, when it is already known
        :rtype: bool
        """
        if hidden_nodes is None:
            hidden_nodes = self.hidden_nodes()
        return node_path in hidden_nodes

    def hidden_backdrop_ids(self):
        """Ids of the backdrops only hidden layers draw.

        :rtype: set
        """
        hidden = self.hidden_layer_paths()
        if not hidden:
            return set()
        shown = backdrops.merged([layer for layer in self.stage._sub_layers
                                  if layer.real_path not in hidden])
        return set(self.get_backdrops()) - set(shown)

    def is_backdrop_hidden(self, backdrop_id):
        """Whether a backdrop only hidden layers draw.

        :rtype: bool
        """
        return backdrop_id in self.hidden_backdrop_ids()

    def _show_layer_for_new_nodes(self, node_paths, layer_path,
                                  why='a node was made on it'):
        """Show a hidden layer again when nodes made on it would be hidden
        the moment they are made, and say so.

        :param node_paths: the nodes just made
        :param layer_path: real path of the layer they were made on, or a
            LAYERS constant
        :param why: the end of the message: what was done on the layer
        """
        node_paths = [path for path in node_paths or () if path]
        layer = self.lookup_layer(layer_path)
        if not node_paths or layer is None:
            return
        layer_path = layer.real_path
        if not self.get_layer_hidden(layer_path):
            return
        hidden_nodes = self.hidden_nodes()
        if not any(self.is_node_hidden(path, hidden_nodes)
                   for path in node_paths):
            return
        self.set_layer_hidden(layer_path, False)
        name = layer.get_alias()
        message = 'Showing layer "{}" in the graph again, {}'.format(name,
                                                                   why)
        logger.info(message)
        self.status_message.emit(message)

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

    def get_layers_with_opinion(self, node_path, attr_name=None,
                                as_layers=False):
        """Returns all layer paths in the current comp that contain the given
        node. Ordered with the top layer at 0.

        :param node_path: path to find layers for.
        :type node_path: str
        :param attr_name: Optional: name of specific attr that must have an
        opinion at the given node path.
        :type attr_name: str
        :param as_layers: the layers themselves rather than their paths. A
            path can name the wrong layer, or none: a new layer has no file
            yet, and two layers can be the same file.
        :type as_layers: bool
        :return: list of layer paths, or layers
        :rtype: list
        """
        s, e = self.comp_layer._layer_range
        comp_layers = self.stage._sub_layers[s:e]
        layers = nxt_layer.get_active_layers(comp_layers)
        layers = self.stage.get_layers_with_opinion(node_path, layers,
                                                    attr_name)
        if as_layers:
            return list(layers)
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
            if node is None:
                # The node exists, just not in this layer.
                node = self.comp_layer.lookup(node_path)
            if node is None:
                return self.get_layer_color(layer)
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
        self._show_layer_for_new_nodes([new_node_path], layer.real_path)
        return new_node_path

    def delete_is_orphaning(self, node_path, layer):
        """Whether deleting this node would leave its path behind as a ghost.

        Deleting a node keeps its children by default, so the path it
        occupied still has things hanging off it and comes back as an
        implied node: drawn in the graph, listed in the build, and not
        deletable, because nothing is there to delete. That is only the
        right answer when another layer actually provides the node, in
        which case the lower opinion should surface.

        :param node_path: node about to be deleted
        :type node_path: str
        :param layer: layer it is being deleted from
        :return: True when the descendants should go with it
        :rtype: bool
        """
        if not layer.descendants(node_path, include_implied=True):
            return False
        others = [l for l in self.stage.get_layers_with_opinion(node_path)
                  if l is not layer]
        return not others

    def delete_nodes(self, node_paths=(), layer=None, recursive=False):
        if not node_paths:
            node_paths = self.selection
        layer = layer or self.target_layer
        if not recursive:
            # Taking the descendants is not really a separate mode when
            # nothing else can fill the path; it is the difference between
            # deleting the node and leaving a ghost of it.
            recursive = any(self.delete_is_orphaning(p, layer)
                            for p in node_paths)
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
        self._show_layer_for_new_nodes(cmd.new_node_paths, target_layer_path)
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
        self._show_layer_for_new_nodes(new_nodes, target_layer_path)

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
            layer = self.target_layer
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
            # The world node is copied but never deleted: a graph always
            # has one.
            node_paths = [p for p in node_paths if p != nxt_path.WORLD]
            if node_paths:
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

    # The key copied attributes sit under on the clipboard, which is how a
    # paste tells them from copied nodes or any other text.
    ATTRS_CLIPBOARD_KEY = 'nxt_attrs'

    def copy_attrs(self, node_path, attr_names, layer=None):
        """Put attributes on the clipboard as JSON: each one's name, raw
        value, type and comment, in the order given. paste_attrs puts them
        on other nodes, in this graph or another.

        :param node_path: the node they are on
        :param attr_names: their names
        :param layer: where to read them, the comp layer by default
        :return: the attributes copied, as they are on the clipboard
        :rtype: list
        """
        layer = layer or self.comp_layer
        attrs = []
        for attr_name in attr_names:
            value = self.get_node_attr_value(node_path, attr_name, layer,
                                             data_state=DATA_STATE.RAW,
                                             as_string=True)
            attrs += [{'name': attr_name,
                       'value': value,
                       'type': self.get_node_attr_type(node_path, attr_name,
                                                       layer),
                       'comment': self.get_node_attr_comment(node_path,
                                                             attr_name,
                                                             layer)}]
        if not attrs:
            return []
        text = json.dumps({self.ATTRS_CLIPBOARD_KEY: attrs}, indent=4)
        self.clipboard.setText(text)
        return attrs

    def get_clipboard_attrs(self):
        """The attributes copy_attrs put on the clipboard, or an empty
        list when it holds anything else.

        :rtype: list
        """
        try:
            data = json.loads(self.clipboard.text())
        except (TypeError, ValueError):
            return []
        if not isinstance(data, dict):
            return []
        attrs = data.get(self.ATTRS_CLIPBOARD_KEY)
        if not isinstance(attrs, list):
            return []
        return [attr for attr in attrs
                if isinstance(attr, dict) and attr.get('name')]

    def paste_attrs(self, node_paths, layer=None):
        """Add the attributes on the clipboard to each of the nodes, on the
        target layer, or set them where a node already has them. Their
        comments come along too. It is one undo however many nodes and
        attributes there are.

        :param node_paths: the nodes to paste onto
        :param layer: where to set them, the target layer by default
        :return: whether anything was pasted
        :rtype: bool
        """
        attrs = self.get_clipboard_attrs()
        node_paths = [path for path in node_paths if path]
        if not attrs or not node_paths:
            return False
        layer = layer or self.target_layer
        msg = 'Paste {} attribute(s) onto {}'.format(
            len(attrs), node_paths[0] if len(node_paths) == 1 else
            '{} nodes'.format(len(node_paths)))
        self.undo_stack.beginMacro(msg)
        try:
            for node_path in node_paths:
                for attr in attrs:
                    attr_name = str(attr['name'])
                    value = attr.get('value')
                    if value is None:
                        value = ''
                    self.set_node_attr_value(node_path, attr_name, value,
                                             layer)
                    comment = attr.get('comment')
                    if comment:
                        self.node_setattr_comment(node_path, attr_name,
                                                  comment, layer)
        finally:
            self.undo_stack.endMacro()
        return True

    def cut_nodes(self, node_paths=(), layer=None):
        if not node_paths:
            node_paths = self.selection
        return self.copy_nodes(node_paths, cut=True, layer=layer)

    def paste_nodes(self, pos=None, parent_path=None, layer=None):
        """Paste whatever nodes are on the clipboard into the graph.

        A paste is one edit however many nodes it brought in, so it goes on
        the undo stack as one thing. Pasting five nodes and changing your
        mind used to take five undos, and each one of the first four left
        the graph in a state nobody had ever asked for.

        :return: paths of the nodes that were pasted
        :rtype: list
        """
        node_load_data = []
        try:
            node_load_data = clean_json.load(json.loads(self.clipboard.text(),
                                                        object_hook=clean_json._byteify))
        except ValueError:
            pass
        if not node_load_data:
            return []
        pos = pos or [0.0, 0.0]
        pasted = []
        # The world node is not pasted as a node of its own, there is only
        # one, so what it holds is merged into the target layer's.
        worlds = [list(d.values())[0] for d in node_load_data
                  if list(d.keys())[0] == nxt_path.WORLD]
        node_load_data = [d for d in node_load_data
                          if list(d.keys())[0] != nxt_path.WORLD]
        # A single node is already a single command; wrapping it would only
        # bury the name of what was pasted under a macro. The world node's
        # attributes and code are a command each.
        as_macro = len(node_load_data) > 1 or bool(worlds)
        if as_macro:
            if not node_load_data:
                msg = 'Paste world node'
            else:
                count = len(node_load_data) + len(worlds)
                msg = 'Paste {} nodes'.format(count)
            self.undo_stack.beginMacro(msg)
        try:
            for data in worlds:
                self._paste_world(data, layer)
            for node_data in node_load_data:
                node_path, data = list(node_data.items())[0]
                name = nxt_path.node_name_from_node_path(node_path)
                if not (node_path and name):
                    continue
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
                if not new_node_path:
                    continue
                self._set_node_pos(new_node_path, pos, layer=layer)
                pos = [pos[0] + 20, pos[1] + 20]
                pasted += [new_node_path]
        finally:
            if as_macro:
                self.undo_stack.endMacro()
        if worlds:
            pasted = [nxt_path.WORLD] + pasted
        if not pasted:
            return []
        self.update_comp_layer()
        for new_node_path in pasted:
            if new_node_path != nxt_path.WORLD:
                self.node_added.emit(new_node_path)
        self.selection = pasted
        return pasted

    def _paste_world(self, data, layer=None):
        """Merge a copied world node into the layer's world node: its
        attributes are set on it, a pasted one taking the place of one of
        the same name, and its code and comment, when it has them, take
        the place of the layer's. The world node is made if the layer has
        none.

        :param data: the world node as copied, see copy_nodes
        :param layer: the layer to paste on, the target layer by default
        """
        layer = layer or self.target_layer
        layer_path = self.get_layer_path(layer, fallback=LAYERS.TARGET)
        world = nxt_path.WORLD
        attrs = data.get(nxt_io.SAVE_KEY.ATTRS) or {}
        for attr_name, attr_data in attrs.items():
            attr_data = dict(attr_data or {})
            attr_data.setdefault(META_ATTRS.VALUE, None)
            cmd = SetNodeAttributeData(node_path=world, attr_name=attr_name,
                                       data=attr_data, model=self,
                                       layer_path=layer_path)
            self.undo_stack.push(cmd)
        code_key = INTERNAL_ATTRS.as_save_key(INTERNAL_ATTRS.COMPUTE)
        code = data.get(code_key)
        if code:
            self.set_node_code_lines(world, list(code), layer=layer)
        comment_key = INTERNAL_ATTRS.as_save_key(INTERNAL_ATTRS.COMMENT)
        comment = data.get(comment_key)
        if comment:
            self.set_node_comment(world, comment, layer=layer)

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
            # Parented on a hidden target layer, a node would vanish from
            # the graph as it moved, as a node made there would.
            self._show_layer_for_new_nodes(
                list(cmd.node_path_data.values()), LAYERS.TARGET,
                why='a node was parented on it')
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
        layer = self.lookup_layer(layer_path)
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
        if not node:
            return None
        if isinstance(layer, nxt_layer.CacheLayer):
            # A cached value is whatever object a node's code left there,
            # so its type is right there. Working it out the way a saved
            # value's is, by resolving tokens in its text and parsing that
            # back, took seconds for a big list and stalled the editor,
            # and the host it runs in, at the end of every build.
            value = self.stage.get_node_attr_value(node, attr_name, layer,
                                                   resolved=False)
            if not isinstance(value, str):
                return cached_type_name(value)
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
        """Collapse or expand nodes, each the opposite of what it is.

        Recursively, the nodes below (or above) one are all set to its new
        state, so a hierarchy is collapsed or expanded as a whole rather
        than each node in it flipped, which left a mixed one mixed.

        Each node's state is the one shown, the comp's: a layer below can
        have a node collapsed that the top layer says nothing about, and
        flipping the top layer's own state collapsed it again.
        """
        comp_layer = self.comp_layer
        layer = (self.lookup_layer(layer_path) if layer_path
                 else comp_layer)
        new_states = {}
        for node_path in node_paths:
            state = not self.get_node_collapse(node_path, layer)
            new_states[node_path] = state
            related = []
            if recursive_down:
                related += self.get_descendants(node_path, comp_layer)
            if recursive_up:
                related += [comp_layer.get_node_path(ancestor)
                            for ancestor in comp_layer.ancestors(node_path)]
            for path in related:
                if self.get_node_collapse(path, layer) != state:
                    new_states[path] = state
        set_true = [path for path, state in new_states.items() if state]
        set_false = [path for path, state in new_states.items() if not state]
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
        self.select_and_frame_nodes([node_path])

    def select_and_frame_nodes(self, node_paths):
        """Select the nodes and frame them in the graph, expanding any
        collapsed node they are under so they show."""
        node_paths = [path for path in node_paths
                      if self.node_exists(path) or self.node_is_implied(path)]
        if not node_paths:
            return
        if len(node_paths) == 1:
            text = 'Select and frame {}'.format(node_paths[0])
        else:
            text = 'Select and frame {} nodes'.format(len(node_paths))
        self.undo_stack.beginMacro(text)
        for node_path in node_paths:
            if self.get_collapsed_ancestor(node_path):
                parent = nxt_path.get_parent_path(node_path)
                self.set_node_collapse([parent], False, recursive_up=True)
        self.set_selection(list(node_paths))
        self.frame_items.emit(tuple(node_paths))
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

    def push_node_positions(self, node_paths=None, layer=None):
        """Write where nodes are shown onto a layer, the target layer by
        default, as one undo. Moving a node only ever writes its position
        to the top layer, so a layer below keeps where the nodes were when
        it was last the top, or nothing. Only top level nodes have a
        position: children are stacked under their root.

        :param node_paths: the nodes, the selected ones by default
        :param layer: the layer to write to
        :return: how many positions were written
        """
        layer = layer or self.target_layer
        if node_paths is None:
            node_paths = self.get_selected_nodes()
        positions = {}
        for path in node_paths:
            if nxt_path.get_root_path(path) != path:
                continue
            if not (self.node_exists(path) or self.node_is_implied(path)):
                continue
            positions[path] = list(self.get_node_pos(path))
        if not positions:
            return 0
        if len(positions) == 1:
            text = 'Push position of {} to {}'.format(
                list(positions)[0], layer.get_alias())
        else:
            text = 'Push {} positions to {}'.format(len(positions),
                                                    layer.get_alias())
        cmd = PushNodePositions(positions, model=self,
                                layer_path=layer.real_path, text=text)
        self.undo_stack.push(cmd)
        return len(positions)

    # Backdrops, see nxt_editor.backdrops ----------------------------------

    def get_backdrops(self):
        """Every backdrop this graph shows.

        :return: {id: record}
        """
        return backdrops.merged(self.stage._sub_layers)

    def get_backdrop(self, backdrop_id):
        return self.get_backdrops().get(backdrop_id)

    def add_backdrop(self, record, backdrop_id=None):
        """Add a backdrop to the top layer.

        :return: the new backdrop's id
        """
        backdrop_id = backdrop_id or backdrops.new_id()
        self.set_backdrops({backdrop_id: self._safe_backdrop(record)},
                           text='Add backdrop "{}"'.format(
                               record.get(backdrops.TITLE, '')))
        return backdrop_id

    def edit_backdrop(self, backdrop_id, text='Edit backdrop', **fields):
        """Change some of a backdrop's fields, such as title or color."""
        record = self.get_backdrop(backdrop_id)
        if record is None:
            return
        record.update(fields)
        self.set_backdrops({backdrop_id: self._safe_backdrop(record)},
                           text=text)

    @staticmethod
    def _safe_backdrop(record):
        """A clean record. Its color is kept as chosen, written the way
        colors are; how it is shown is each user's view, see color_range."""
        record = backdrops.clean(record)
        if record is not None:
            color = QtGui.QColor(record[backdrops.COLOR])
            if color.isValid():
                record[backdrops.COLOR] = color.name()
        return record

    def remove_backdrops(self, backdrop_ids):
        """Take backdrops away. The nodes in them stay where they are."""
        top = self.top_layer
        below = backdrops.merged(self.stage._sub_layers[1:])
        changes = {}
        for backdrop_id in backdrop_ids:
            if backdrop_id in below:
                # A lower layer made it, and only the top layer is written,
                # so it is hidden rather than removed.
                changes[backdrop_id] = None
            elif backdrop_id in backdrops.layer_backdrops(top):
                changes[backdrop_id] = backdrops.ABSENT
        if not changes:
            return
        if len(changes) == 1:
            text = 'Delete backdrop'
        else:
            text = 'Delete {} backdrops'.format(len(changes))
        self.set_backdrops(changes, text=text)

    def set_backdrops(self, changes, text='Edit backdrop'):
        """Write backdrop records onto the top layer, as one undo.

        :param changes: {id: record, None or backdrops.ABSENT}
        """
        if not changes:
            return
        cmd = SetBackdrops(changes, model=self,
                           layer_path=self.top_layer.real_path, text=text)
        self.undo_stack.push(cmd)

    # Camera bookmarks, see nxt_editor.bookmarks ----------------------------

    def get_bookmarks(self):
        """The graph's camera bookmarks, in order.

        :return: [{'name': str, 'rect': [x, y, w, h]}]
        """
        return bookmarks.layer_bookmarks(self.top_layer)

    def set_bookmarks(self, records, text='Edit bookmarks'):
        """Save the graph's bookmarks, all of them, as one undo."""
        cmd = SetBookmarks(records, model=self,
                           layer_path=self.top_layer.real_path, text=text)
        self.undo_stack.push(cmd)

    def add_bookmark(self, rect, name=None):
        """Bookmark a part of the graph.

        :param rect: (x, y, width, height) in the scene
        :param name: what to call it, "Bookmark 1" and so on by default
        :return: the new bookmark's index
        """
        records = self.get_bookmarks()
        name = (name or '').strip() or bookmarks.unique_name(records)
        records.append(bookmarks.make(name, rect))
        self.set_bookmarks(records, text='Add bookmark "{}"'.format(name))
        return len(records) - 1

    def rename_bookmark(self, index, name):
        records = self.get_bookmarks()
        name = (name or '').strip()
        if not (0 <= index < len(records)) or not name:
            return
        if records[index][bookmarks.NAME] == name:
            return
        old = records[index][bookmarks.NAME]
        records[index][bookmarks.NAME] = name
        self.set_bookmarks(records, text='Rename bookmark "{}" to "{}"'.format(
            old, name))

    def remove_bookmark(self, index):
        records = self.get_bookmarks()
        if not (0 <= index < len(records)):
            return
        removed = records.pop(index)
        self.set_bookmarks(records, text='Delete bookmark "{}"'.format(
            removed[bookmarks.NAME]))

    # Line style and points, see nxt_editor.wires ------------------------

    @staticmethod
    def preferred_connection_style():
        """How lines are drawn in a graph that does not save its own
        choice: the user's preference, else straight."""
        style = user_dir.user_prefs.get(user_dir.USER_PREF.CONNECTION_STYLE)
        if style in wires.STYLES:
            return style
        return wires.DEFAULT_STYLE

    def get_connection_style(self):
        """Whether this graph draws its lines straight or curved."""
        return wires.merged_style(self.stage._sub_layers,
                                  self.preferred_connection_style())

    def set_connection_style(self, style):
        """Draw this graph's lines straight or curved, saved on the top
        layer, and remembered as the user's preference for graphs that do
        not save one."""
        if style not in wires.STYLES:
            return
        if style == self.get_connection_style():
            # Nothing to see change, but remembered for the graphs to come.
            user_dir.user_prefs[user_dir.USER_PREF.CONNECTION_STYLE] = style
            return
        # Saved on the graph unless it is what the lower layers, or a user
        # with no preference, would see anyway.
        lower = wires.merged_style(self.stage._sub_layers[1:])
        if style == lower:
            # What the lower layers say already, so nothing to keep.
            saved = wires.ABSENT
        else:
            saved = style
        if style == wires.CURVED:
            text = 'Curved connections'
        else:
            text = 'Straight connections'
        cmd = SetWires(model=self, layer_path=self.top_layer.real_path,
                       style=saved, text=text, preference=style)
        self.undo_stack.push(cmd)

    def get_line_points(self, key=None):
        """The points lines are routed through.

        :param key: one line's key, see wires.line_key, or None for all
        :return: [[x, y], ...] for one line, else {key: points}
        """
        shown = wires.merged_points(self.stage._sub_layers)
        if key is None:
            return shown
        return shown.get(key, [])

    def set_line_points(self, key, points, text='Edit connection points'):
        """Route one line through the given points, as one undo. No points
        takes them all away."""
        points = wires.clean_points(points) or []
        if points == self.get_line_points(key):
            return
        if points:
            change = points
        elif key in wires.merged_points(self.stage._sub_layers[1:]):
            # A lower layer's, and only the top layer is written.
            change = None
        else:
            change = wires.ABSENT
        cmd = SetWires(model=self, layer_path=self.top_layer.real_path,
                       points={key: change}, text=text)
        self.undo_stack.push(cmd)

    def break_connections(self, lines, text=None):
        """Break connections, as one undo.

        What a line came from is taken out of where it went, and nothing
        else is left in its place: an exec input or instance is cleared,
        and an attribute loses the reference, keeping any other text it
        has, and is left empty when that was all it held. Should a weaker
        layer still make the connection, the target layer is given an
        empty value over it. An instance is removed from the node whichever
        layer made it, as Remove Instance does. The line's points go too.

        :param lines: (source path, target attr path) pairs, as the graph
            draws them
        :return: how many were broken
        """
        breakable = []
        for src, tgt in lines:
            if not self._breakable(tgt):
                continue
            attr = nxt_path.attr_name_from_attr_path(tgt)
            owner = self._connection_layer(tgt)
            if (attr != INTERNAL_ATTRS.INSTANCE_PATH and owner is not None and
                    owner != self.target_layer.real_path):
                # nxt reads an empty exec input as no opinion, so a
                # stronger layer cannot clear a weaker one's. It is broken
                # on the layer that made it. An empty instance path is an
                # opinion, so an instance is removed on any layer.
                logger.warning(
                    'The connection into {} is made on {}. Make that the '
                    'target layer to break it.'.format(tgt, owner),
                    links=[nxt_path.node_path_from_attr_path(tgt)])
                continue
            breakable.append((src, tgt))
        lines = breakable
        if not lines:
            return 0
        if text is None:
            text = ('Break connection' if len(lines) == 1 else
                    'Break {} connections'.format(len(lines)))
        self.undo_stack.beginMacro(text)
        try:
            for src, tgt in lines:
                self._break_connection(src, tgt)
                self.set_line_points(wires.line_key(src, tgt), [],
                                     text=text)
        finally:
            self.undo_stack.endMacro()
        return len(lines)

    @staticmethod
    def _breakable(tgt_path):
        """Whether a line into this attr can be broken from the graph.

        A line into a node's code is drawn for a reference written in the
        code, which is the code editor's to change.
        """
        attr = nxt_path.attr_name_from_attr_path(tgt_path)
        return bool(attr) and attr != INTERNAL_ATTRS.COMPUTE

    def _connection_layer(self, tgt_path):
        """The path of the layer whose opinion makes a connection, or None
        when it cannot be told."""
        node_path = nxt_path.node_path_from_attr_path(tgt_path)
        attr = nxt_path.attr_name_from_attr_path(tgt_path)
        node = self.comp_layer.lookup(node_path)
        if node is None:
            return None
        try:
            layer_path, _ = self.stage.get_node_attr_source(node, attr)
        except (AttributeError, TypeError, ValueError):
            return None
        return layer_path

    def _break_connection(self, src_path, tgt_path):
        node_path = nxt_path.node_path_from_attr_path(tgt_path)
        attr = nxt_path.attr_name_from_attr_path(tgt_path)
        layer = self.target_layer
        if attr == INTERNAL_ATTRS.EXECUTE_IN:
            self._clear_link(node_path, attr, layer,
                             lambda value: self.set_node_exec_in(
                                 node_path, value, layer),
                             lambda: self.get_node_exec_in(node_path,
                                                           self.comp_layer))
            return
        if attr == INTERNAL_ATTRS.INSTANCE_PATH:
            # An empty instance path is how an instance is removed, see
            # the Remove Instance action. It is only written when a weaker
            # layer would still instance the node.
            def write(value):
                if value is not None:
                    self.set_node_instance(node_path, value, layer)
                elif layer.lookup(node_path) is not None:
                    self.revert_node_instance(node_path, layer)
            self._clear_link(node_path, attr, layer, write,
                             lambda: bool(self.get_node_instance_path(
                                 node_path, self.comp_layer)))
            return
        value = self.get_node_attr_value(node_path, attr, self.comp_layer,
                                         data_state=DATA_STATE.RAW)
        kept = self._without_reference(value, src_path, node_path)
        if kept is not None and str(kept).strip():
            self.set_node_attr_value(node_path, attr, kept, layer)
            return
        self._clear_link(node_path, attr, layer,
                         lambda value: self.set_node_attr_value(
                             node_path, attr, value, layer),
                         lambda: src_path in (
                             self.get_node_attr_external_sources(
                                 node_path, attr, self.comp_layer) or []))

    @staticmethod
    def _clear_link(node_path, attr, layer, write, still_linked):
        """Clear an attr on the layer, and if a weaker layer's value then
        still links it, write an empty one over that."""
        write(None)
        if still_linked():
            write('')

    def _without_reference(self, value, src_path, node_path):
        """An attr value with every reference to src_path taken out.

        :return: what is left, or None when nothing is
        """
        if value is None:
            return None
        text = str(value)
        attr_tokens = self.stage.get_tokens_from(
            text, token_type=tokens.TOKENTYPE.ATTR)
        for token in attr_tokens:
            ref = tokens.get_token_content(token)
            if not nxt_path.is_attr_path(ref):
                continue
            if nxt_path.expand_relative_node_path(ref, node_path) == src_path:
                text = text.replace(token, '')
        return text if text.strip() else None

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
        # The nearest line either way, not the one up and to the left, so
        # a node dragged just short of a grid line still lands on it. Half
        # way rounds up, the same in both directions.
        x = math.floor(pos[0] / grid_size + .5) * grid_size
        y = math.floor(pos[1] / grid_size + .5) * grid_size
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

    def _breaks(self, layer_path):
        """Where the breakpoints of the layer at layer_path are kept: the
        user's prefs, by the layer's file, or for a layer not saved yet
        this session, until it is."""
        if layer_path:
            return user_dir.breakpoints
        return self._unsaved_points['breaks']

    def _skips(self, layer_path):
        """Where the skip points of the layer at layer_path are kept, see
        _breaks."""
        if layer_path:
            return user_dir.skippoints
        return self._unsaved_points['skips']

    def _keep_unsaved_points(self, layer_path):
        """The graph was saved for the first time: its break and skip
        points go to the user's prefs, by its new file."""
        if not layer_path or layer_path != self.top_layer.real_path:
            return
        for name, prefs in (('breaks', user_dir.breakpoints),
                            ('skips', user_dir.skippoints)):
            points = self._unsaved_points[name].pop(None, None)
            if points:
                prefs[layer_path] = points

    @staticmethod
    def breakpoints_ignored():
        """Whether runs are going through every breakpoint, as the Ignore
        Breakpoints toggle asks. The breakpoints themselves are kept.

        :rtype: bool
        """
        pref_key = user_dir.USER_PREF.IGNORE_BREAKS
        return bool(user_dir.user_prefs.get(pref_key, False))

    def get_breakpoints(self, layer=None):
        """The paths of the nodes with a breakpoint, on layer or the top
        layer."""
        layer_path = (layer or self.top_layer).real_path
        return list(self._breaks(layer_path).get(layer_path, []))

    def get_skippoints(self, layer_path=None):
        """The paths of the nodes with a skip point, on the layer at
        layer_path or the top layer."""
        layer_path = self._skip_key(layer_path)
        return list(self._skips(layer_path).get(layer_path, []))

    def get_is_node_breakpoint(self, node_path, layer=None):
        layer = layer or self.top_layer
        layer_breaks = self._breaks(layer.real_path).get(layer.real_path, [])
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
            # Not saved yet, see _breaks.
            layer_path = LAYERS.TOP
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
        cmd = ClearBreakpoints(model=self,
                               layer_path=layer.real_path or LAYERS.TOP)
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
        layer_path = layer.real_path and str(layer.real_path)
        breaks = self._breaks(layer_path)
        layer_breaks = breaks.get(layer_path, [])
        if node_path in layer_breaks:
            # no need to re-write existing data to pref
            return
        layer_breaks.append(node_path)
        breaks[layer_path] = layer_breaks
        self.breaks_changed.emit(layer_breaks)

    def _remove_breakpoint(self, node_path, layer):
        """Removes the node_path breakpoint based on the layer's real_path.
        If node_path is None all breakpoints for the layer will be removed.
        :param node_path: String of a node path
        :param layer: Layer object
        :return: None
        """
        layer_path = layer.real_path
        breaks = self._breaks(layer_path)
        layer_breaks = breaks.get(layer_path)
        if not layer_breaks:
            return
        if not node_path:
            breaks.pop(layer_path)
            return
        try:
            layer_breaks.remove(node_path)
        except ValueError:
            # Can return without the below save in this case. If the node
            # path is not present, it's already "removed"
            return
        breaks[layer_path] = layer_breaks
        self.breaks_changed.emit(layer_breaks)

    def toggle_skippoints(self, node_paths, layer_path=None):
        """Reverse the skip status of all given node paths.

        :param node_paths: Node paths to toggle.
        :type node_paths: iterable
        :param layer_path: Layer to set skips on, defaults to top layer.
        :type layer_path: str, optional
        """
        if not layer_path:
            # Not saved yet, see _skips.
            layer_path = self.top_layer.real_path or LAYERS.TOP
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
            # Not saved yet, see _skips.
            layer_path = self.top_layer.real_path or LAYERS.TOP
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
            # Not saved yet, see _skips.
            layer_path = self.top_layer.real_path or LAYERS.TOP
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
        layer_path = self._skip_key(layer_path)
        layer_skips = self._skips(layer_path).get(layer_path, [])
        return node_path in layer_skips

    def _skip_key(self, layer_path):
        """The key the skip points of layer_path are kept by: its file, or
        None for the top layer before it is saved."""
        if not layer_path or layer_path == LAYERS.TOP:
            return self.top_layer.real_path
        return layer_path

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
        layer_path = self._skip_key(str(layer_path))
        skips = self._skips(layer_path)
        layer_skips = skips.get(layer_path, [])
        if node_path in layer_skips:
            # no need to re-write existing data to pref
            return
        layer_skips.append(node_path)
        skips[layer_path] = layer_skips
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
        layer_path = self._skip_key(str(layer_path))
        skips = self._skips(layer_path)
        layer_skips = skips.get(layer_path, [])
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
        skips[layer_path] = layer_skips
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
        base_dir = user_dir.last_opened_dir()
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
            rt_layer = self.new_runtime_layer()
            self.current_rt_layer = rt_layer
        return rt_layer

    def new_runtime_layer(self):
        """A runtime layer to run in, made from a copy of the comp the
        editor shows while that is exact, or else from a fresh comp.

        Compositing the graph for each run cost as long as opening it,
        before the first node started. A copy is much quicker, and is the
        graph as it is now while the comp is exact, see comp_is_exact. A
        run sets values on the nodes it runs in, so it has a copy of its
        own. See RECOMP_ENV_VAR and CHECK_COMP_ENV_VAR.

        :raises GraphError: when the world node fails
        :rtype: CompLayer
        """
        comp = self.comp_layer
        if (os.environ.get(RECOMP_ENV_VAR) == '1' or
                not hasattr(comp, 'copy')):
            build = self.stage.build_stage(comp.layer_idx())
        elif not self.comp_is_exact:
            # The comp shown changed in place. A fresh one is made, the
            # run has a copy, and it is shown once the run is done.
            self.stale_comp_timer.stop()
            fresh = self.build_comp(comp.layer_idx())
            self._fresh_comp = (fresh, self.comp_stamp())
            build = fresh.copy()
        else:
            build = comp.copy()
            if os.environ.get(CHECK_COMP_ENV_VAR) == '1':
                build = self.checked_copy(build)
        return self.stage.setup_runtime_layer(build)

    def checked_copy(self, copied):
        """The copy, or a fresh comp where it differs from one.

        :param copied: a copy of the comp the editor shows
        :rtype: CompLayer
        """
        fresh = self.stage.build_stage(copied.layer_idx())
        found = nxt_layer.comp_differences(copied, fresh)
        if not found:
            logger.info('The graph shown is the same as a fresh comp of it.')
            return copied
        logger.warning('The graph shown differs from a fresh comp of it, '
                       'so this run is in a fresh comp. Where they differ:\n'
                       '{}'.format('\n'.join(found)))
        return fresh

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
        :param safe_exec: If True a cached runtime layer that cannot run
            these nodes is thrown away and built again rather than run
        :return: CompLayer (the runtime layer that ran)
        """
        if not node_paths:
            logger.error("No node paths specified for execution")
            return
        self.about_to_execute.emit(True)
        self.setup_build(node_paths, rt_layer=rt_layer, safe_exec=safe_exec)
        self.resume_build()
        return rt_layer

    def _execute_node(self, node_path):
        t = ExecuteNodeThread(self, node_path)
        self._running_node = True
        try:
            if self.is_standalone:
                self.processing.emit(True)
                t.start()
                while not t.isFinished():
                    self.process_events()
                self.processing.emit(False)
            else:
                # DCCs aren't thread safe, we need to get attached working so
                # we can know we're in a thread safe environment.
                t._run()
                self.process_events()
        finally:
            self._running_node = False
        if self._build_should_stop and not t.raised_exception:
            # Stop was pressed while the node ran, after it last looked.
            raise BuildStop
        if t.failed:
            # Told before the invalid node dialog below, which waits.
            self.build_failed.emit(node_path)
        if t.raised_exception:
            if isinstance(t.raised_exception, InvalidNodeError):
                details = ("A build runs against the graph as it was when "
                           "the build started. A node that is not there is "
                           "usually one that was deleted, or one in a layer "
                           "that was muted, while the build was running."
                           "\n\n"
                           "A cache left over from an earlier run is "
                           "cleared and built again on its own when it "
                           "does not know every node in the build, so this "
                           "is not that. 'Execute > Clear cache' is worth "
                           "trying anyway if the graph looks right.")
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

    def runtime_layer_can_run(self, rt_layer, node_paths):
        """Whether a cached runtime layer still knows these nodes.

        The cache is a snapshot of the graph, taken when it was built and
        kept on purpose: running a node again in the same interpreter is
        what makes the workflow buttons quick. A node moved, renamed or
        deleted since is not in that snapshot, and running against it
        gets as far as the missing node before giving up.

        :param rt_layer: cached runtime layer, or None
        :param node_paths: the nodes about to be run
        :type node_paths: list
        :return: bool
        """
        if rt_layer is None:
            return False
        for node_path in node_paths:
            if rt_layer.lookup(node_path) is None:
                logger.debug('"{}" is not in the cached graph'
                             ''.format(node_path))
                return False
        return True

    def setup_build(self, node_paths, rt_layer=None, safe_exec=True):
        """Get ready to run the given nodes.

        :param node_paths: nodes to run, in order
        :type node_paths: list
        :param rt_layer: runtime layer to run in, built if not given
        :param safe_exec: If True a cached runtime layer that cannot run
            these nodes is thrown away and built again rather than run
        :type safe_exec: bool
        """
        # Reset once_sec_timer vars
        self.build_start_time = time.time()
        self.build_paused_time = .0
        self.last_step_time = .0

        self.current_build_order = node_paths
        self.build_changed.emit(node_paths)
        self.refresh_exec_framing_from_pref()
        stale_cache = (rt_layer is not None and safe_exec
                       and not self.runtime_layer_can_run(rt_layer,
                                                          node_paths))
        if stale_cache:
            # Nothing has run yet, so clearing the cache here costs the
            # person a rebuild. Letting it run would cost them a build
            # that stops part way through, at whichever node had moved,
            # with the work before it already done.
            logger.info('The cache does not know every node in this build, '
                        'so it has been cleared and built again.')
            rt_layer = None
        if self.use_cmd_port:
            # TODO: Only run this if we actually have to
            self.update_remote_comp()
            self.current_rt_layer = self.comp_layer
        elif rt_layer:
            self.current_rt_layer = rt_layer
        else:
            try:
                self.current_rt_layer = self.new_runtime_layer()
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

        top_path = self.top_layer.real_path
        breaks = self._breaks(top_path).get(top_path, [])[:]
        skips = self._skips(top_path).get(top_path, [])[:]
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
        # Ignored breakpoints stay where they are, a run just goes through.
        if breaks and self.breakpoints_ignored():
            logger.execinfo('Ignoring {} breakpoint(s), see Execute > Ignore '
                            'Breakpoints.'.format(len(breaks)))
            breaks = []
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
        if self.build_paused and not self._running_node:
            self.finish_build()
        else:
            # A node is running, stepped or not. Ending the build under it
            # put the build view back while the node carried on, and the
            # step finishing it again afterwards emptied the build list.
            # The build stops once the node is done.
            self._build_should_stop = True

    def _set_executing(self, executing):
        if not executing:
            self._build_should_stop = False
        if self._executing == executing:
            return
        self._executing = executing
        self.executing_changed.emit(self._executing)

    def finish_build(self, verbose=True):
        if not self.executing and self.current_build_order is None:
            # Already finished. Telling the views again would empty the
            # build list they have just put back.
            return
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
        if self._fresh_comp is not None:
            QtCore.QTimer.singleShot(0, self.show_fresh_comp)
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


def _takes_comp(call):
    """Whether a stage call takes a comp_layer, which an older nxt core
    may not."""
    try:
        return 'comp_layer' in inspect.signature(call).parameters
    except (TypeError, ValueError):
        return False


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
        # Whether the node raised an error, rather than the build being
        # stopped or the graph exiting on purpose.
        self.failed = False

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
                self.failed = True
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
