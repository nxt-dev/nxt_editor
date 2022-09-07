# Built-in
import copy
import logging
import time

# External
from Qt.QtWidgets import QUndoCommand

# Internal
from nxt_editor import colors
from nxt_editor import user_dir
from nxt import nxt_path
from nxt.nxt_layer import LAYERS, SAVE_KEY
from nxt.nxt_node import (INTERNAL_ATTRS, META_ATTRS, get_node_as_dict,
                          list_merger)
from nxt import nxt_io
from nxt import GRID_SIZE
import nxt_editor

logger = logging.getLogger(nxt_editor.LOGGER_NAME)


def processing(func):

    def wrapper(self):
        self.model.processing.emit(True)
        func(self)
        self.model.processing.emit(False)
    return wrapper


class NxtCommand(QUndoCommand):
    def __init__(self, model):
        super(NxtCommand, self).__init__()
        self.model = model
        self.model.layer_saved.connect(self.reset_layer_effected)
        self._layers_effected_by_me = {}

    def _get_effects(self, layer_path):
        """Gets the effected state for a given layer with context to this
        command. Since a single command can effect layers in different ways.

        :param layer_path: string of layer real path
        :return: (bool, bool) | (first_effected_by_undo, first_effected_by_redo)
        """
        first_eff_by_undo = False
        first_eff_by_redo = False
        try:
            first_eff_by_undo = self._layers_effected_by_me[layer_path]['undo']
        except KeyError:
            pass
        try:
            first_eff_by_redo = self._layers_effected_by_me[layer_path]['redo']
        except KeyError:
            pass
        return first_eff_by_undo, first_eff_by_redo

    def reset_layer_effected(self, layer_just_saved):
        """When the model marks a layer as saved we reset the class attr
        `_first_effected_by_redo` to False. This makes sure the layer is
        properly marked as unsaved even if we undo an action after saving it.

        :param layer_just_saved: string of layer real path
        :return: None
        """
        eff_by_undo, eff_by_redo = self._get_effects(layer_just_saved)
        where_were_at = self.model.undo_stack.index()
        cur_cmd = self.model.undo_stack.command(max(0, where_were_at - 1))
        if cur_cmd is self:
            return
        if layer_just_saved in self._layers_effected_by_me:
            if eff_by_undo:
                # This command has already been marked as undo effects the
                # layer, meaning the layer has been saved and the undo queue
                # was moved to an index before this command and the same
                # layer was saved again.
                eff_by_redo = True
                eff_by_undo = False
            else:
                # Now the undo of this command  effects the layer not the redo
                eff_by_redo = False
                eff_by_undo = True
        self._layers_effected_by_me[layer_just_saved] = {'undo': eff_by_undo,
                                                         'redo': eff_by_redo}

    def redo_effected_layer(self, layer_path):
        """Adds layer to the model's set of effected (unsaved) layers. If
        this command was the first to effect the layer we mark it as such
        by setting the class attr `_first_effected_by_redo` to True.

        :param layer_path: string of layer real path
        :return: None
        """
        layer_unsaved = layer_path in self.model.effected_layers
        eff_by_undo, eff_by_redo = self._get_effects(layer_path)
        if not eff_by_undo and layer_unsaved:
            return
        if not eff_by_undo:
            self._layers_effected_by_me[layer_path] = {'undo': False,
                                                       'redo': True}
            self.model.effected_layers.add(layer_path)
        else:
            # Layer was saved and then undo was called, thus this redo has a
            # net zero effect on the layer
            try:
                self.model.effected_layers.remove(layer_path)
            except KeyError:  # Removed by a save action
                pass

    def undo_effected_layer(self, layer_path):
        """Removes layer from the model's set of effected (unsaved) layers.
        If the layer is not marked as effected in the model we mark it as
        effected. This case happens when undo is called after a layer is saved.

        :param layer_path: string of layer real path
        :return: None
        """
        eff_by_undo, eff_by_redo = self._get_effects(layer_path)
        layer_saved = layer_path not in self.model.effected_layers
        if layer_saved:
            eff_by_undo = True
            # Set redo to False since now its been saved & the undo effects it
            eff_by_redo = False
            self.model.effected_layers.add(layer_path)
        elif eff_by_redo:
            try:
                self.model.effected_layers.remove(layer_path)
            except KeyError:  # Removed by a save action
                pass
        self._layers_effected_by_me[layer_path] = {'undo': eff_by_undo,
                                                   'redo': eff_by_redo}


class AddNode(NxtCommand):

    """Add a node to the graph"""

    def __init__(self, name, data, parent_path, pos, model, layer_path):
        super(AddNode, self).__init__(model)
        self.name = name
        self.data = data
        self.parent_path = parent_path
        self.layer_path = layer_path
        self.stage = model.stage

        # command data
        self.pos = pos or [0.0, 0.0]
        self.prev_selection = self.model.selection

        # resulting node
        self.node_path = None
        self.created_node_paths = []

    @processing
    def undo(self):
        layer = self.model.lookup_layer(self.layer_path)
        dirty_nodes = []
        # delete any created nodes
        for node_path in self.created_node_paths:
            node = layer.lookup(node_path)
            if node is not None:
                _, dirty = self.stage.delete_node(node, layer,
                                                  remove_layer_data=False)
                dirty_nodes += dirty
        node = layer.lookup(self.node_path)
        source_layer = self.stage.get_node_source_layer(node)
        if source_layer.layer_idx() > 0:
            rm_layer_data = True
        else:
            rm_layer_data = False
        comp_layer = self.model.comp_layer
        if node is not None:
            # delete node
            _, dirty = self.stage.delete_node(node, layer,
                                              comp_layer=comp_layer,
                                              remove_layer_data=rm_layer_data)
            dirty_nodes += dirty
        dirty_nodes += self.created_node_paths
        dirty_nodes += [self.node_path]
        self.undo_effected_layer(self.layer_path)
        self.model.nodes_changed.emit(tuple(set(dirty_nodes)))
        self.model.selection = self.prev_selection

    @processing
    def redo(self):
        layer = self.model.lookup_layer(self.layer_path)
        self.created_node_paths = []
        dirty_nodes = []
        nodes, dirty = self.stage.add_node(name=self.name, data=self.data,
                                           parent=self.parent_path,
                                           layer=layer.layer_idx(),
                                           comp_layer=self.model.comp_layer)
        dirty_nodes += dirty
        self.node_path = layer.get_node_path(nodes[0])
        self.model._set_node_pos(node_path=self.node_path, pos=self.pos,
                                 layer=layer)
        self.model.nodes_changed.emit(tuple(set(dirty_nodes)))
        self.model.selection = [self.node_path]
        self.redo_effected_layer(layer.real_path)
        self.setText('Added node: {}'.format(self.node_path))


class DeleteNode(NxtCommand):

    def __init__(self, node_path, model, layer_path, other_removed_nodes):
        """Delete node from the layer at the layer path and the comp layer.
        It is important to note that the other_removed_nodes
        list must be shared by other DeleteNode commands in a command macro.
        The list will be mutated by the stage as it deletes node, this
        behavior is depended upon!
        :param node_path: String of node path
        :param model: StageModel
        :param layer_path: String of layer realpath
        :param other_removed_nodes: list of node paths that will be deleted
        in this event loop.
        """
        super(DeleteNode, self).__init__(model)
        self.layer_path = layer_path
        self.stage = model.stage
        # get undo data
        self.prev_selection = self.model.selection
        self.prev_starts = []
        self.prev_breaks = {}
        self.node_path = node_path
        self.node_data = {}
        self.others = other_removed_nodes

    @processing
    def undo(self):
        layer = self.model.lookup_layer(self.layer_path)
        comp_layer = self.model.comp_layer
        parent = self.node_data['parent']
        # We don't want to fix names because we know this node should be
        # named what it was named when it was deleted
        new_nodes, dirty = self.stage.add_node(name=self.node_data['name'],
                                               data=self.node_data['save_dict'],
                                               parent=parent,
                                               layer=layer.layer_idx(),
                                               comp_layer=comp_layer,
                                               fix_names=False)
        if self.node_data['break']:
            self.model._add_breakpoint(self.node_path, layer)
            self.model._add_breakpoint(self.node_path, self.stage.top_layer)
        if self.node_data['start']:
            self.model._add_start_node(self.node_path, layer)
        # restore layer data
        pos = self.node_data.get('pos')
        if pos:
            self.model.top_layer.positions[self.node_path] = pos
            # This might be a bug? We don't touch the top layer in redo...
            self.undo_effected_layer(self.stage.top_layer.real_path)
        attr_display = self.node_data.get('attr_display')
        if attr_display is not None:
            self.model._set_attr_display_state(self.node_path, attr_display)
        user_dir.breakpoints = self.prev_breaks
        ancestor_tuple = self.node_data.get('ancestor_child_order')
        if ancestor_tuple:
            ancestor_path, ancestor_child_order = ancestor_tuple
            ancestor = layer.lookup(ancestor_path)
            if ancestor:
                setattr(ancestor, INTERNAL_ATTRS.CHILD_ORDER,
                        ancestor_child_order)
        self.model.selection = self.prev_selection
        # Fixme: Does not account for rebuilding proxy nodes for the dirty nodes
        dirty_set = tuple(set(dirty))
        self.undo_effected_layer(self.layer_path)
        if dirty_set != (self.node_path,):
            self.model.update_comp_layer(rebuild=True)
        else:
            self.model.nodes_changed.emit(dirty_set)

    @processing
    def redo(self):
        layer = self.model.lookup_layer(self.layer_path)
        comp_layer = self.model.comp_layer
        self.node_data = {}
        self.prev_starts = self.model.get_start_nodes(layer)
        self.prev_breaks = user_dir.breakpoints
        dirty_nodes = []
        node = layer.lookup(self.node_path)
        # get node info
        parent = getattr(node, INTERNAL_ATTRS.PARENT_PATH)
        name = getattr(node, INTERNAL_ATTRS.NAME)
        is_break = self.model.get_is_node_breakpoint(self.node_path, layer)

        self.node_data = {'parent': parent, 'name': name,
                          'pos': self.model.get_node_pos(self.node_path),
                          'break': is_break}
        closest_ancestor = layer.ancestors(self.node_path)
        if closest_ancestor:
            closest_ancestor = closest_ancestor[0]
        else:
            closest_ancestor = None
        closest_ancestor_path = layer.get_node_path(closest_ancestor)
        if closest_ancestor_path:
            ancestor_child_order = getattr(closest_ancestor,
                                           INTERNAL_ATTRS.CHILD_ORDER)
            self.node_data['ancestor_child_order'] = (closest_ancestor_path,
                                                      ancestor_child_order[:])
        # Attr display data
        attr_display = self.model.get_attr_display_state(self.node_path)
        if attr_display is not None:
            self.node_data['attr_display'] = attr_display
        # get layer data
        is_start = self.model.get_is_node_start(self.node_path, layer)
        self.node_data['start'] = is_start
        self.node_data['save_dict'] = get_node_as_dict(node)

        if self.node_data['break']:
            self.model._remove_breakpoint(self.node_path, layer)
            self.model._remove_breakpoint(self.node_path, self.stage.top_layer)
        if self.node_data['start']:
            self.model._remove_start_node(self.node_path, layer)
        node = layer.lookup(self.node_path)
        source_layer = self.stage.get_node_source_layer(node)
        if source_layer.layer_idx() > 0:
            rm_layer_data = True
        else:
            rm_layer_data = False
        for p in self.others[:]:
            self.others += comp_layer.get_node_dirties(p)
        _, dirty = self.stage.delete_node(node, layer,
                                          comp_layer=comp_layer,
                                          remove_layer_data=rm_layer_data,
                                          other_removed_nodes=self.others)
        dirty_nodes += dirty + [self.node_path]
        if self.node_path in self.model.selection:
            fix_selection = self.model.selection[:]
            fix_selection.remove(self.node_path)
            self.model.selection = fix_selection
        self.model.nodes_changed.emit(tuple(set(dirty_nodes)))
        self.redo_effected_layer(layer.real_path)
        self.setText("Delete node: {}".format(self.node_path))


class SetNodeAttributeData(NxtCommand):

    """Set attribute value"""

    def __init__(self, node_path, attr_name, data, model, layer_path):
        super(SetNodeAttributeData, self).__init__(model)
        self.node_path = node_path
        self.nice_attr_name = attr_name
        self.attr_name = attr_name
        self.data = data
        self.stage = model.stage
        self.layer_path = layer_path
        self.created_node_paths = []
        self.remove_attr = False
        self.prev_data = {}
        self.recomp = attr_name in INTERNAL_ATTRS.REQUIRES_RECOMP
        self.return_value = None
        self.prev_selection = model.selection

    @processing
    def undo(self):
        start = time.time()
        layer = self.model.lookup_layer(self.layer_path)
        self.undo_effected_layer(layer.real_path)
        comp = self.model.comp_layer
        dirties = [self.node_path]
        # delete any created nodes
        for node_path in self.created_node_paths:
            n = layer.lookup(node_path)
            if n is not None:
                self.stage.delete_node(n, layer=layer, comp_layer=comp,
                                       remove_layer_data=False)
        n = layer.lookup(self.node_path)
        if n is not None:
            if self.remove_attr:
                self.stage.delete_node_attr(n, self.attr_name)
                dirties += comp.get_node_dirties(self.node_path)
            else:
                result = self.stage.node_setattr_data(node=n,
                                                      attr=self.attr_name,
                                                      layer=layer, create=False,
                                                      comp_layer=comp,
                                                      **self.prev_data)
                if self.attr_name in (INTERNAL_ATTRS.INSTANCE_PATH,
                                      INTERNAL_ATTRS.ENABLED):
                    dirties += result
        if self.attr_name in INTERNAL_ATTRS.ALL:
            dirties += comp.get_node_dirties(self.node_path)
        changed_attrs = ()
        for dirty in dirties:
            attr_path = nxt_path.make_attr_path(dirty, self.attr_name)
            changed_attrs += (attr_path,)
        if self.recomp:
            self.model.update_comp_layer(rebuild=self.recomp)
        else:
            if (self.remove_attr or self.created_node_paths or
                    self.attr_name in (INTERNAL_ATTRS.INSTANCE_PATH,
                                       INTERNAL_ATTRS.PARENT_PATH,
                                       INTERNAL_ATTRS.ENABLED)):
                self.model.nodes_changed.emit(dirties)
            else:
                self.model.attrs_changed.emit(changed_attrs)
        if not self.recomp:
            changed = tuple([self.node_path] + self.created_node_paths)
            self.model.nodes_changed.emit(changed)
        self.model.selection = self.prev_selection
        # undo_debug(self, start)

    @processing
    def redo(self):
        # start = time.time()
        created_node = False
        self.prev_selection = self.model.selection
        layer = self.model.lookup_layer(self.layer_path)
        self.redo_effected_layer(layer.real_path)
        comp = self.model.comp_layer
        self.remove_attr = False
        self.created_node_paths = []
        # get the node
        node = layer.lookup(self.node_path)
        dirties = [self.node_path]
        if node is None:
            parent_path = nxt_path.get_parent_path(self.node_path)
            name = nxt_path.node_name_from_node_path(self.node_path)
            if self.attr_name in INTERNAL_ATTRS.ALL:
                self.return_value = INTERNAL_ATTRS.as_save_key(self.attr_name)
                attr_data = {self.return_value: self.data.get(META_ATTRS.VALUE)}
            else:
                attr_data = {nxt_io.SAVE_KEY.ATTRS: {self.attr_name: self.data}}
                self.return_value = self.attr_name
            _, dirties = self.stage.add_node(name=name, data=attr_data,
                                             parent=parent_path,
                                             layer=layer.layer_idx(),
                                             comp_layer=comp,
                                             fix_names=False)
            # Fixme: Targeted parenting would avoid the need for a recomp
            if layer.descendants(self.node_path):
                self.recomp = True
            created_node = True
            self.created_node_paths += [self.node_path]
            node = layer.lookup(self.node_path)
        self.prev_data = self.stage.get_node_attr_data(node, self.attr_name,
                                                       layer, quiet=True)
        if self.prev_data:
            self.prev_data = copy.deepcopy(self.prev_data)
        # set attribute value this also adds the attribute if it does not exist
        if not self.stage.node_attr_exists(node, self.attr_name):
            self.remove_attr = True
        if not created_node:
            self.return_value = self.stage.node_setattr_data(node,
                                                             self.attr_name,
                                                             layer=layer,
                                                             create=True,
                                                             comp_layer=comp,
                                                             **self.data)
            if self.attr_name in (INTERNAL_ATTRS.INSTANCE_PATH,
                                  INTERNAL_ATTRS.ENABLED):
                dirties += self.return_value
        if self.attr_name in INTERNAL_ATTRS.ALL:
            # TODO: Some functions already calculated the dirty nodes,
            #  do we really need to do it again here?
            dirties += comp.get_node_dirties(self.node_path)
        if self.recomp:
            self.model.update_comp_layer(rebuild=self.recomp)
        else:
            if (self.remove_attr or self.created_node_paths or
                    self.attr_name in (INTERNAL_ATTRS.INSTANCE_PATH,
                                       INTERNAL_ATTRS.PARENT_PATH,
                                       INTERNAL_ATTRS.ENABLED)):
                self.model.nodes_changed.emit(dirties)
            else:
                changed_attrs = ()
                for dirty in dirties:
                    attr_path = nxt_path.make_attr_path(dirty, self.attr_name)
                    changed_attrs += (attr_path,)
                self.model.attrs_changed.emit(changed_attrs)
        attr_path = nxt_path.make_attr_path(self.node_path, self.nice_attr_name)
        val = str(self.data.get(META_ATTRS.VALUE))
        self.setText("Set {} to {}".format(attr_path, val))
        # redo_debug(self, start)


class SetNodeAttributeValue(SetNodeAttributeData):
    def __init__(self, node_path, attr_name, value, model, layer_path):
        data = {META_ATTRS.VALUE: value}
        super(SetNodeAttributeValue, self).__init__(node_path, attr_name, data,
                                                    model, layer_path)


class RenameNode(SetNodeAttributeValue):

    """Rename node"""
    def __init__(self, node_path, name, model, layer_path):
        self.old_node_path = node_path
        layer = model.lookup_layer(layer_path)
        parent_path = nxt_path.get_parent_path(node_path)
        new_name = model.stage.get_unique_node_name(name=name, layer=layer,
                                                    parent_path=parent_path,
                                                    layer_only=True)
        super(RenameNode, self).__init__(node_path, INTERNAL_ATTRS.NAME,
                                         new_name, model, layer_path)

    def undo(self):
        self.model.about_to_rename.emit()
        self.prev_data['force'] = True
        super(RenameNode, self).undo()
        self.node_path = self.old_node_path
        self.model.selection = [self.node_path]

    def redo(self):
        self.model.about_to_rename.emit()
        super(RenameNode, self).redo()
        self.node_path = self.return_value
        self.model.selection = [self.node_path]
        if self.model.get_is_node_start(self.node_path, self.model.comp_layer):
            self.model.starts_changed.emit(self.model.get_start_nodes())
        self.setText("{} renamed to {}".format(self.old_node_path,
                                               self.return_value))


class DuplicateNodes(NxtCommand):

    """Duplicate nodes on this graph"""

    def __init__(self, node_paths, descendants, model, source_layer_path,
                 target_layer_path):
        # TODO: We should make another base command class that can be used to
        #  set multiple attr's data. That way duplicate can just be a
        #  setattr. The way it works now we can only set one attr's data at a
        #  time and duplicate needs to get local + INTERNAL number of attrs.
        super(DuplicateNodes, self).__init__(model)
        self.node_paths = node_paths
        self.descendants = descendants
        self.source_layer_path = source_layer_path
        self.target_layer_path = target_layer_path
        self.stage = model.stage

        # get undo data
        self.prev_selection = self.model.selection

        # resulting nodes
        self.new_node_paths = []

    @processing
    def undo(self):
        target_layer = self.model.lookup_layer(self.target_layer_path)
        # delete duplicated nodes
        for node_path in self.new_node_paths:
            n = target_layer.lookup(node_path)
            if n is not None:
                self.stage.delete_node(n, target_layer,
                                       remove_layer_data=True)

        self.model.selection = self.prev_selection
        self.model.update_comp_layer(rebuild=True)
        self.undo_effected_layer(target_layer.real_path)

    @processing
    def redo(self):
        new_selection = []
        self.new_node_paths = []
        source_layer = self.model.lookup_layer(self.source_layer_path)
        target_layer = self.model.lookup_layer(self.target_layer_path)
        self.redo_effected_layer(target_layer.real_path)
        for node_path in self.node_paths:
            node = source_layer.lookup(node_path)
            # duplicate node
            new, dirty = self.stage.duplicate_node(node=node,
                                                   layer=target_layer,
                                                   descendants=self.descendants)
            new_selection.append(target_layer.get_node_path(new[0]))

            # process new nodes
            for new_node in new:
                # add new node path to the list and emit model signal
                new_node_path = target_layer.get_node_path(new_node)
                self.new_node_paths += [new_node_path]
                # self.model.node_added.emit(new_node_path)

                # set position
                has_parent = self.model.node_has_parent(new_node_path,
                                                        target_layer)
                if not has_parent and new_node_path != node_path:
                    pos = self.model.get_node_pos(node_path)
                    pos = [pos[0] + 20, pos[1] + 20]
                    self.model._set_node_pos(new_node_path, pos,
                                             layer=target_layer)

        self.model.selection = new_selection
        self.model.update_comp_layer(rebuild=True)
        if len(self.node_paths) == 1:
            nodes_str = self.node_paths[0]
        else:
            nodes_str = 'nodes'
        self.setText('Duplicated {}'.format(nodes_str))


class InstanceNode(SetNodeAttributeValue):

    """Instance nodes on this graph"""

    def __init__(self, node_path, model, source_layer_path, target_layer_path):
        src_name = nxt_path.node_name_from_node_path(node_path)
        parent_path = nxt_path.get_parent_path(node_path)
        new_name = model.stage.get_unique_node_name(src_name,
                                                    model.comp_layer,
                                                    parent_path=parent_path)
        new_path = nxt_path.join_node_paths(parent_path, new_name)
        self.new_path = new_path
        super(InstanceNode, self).__init__(new_path,
                                           INTERNAL_ATTRS.INSTANCE_PATH,
                                           node_path, model, target_layer_path)

    def redo(self):
        node_path = self.data.get(META_ATTRS.VALUE)
        layer = self.model.lookup_layer(self.layer_path)
        new_pos = self.model.get_pos_offset(node_path, (GRID_SIZE * 16, 0),
                                            layer)
        self.model._set_node_pos(self.new_path, new_pos, layer)
        super(InstanceNode, self).redo()
        self.return_value = self.new_path
        self.setText('Instanced {}'.format(self.data.get(META_ATTRS.VALUE)))


class SetNodesPosition(NxtCommand):

    """Move nodes"""

    def __init__(self, node_positions, model, layer_path):
        super(SetNodesPosition, self).__init__(model)
        self.model = model
        self.layer_path = layer_path
        self.new_positions = node_positions
        self.old_positions = {}
        for path in self.new_positions.keys():
            self.old_positions[path] = model.get_node_pos(path)

    @processing
    def undo(self):
        layer = self.model.lookup_layer(self.layer_path)
        for node_path, old_pos in self.old_positions.items():
            self.model._set_node_pos(node_path=node_path,
                                     pos=old_pos, layer=layer)
        self.undo_effected_layer(self.layer_path)

    @processing
    def redo(self):
        delta_str = None
        layer = self.model.lookup_layer(self.layer_path)
        for node_path, new_pos in self.new_positions.items():
            self.model._set_node_pos(node_path=node_path,
                                     pos=new_pos, layer=layer)
            if not delta_str:
                pos = new_pos
                prev_pos = self.old_positions[node_path]
                # Only letting it set text once, relying on consistent delta.
                x_delta = pos[0] - prev_pos[0]
                y_delta = pos[1] - prev_pos[1]
                delta_str = '{}, {}'.format(x_delta, y_delta)
                if len(self.new_positions) == 1:
                    nodes_str = node_path
                else:
                    nodes_str = 'nodes'
                self.setText('Move {} {}'.format(nodes_str, delta_str))
        self.redo_effected_layer(layer.real_path)


class SetSelection(QUndoCommand):

    """Select Nodes and Connections"""
    def __init__(self, paths, model):
        super(SetSelection, self).__init__()
        self.new_paths = paths
        self.model = model
        self.prev_paths = self.model.selection

    def undo(self):
        self.model.selection = self.prev_paths

    def redo(self):
        self.model.selection = self.new_paths
        self.setText('Set selection: {}'.format(str(self.new_paths)))


class AddSelection(SetSelection):
    def __init__(self, paths, model):
        self.added_paths = paths
        curr_selection = model.selection
        new_paths = curr_selection + paths
        super(AddSelection, self).__init__(new_paths, model)

    def redo(self):
        super(AddSelection, self).redo()
        self.setText('Add {} to selection'.format(self.added_paths))


class RemoveFromSelection(SetSelection):
    def __init__(self, paths, model):
        self.rem_paths = paths
        new_selection = model.selection[:]
        for path in paths:
            try:
                new_selection.remove(path)
            except ValueError:
                continue
        super(RemoveFromSelection, self).__init__(new_selection, model)

    def redo(self):
        super(RemoveFromSelection, self).redo()
        self.setText('Remove {} from selection'.format(self.rem_paths))


class LocalizeNodes(NxtCommand):

    """Localize nodes"""

    def __init__(self, node_paths, model):
        super(LocalizeNodes, self).__init__(model)
        self.node_paths = node_paths
        self.model = model
        self.stage = model.stage
        self.prev_selection = self.model.selection
        self.prev_node_data = {}
        self.created_node_paths = []

    @processing
    def undo(self):
        for node_path in self.created_node_paths:
            n = self.model.target_layer.lookup(node_path)
            if n is not None:
                self.stage.delete_node(n, layer=self.model.target_layer,
                                       remove_layer_data=False)
        layers = [self.model.target_layer]
        for node_path, all_data in self.prev_node_data.items():
            apply_data = {}
            node = self.model.target_layer.lookup(node_path)
            if not node:
                continue
            data = all_data['data']
            child_order = all_data['data'].get('child_order', [])
            apply_data['child_order'] = child_order
            apply_data['attributes'] = data.get('attributes', {})
            attrs_to_keep = apply_data['attributes'].keys()
            apply_data['enabled'] = data.get('enabled')
            if data.get('instance'):
                apply_data['instance'] = data['instance']
            self.stage.transfer_node_data(node, self.model.target_layer,
                                          apply_data, self.model.comp_layer)
            local_attrs = self.stage.get_node_local_attr_names(node_path,
                                                               layers)
            for attr in local_attrs:
                if attr not in attrs_to_keep:
                    self.stage.delete_node_attr(node=node, attr_name=attr)
        self.model.update_comp_layer(rebuild=True)
        self.undo_effected_layer(layers[0].real_path)
        self.model.selection = self.prev_selection

    @processing
    def redo(self):
        self.prev_node_data = {}
        self.created_node_paths = []
        layer = self.model.target_layer
        for node_path in self.node_paths:
            node_data = {}
            display_node = self.model.comp_layer.lookup(node_path)
            if not display_node:
                continue
            # add node if it doesn't exist on the target layer
            target_node = self.model.target_layer.lookup(node_path)
            if not target_node:
                new_nodes, new_paths, dirty = _add_node_hierarchy(node_path,
                                                                  self.model,
                                                                  layer)
                target_node = new_nodes[-1]
                self.created_node_paths += new_paths
                # self.model.node_added.emit(node_path)
            # preserve original data
            node_data['data'] = get_node_as_dict(target_node)
            # localize source node
            self.stage.transfer_node_data(target_node, self.model.target_layer,
                                          display_node,
                                          self.model.comp_layer)

            self.prev_node_data[node_path] = node_data
        self.model.update_comp_layer(rebuild=bool(self.created_node_paths))
        self.redo_effected_layer(layer.real_path)
        self.model.selection = self.prev_selection
        if len(self.node_paths) == 1:
            path_str = self.node_paths[0]
        else:
            path_str = str(self.node_paths)
        self.setText('Localize {}'.format(str(path_str)))


class LocalizeUserAttr(SetNodeAttributeData):

    """Localize nodes"""

    def __init__(self, node_path, attr_name, model, layer_path):
        node = model.comp_layer.lookup(node_path)
        data = model.stage.get_node_attr_data(node, attr_name,
                                              model.comp_layer)
        if META_ATTRS.SOURCE in data:
            data.pop(META_ATTRS.SOURCE)
        super(LocalizeUserAttr, self).__init__(node_path, attr_name, data,
                                               model, layer_path)


class LocalizeCompute(SetNodeAttributeValue):

    """Localize nodes"""

    def __init__(self, node_path, model, layer_path):
        comp_layer = model.comp_layer
        display_node = comp_layer.lookup(node_path)
        code_lines = model.stage.get_node_code_lines(display_node, comp_layer)
        super(LocalizeCompute, self).__init__(node_path,
                                              INTERNAL_ATTRS.COMPUTE,
                                              code_lines, model, layer_path)

    def redo(self):
        super(LocalizeCompute, self).redo()
        self.setText("Localize compute on {}".format(self.node_path))


class LocalizeInstancePath(SetNodeAttributeValue):
    def __init__(self, node_path, model, layer_path):
        inst_path = model.get_node_instance_path(node_path, model.comp_layer,
                                                 expand=False)
        super(LocalizeInstancePath, self).__init__(node_path,
                                                   INTERNAL_ATTRS.INSTANCE_PATH,
                                                   inst_path, model, layer_path)

    def redo(self):
        super(LocalizeInstancePath, self).redo()
        self.setText("Localize instance path to {}".format(self.node_path))


class RevertInstancePath(SetNodeAttributeValue):
    def __init__(self, node_path, model, layer_path):
        super(RevertInstancePath, self).__init__(node_path,
                                                 INTERNAL_ATTRS.INSTANCE_PATH,
                                                 None, model, layer_path)

    def redo(self):
        super(RevertInstancePath, self).redo()
        self.setText("Revert instance path on {}".format(self.node_path))


class LocalizeExecPath(SetNodeAttributeValue):
    def __init__(self, node_path, model, layer_path):
        exec_path = model.get_node_exec_in(node_path)
        super(LocalizeExecPath, self).__init__(node_path,
                                               INTERNAL_ATTRS.EXECUTE_IN,
                                               exec_path, model, layer_path)

    def redo(self):
        super(LocalizeExecPath, self).redo()
        self.setText("Localize exec input on {}".format(self.node_path))


class RevertExecPath(SetNodeAttributeValue):
    def __init__(self, node_path, model, layer_path):
        super(RevertExecPath, self).__init__(node_path,
                                             INTERNAL_ATTRS.EXECUTE_IN, None,
                                             model, layer_path)

    def redo(self):
        self.setText("Revert exec input on {}".format(self.node_path))


class RevertNode(DeleteNode):

    """Localize nodes"""

    def __init__(self, node_path, model, layer_path, others):
        super(RevertNode, self).__init__(node_path, model, layer_path, others)
        self.rebuild = False  # Tells the delete command not to re-comp
        self.created_node_paths = []
        self.node_path = node_path

    def undo(self):
        layer = self.model.lookup_layer(self.layer_path)
        # Remove our created empty nodes
        for node_path in self.created_node_paths:
            n = layer.lookup(node_path)
            if n is not None:
                self.stage.delete_node(n, layer, remove_layer_data=False)
        super(RevertNode, self).undo()
        self.model.update_comp_layer(rebuild=True)
        self.model.selection = self.prev_selection

    def redo(self):
        self.created_node_paths = []
        super(RevertNode, self).redo()
        layer = self.model.lookup_layer(self.layer_path)
        # Re-create the node as an empty node
        new_nodes, new_paths, dirty = _add_node_hierarchy(self.node_path,
                                                          self.model, layer)
        self.created_node_paths += new_paths
        self.model.update_comp_layer(rebuild=bool(self.created_node_paths))
        self.model.selection = self.prev_selection
        self.setText('Revert {}'.format(self.node_path))


class ParentNodes(NxtCommand):

    """Parent Nodes"""

    def __init__(self, node_paths, parent_node_path, model):
        super(ParentNodes, self).__init__(model)
        self.parent_node_path = parent_node_path
        self.parent_node = None
        self.model = model
        self.stage = model.stage
        self.node_paths = node_paths
        # resulting nodes
        self.node_path_data = {}
        self.new_node_paths = []
        self.created_node_paths = []
        # get node selection for undo
        self.prev_selection = self.model.selection
        # get previous node data for all child nodes for undo
        self.prev_node_data = {}

    @processing
    def undo(self):
        layer = self.model.target_layer
        self.undo_effected_layer(layer.real_path)
        # undo parent
        common_parent_nodes = {}
        for old_path, node_data in self.prev_node_data.items():
            prev_parent_path = node_data['parent']
            prev_parent_node = layer.lookup(prev_parent_path)
            new_path = self.node_path_data[old_path]
            node = layer.lookup(new_path)
            if prev_parent_path not in list(common_parent_nodes.keys()):
                common_parent_nodes[prev_parent_path] = {node: old_path}
            else:
                common_parent_nodes[prev_parent_path][node] = old_path
            child_order_tuple = node_data.get(INTERNAL_ATTRS.CHILD_ORDER)
            if child_order_tuple:
                ancestor_path, child_order = child_order_tuple
                ancestor = layer.lookup(ancestor_path)
                if ancestor:
                    self.stage.set_node_child_order(ancestor, child_order,
                                                    layer)
            if new_path in list(self.model.top_layer.positions.keys()):
                source_layer = self.stage.get_node_source_layer(node)
                source_layer.positions.pop(new_path)
        for parent_path, nodes_dict in common_parent_nodes.items():
            self.stage.parent_nodes(nodes=list(nodes_dict.keys()),
                                    parent_path=parent_path,
                                    layer=layer)
        for parent_path, nodes_dict in common_parent_nodes.items():
            for node, old_path in nodes_dict.items():
                node_data = self.prev_node_data[old_path]
                # restore name
                prev_name = node_data['name']
                name = getattr(node, INTERNAL_ATTRS.NAME)
                if name != prev_name:
                    self.stage.set_node_name(node, name=prev_name,
                                             layer=layer, force=True)
                # restore position
                if self.parent_node_path != nxt_path.WORLD:
                    prev_pos = node_data['pos']
                    source_layer = self.stage.get_node_source_layer(node)
                    self.model._set_node_pos(old_path, prev_pos,
                                             layer=source_layer)
        # delete any created nodes
        for node_path in self.created_node_paths:
            node = layer.lookup(node_path)
            if node is not None:
                self.stage.delete_node(node, layer)
        idx = 0
        for old_node_path in self.node_paths:
            new_node_path = self.new_node_paths[idx]
            attr_state = self.model.remove_attr_display_state(new_node_path)
            if attr_state is not None:
                self.model._set_attr_display_state(old_node_path, attr_state)
            idx += 1
        self.model.update_comp_layer(rebuild=True)
        self.model.selection = self.prev_selection

    @processing
    def redo(self):
        self.prev_node_data = {}
        self.node_path_data = {}
        self.new_node_paths = []
        self.created_node_paths = []
        nodes = []
        layer = self.model.target_layer
        self.redo_effected_layer(layer.real_path)
        for node_path in self.node_paths:
            node = layer.lookup(node_path)
            name = getattr(node, INTERNAL_ATTRS.NAME)
            parent_path = getattr(node, INTERNAL_ATTRS.PARENT_PATH)
            self.stage.get_node_data(node, layer)
            node_data = self.stage.get_node_data(node, layer)
            node_data['pos'] = self.model.get_node_pos(node_path)
            node_data['name'] = name
            node_data['parent'] = parent_path
            parent_node = layer.lookup(parent_path)
            ancestor_path = parent_path
            child_order = []
            if parent_node:
                child_order = getattr(parent_node,
                                      INTERNAL_ATTRS.CHILD_ORDER)
            else:
                ancestors = layer.ancestors(node_path)
                if ancestors:
                    ancestor = ancestors[0]
                    ancestor_path = layer.get_node_path(ancestor)
                    child_order = self.stage.get_node_child_order(ancestor)
            node_data[INTERNAL_ATTRS.CHILD_ORDER] = [ancestor_path,
                                                     child_order]
            self.prev_node_data[node_path] = node_data
            nodes += [node]
        # get current node hierarchy information for each node. each node
        # path is placed in a list of descendants for each top node so when
        # they are un-parented each node can be placed visually beside it's
        # original top node.
        node_hierarchy_data = {}
        if self.parent_node_path is nxt_path.WORLD:
            for node_path in self.node_paths:
                node = layer.lookup(node_path)
                top_node = self.stage.get_top_node(node,
                                                   self.model.target_layer)
                if top_node is None:
                    top_node = node
                top_node_path = layer.get_node_path(top_node)
                top_node_descendant_list = node_hierarchy_data.get(top_node, [])
                top_node_descendant_list += [node]
                node_hierarchy_data[top_node_path] = top_node_descendant_list
            if not node_hierarchy_data:
                return
        # parent
        self.node_path_data = self.stage.parent_nodes(nodes,
                                                      self.parent_node_path,
                                                      layer)
        self.new_node_paths = list(self.node_path_data.values())
        idx = 0
        for new_node_path in self.new_node_paths:
            old_node_path = self.node_paths[idx]
            attr_state = self.model.remove_attr_display_state(old_node_path)
            if attr_state is not None:
                self.model._set_attr_display_state(new_node_path, attr_state)
            # set position for un-parent
            if self.parent_node_path == nxt_path.WORLD:
                old_root = nxt_path.get_root_path(old_node_path)
                new_pos = self.model.get_pos_offset(old_root, (GRID_SIZE * 14,
                                                               GRID_SIZE),
                                                    self.model.top_layer)
                self.model._set_node_pos(new_node_path, new_pos, layer)
            idx += 1
        self.model.update_comp_layer(rebuild=True)

        self.model.selection = list(self.node_path_data.values())
        if len(self.node_paths) == 1:
            path_str = self.node_paths[0]
        else:
            path_str = str(self.node_paths)
        self.setText("Parent {} to {}".format(path_str, self.parent_node_path))


class AddAttribute(SetNodeAttributeData):

    """Add an attribute to a node."""

    def __init__(self, node_path, attr_name, value, model, layer_path):
        data = {META_ATTRS.VALUE: value}
        super(AddAttribute, self).__init__(node_path, attr_name, data,
                                           model, layer_path)

    def redo(self):
        super(AddAttribute, self).redo()
        self.remove_attr = True
        self.setText("Add {} attr to {}".format(self.attr_name,
                                                self.node_path))


class DeleteAttribute(AddAttribute):

    """Delete attribute on a node"""

    def __init__(self, node_path, attr_name, model, layer_path):
        super(DeleteAttribute, self).__init__(node_path, attr_name, None,
                                              model, layer_path)
        # Get the data to be set if undo is called
        layer = self.model.lookup_layer(self.layer_path)
        node = layer.lookup(self.node_path)
        self.data = self.stage.get_node_attr_data(node, self.attr_name, layer)

    def undo(self):
        super(DeleteAttribute, self).redo()
        layer = self.model.lookup_layer(self.layer_path)
        self.undo_effected_layer(layer.real_path)

    def redo(self):
        # Overload remove attr here to insure attr is deleted
        self.remove_attr = True
        super(DeleteAttribute, self).undo()
        layer = self.model.lookup_layer(self.layer_path)
        self.redo_effected_layer(layer.real_path)
        self.setText("Remove {} attr from {}".format(self.attr_name,
                                                     self.node_path))


class RevertCompute(SetNodeAttributeValue):

    """Revert compute"""

    def __init__(self, node_path, model, layer_path):
        super(RevertCompute, self).__init__(node_path,
                                            INTERNAL_ATTRS.COMPUTE, [], model,
                                            layer_path)

    def redo(self):
        super(RevertCompute, self).redo()
        self.setText("Revert compute on {}".format(self.node_path))


class RenameAttribute(NxtCommand):

    """Rename attribute"""

    def __init__(self, node_path, attr_name, new_attr_name, model, layer_path):
        super(RenameAttribute, self).__init__(model)
        self.node_path = node_path
        self.attr_name = attr_name
        self.new_attr_name = new_attr_name
        self.model = model
        self.stage = model.stage
        self.layer_path = layer_path

    @processing
    def undo(self):
        layer = self.model.lookup_layer(self.layer_path)
        self.rename_attribute(layer, self.new_attr_name, self.attr_name)
        self.undo_effected_layer(layer.real_path)

    @processing
    def redo(self):
        layer = self.model.lookup_layer(self.layer_path)
        self.rename_attribute(layer, self.attr_name, self.new_attr_name)
        self.redo_effected_layer(layer.real_path)

    def rename_attribute(self, layer, attr_name, new_attr_name):

        node = layer.lookup(self.node_path)
        self.stage.rename_node_attr(node, attr_name, new_attr_name, layer)
        self.model.update_comp_layer()
        old_name = nxt_path.make_attr_path(self.node_path, attr_name)
        new_name = nxt_path.make_attr_path(self.node_path, new_attr_name)
        self.setText("Rename {} to {}".format(old_name, new_name))


class SetAttributeComment(SetNodeAttributeData):

    """Set attribute comment"""

    def __init__(self, node_path, attr_name, comment, model, layer_path):
        data = {META_ATTRS.as_save_key(META_ATTRS.COMMENT): comment}
        super(SetAttributeComment, self).__init__(node_path, attr_name, data,
                                                  model, layer_path)

    def redo(self):
        super(SetAttributeComment, self).redo()
        attr_path = nxt_path.make_attr_path(self.node_path, self.nice_attr_name)
        self.setText("Changed comment on {}".format(attr_path))


class SetCompute(SetNodeAttributeValue):

    """Set node code value"""

    def __init__(self, node_path, code_lines, model, layer_path):
        super(SetCompute, self).__init__(node_path,
                                         INTERNAL_ATTRS.COMPUTE,
                                         code_lines, model, layer_path)

    def redo(self):
        super(SetCompute, self).redo()
        self.setText("Changed compute on {}".format(self.node_path))


class SetNodeComment(SetNodeAttributeValue):

    """Set node comment"""

    def __init__(self, node_path, comment, model, layer_path):
        super(SetNodeComment, self).__init__(node_path,
                                             INTERNAL_ATTRS.COMMENT,
                                             comment, model, layer_path)

    def redo(self):
        super(SetNodeComment, self).redo()
        self.setText("Changed comment on {}".format(self.node_path))


class SetNodeInstance(SetNodeAttributeValue):

    """Set node instance"""

    def __init__(self, node_path, instance_path, model, layer_path):
        super(SetNodeInstance, self).__init__(node_path,
                                              INTERNAL_ATTRS.INSTANCE_PATH,
                                              instance_path, model, layer_path)

    def redo(self):
        super(SetNodeInstance, self).redo()
        txt = ("Set inst path on "
               "{} to {}".format(self.node_path,
                                 self.data.get(META_ATTRS.VALUE)))
        self.setText(txt)


class SetNodeEnabledState(SetNodeAttributeValue):

    """Set node enabled state"""

    def __init__(self, node_path, value, model, layer_path):
        super(SetNodeEnabledState, self).__init__(node_path,
                                                  INTERNAL_ATTRS.ENABLED,
                                                  value, model, layer_path)

    def redo(self):
        super(SetNodeEnabledState, self).redo()
        if self.data.get(META_ATTRS.VALUE):
            self.setText("Enabled {}".format(self.node_path))
        else:
            self.setText("Disabled {}".format(self.node_path))


class SetNodeCollapse(NxtCommand):

    """Set the node collapse state"""

    def __init__(self, node_paths, value,
                 model, layer_path):
        super(SetNodeCollapse, self).__init__(model)
        self.node_paths = node_paths
        self.value = value
        self.model = model
        self.stage = model.stage
        self.layer_path = layer_path
        self.prev_values = {}

    @processing
    def undo(self):
        layer = self.model.lookup_layer(self.layer_path)
        self.undo_effected_layer(layer.real_path)
        for node_path, prev_value in self.prev_values.items():
            layer.collapse[node_path] = prev_value
            self.model.comp_layer.collapse[node_path] = prev_value
        self.model.collapse_changed.emit(list(self.prev_values.keys()))

    @processing
    def redo(self):
        layer = self.model.lookup_layer(self.layer_path)
        self.redo_effected_layer(layer.real_path)
        self.prev_values = {}
        for np in self.node_paths:
            self.prev_values[np] = self.model.get_node_collapse(np, layer)
        for node_path in self.node_paths:
            layer.collapse[node_path] = self.value
            self.model.comp_layer.collapse[node_path] = self.value

        self.model.collapse_changed.emit(list(self.prev_values.keys()))
        if len(self.node_paths) == 1:
            path_str = self.node_paths[0]
        else:
            path_str = str(self.node_paths)
        if self.value:
            self.setText("Collapsed {}".format(path_str))
        else:
            self.setText("Expanded {}".format(path_str))


class SetNodeExecuteSources(SetNodeAttributeValue):

    """Set node execute sources"""

    def __init__(self, node_path, exec_source, model, layer_path):
        super(SetNodeExecuteSources, self).__init__(node_path,
                                                    INTERNAL_ATTRS.EXECUTE_IN,
                                                    exec_source, model,
                                                    layer_path)

    def redo(self):
        super(SetNodeExecuteSources, self).redo()
        val = self.data.get(META_ATTRS.VALUE)
        if val is None:
            self.setText("Removed exec input for {}".format(self.node_path))
            return
        self.setText("Set {} exec input to {}".format(self.node_path, val))


class SetNodesAreSkipPoints(QUndoCommand):

    """Set nodes as skip points"""

    def __init__(self, node_paths, to_skip, layer_path, model):
        super(SetNodesAreSkipPoints, self).__init__()
        self.node_paths = node_paths
        self.to_skip = to_skip
        self.model = model
        self.layer_path = layer_path

    @processing
    def redo(self):
        if self.to_skip:
            func = self.model._add_skippoint
        else:
            func = self.model._remove_skippoint
        for node_path in self.node_paths:
            func(node_path, self.layer_path)
        self.model.nodes_changed.emit(tuple(self.node_paths))
        if len(self.node_paths) == 1:
            path_str = self.node_paths[0]
        else:
            path_str = "Multiple nodes"
        if self.to_skip:
            self.setText("Add skippoint to {}".format(path_str))
        else:
            self.setText("Remove skippoint from {}".format(path_str))

    @processing
    def undo(self):
        if not self.to_skip:
            func = self.model._add_skippoint
        else:
            func = self.model._remove_skippoint
        for node_path in self.node_paths:
            func(node_path, self.layer_path)


class SetNodeBreakPoint(QUndoCommand):

    """Set node as a break point"""

    def __init__(self, node_paths, value, model, layer_path):
        super(SetNodeBreakPoint, self).__init__()
        self.node_paths = node_paths
        self.value = value
        self.model = model
        self.layer_path = layer_path

    @processing
    def undo(self):
        layer = self.model.lookup_layer(self.layer_path)
        if not self.value:
            func = self.model._add_breakpoint
        else:
            func = self.model._remove_breakpoint
        for node_path in self.node_paths:
            func(node_path, layer)
        self.model.nodes_changed.emit(tuple(self.node_paths))

    @processing
    def redo(self):
        layer = self.model.lookup_layer(self.layer_path)
        if self.value:
            func = self.model._add_breakpoint
        else:
            func = self.model._remove_breakpoint
        for node_path in self.node_paths:
            func(node_path, layer)
        self.model.nodes_changed.emit(tuple(self.node_paths))
        if len(self.node_paths) == 1:
            path_str = self.node_paths[0]
        else:
            path_str = str(self.node_paths)
        if self.value:
            self.setText("Add breakpoint to {}".format(path_str))
        else:
            self.setText("Remove breakpoint from {}".format(path_str))


class ClearBreakpoints(QUndoCommand):

    """Clear all the breakpoints for a given layer"""

    def __init__(self, model, layer_path):
        super(ClearBreakpoints, self).__init__()
        self.model = model
        self.layer_path = layer_path
        self.prev_breaks = []

    @processing
    def undo(self):
        user_dir.breakpoints[self.layer_path] = self.prev_breaks
        self.model.nodes_changed.emit(tuple(self.prev_breaks))

    @processing
    def redo(self):
        self.prev_breaks = user_dir.breakpoints.get(self.layer_path, [])
        if self.layer_path in list(user_dir.breakpoints.keys()):
            user_dir.breakpoints.pop(self.layer_path)
        self.model.nodes_changed.emit(tuple(self.prev_breaks))
        self.setText("Clear all breakpoints")


class SetNodeStartPoint(SetNodeAttributeValue):

    """Set this node as the execution start point"""

    def __init__(self, node_path, value, model, layer_path):
        super(SetNodeStartPoint, self).__init__(node_path,
                                                INTERNAL_ATTRS.START_POINT,
                                                value, model, layer_path)


class SetNodeChildOrder(SetNodeAttributeValue):

    """Set node child order"""

    def __init__(self, node_path, child_order, model, layer_path):
        super(SetNodeChildOrder, self).__init__(node_path,
                                                INTERNAL_ATTRS.CHILD_ORDER,
                                                child_order, model, layer_path)

    def redo(self):
        super(SetNodeChildOrder, self).redo()
        self.setText("Change child order on {}".format(self.node_path))


class SetLayerAlias(NxtCommand):

    """Set Layer Alias"""

    def __init__(self, alias, layer_path, model):
        super(SetLayerAlias, self).__init__(model)
        self.layer_path = layer_path
        self.alias = alias
        self.old_alias = ''
        self.model = model
        self.stage = model.stage

    @processing
    def undo(self):
        layer = self.model.lookup_layer(self.layer_path)
        if layer is self.model.top_layer:
            layer.set_alias(self.old_alias)
        else:
            layer.set_alias_over(self.old_alias)
        self.undo_effected_layer(self.model.top_layer.real_path)
        self.model.layer_alias_changed.emit(self.layer_path)

    @processing
    def redo(self):
        layer = self.model.lookup_layer(self.layer_path)
        if layer is self.model.top_layer:
            self.old_alias = layer.get_alias(local=True)
            layer.set_alias(self.alias)
        else:
            self.old_alias = layer.get_alias(fallback_to_local=False)
            layer.set_alias_over(self.alias)
        self.redo_effected_layer(self.model.top_layer.real_path)
        self.model.layer_alias_changed.emit(self.layer_path)
        self.setText("Set {} alias to {}".format(layer.filepath, self.alias))


class NewLayer(NxtCommand):

    """Add new layer"""

    def __init__(self, file_path, file_name, idx, model, chdir):
        super(NewLayer, self).__init__(model)
        self.new_layer_path = None
        self.model = model
        self.stage = model.stage
        self.insert_idx = idx
        self.file_path = file_path
        self.file_name = file_name
        self.chdir = chdir

    @processing
    def undo(self):
        new_layer = self.model.lookup_layer(self.new_layer_path)
        if new_layer in self.stage._sub_layers:
            self.undo_effected_layer(new_layer.parent_layer.real_path)
            self.stage.remove_sublayer(new_layer)
        self.model.update_comp_layer(rebuild=True)
        self.model.set_target_layer(LAYERS.TOP)
        self.undo_effected_layer(self.new_layer_path)
        self.model.layer_removed.emit(self.new_layer_path)

    @processing
    def redo(self):
        sub_layer_count = len(self.stage._sub_layers)
        if 0 < self.insert_idx <= sub_layer_count:
            parent_layer = self.stage._sub_layers[self.insert_idx - 1]
            self.redo_effected_layer(parent_layer.real_path)
        else:
            parent_layer = None
        layer_color_index = [str(k.name()) for k in colors.LAYER_COLORS]
        open_layer_colors = []
        for layer in self.stage._sub_layers:
            color = layer.color
            if color:
                color = color.lower()
            open_layer_colors += [color]
        layer_color = layer_color_index[0]
        for c in layer_color_index:
            if c not in open_layer_colors:
                layer_color = c
                break
        real_path = nxt_path.full_file_expand(self.file_path, start=self.chdir)
        layer_data = {"parent_layer": parent_layer,
                      SAVE_KEY.FILEPATH: self.file_path,
                      SAVE_KEY.REAL_PATH: real_path,
                      SAVE_KEY.COLOR: layer_color,
                      SAVE_KEY.ALIAS: self.file_name
                      }
        new_layer = self.stage.new_sublayer(layer_data=layer_data,
                                            idx=self.insert_idx)
        self.new_layer_path = new_layer.real_path
        self.redo_effected_layer(new_layer.real_path)
        # Fixme: The next 2 lines each build once
        self.model.update_comp_layer(rebuild=True)
        self.model.set_target_layer(self.new_layer_path)
        self.model.layer_added.emit(self.new_layer_path)
        self.setText("New layer {}".format(self.new_layer_path))


class ReferenceLayer(NxtCommand):
    """Refernce existing layer"""
    def __init__(self, file_path, idx, model, chdir):
        super(ReferenceLayer, self).__init__(model)
        self.model = model
        self.stage = model.stage
        self.insert_idx = idx
        self.file_path = file_path
        self.real_path = nxt_path.full_file_expand(self.file_path, chdir)

    @processing
    def undo(self):
        new_layer = self.model.lookup_layer(self.real_path)
        if new_layer in self.stage._sub_layers:
            self.undo_effected_layer(new_layer.parent_layer.real_path)
            self.stage.remove_sublayer(new_layer)
        self.model.set_target_layer(LAYERS.TOP)
        self.model.update_comp_layer(rebuild=True)
        self.model.layer_removed.emit(self.real_path)

    @processing
    def redo(self):
        sub_layer_count = len(self.stage._sub_layers)
        if 0 < self.insert_idx <= sub_layer_count:
            parent_layer = self.stage._sub_layers[self.insert_idx - 1]
            self.redo_effected_layer(parent_layer.real_path)
        else:
            parent_layer = None
        layer_data = nxt_io.load_file_data(self.real_path)
        extra_data = {"parent_layer": parent_layer,
                      "filepath": self.file_path,
                      "real_path": self.real_path,
                      "alias": layer_data['name']
                      }
        layer_data.update(extra_data)
        self.stage.new_sublayer(layer_data=layer_data, idx=self.insert_idx)
        # Fixme: The next 2 lines each build once
        self.model.update_comp_layer(rebuild=True)
        self.model.set_target_layer(self.real_path)
        self.model.layer_added.emit(self.real_path)
        self.setText("Added reference to {}".format(self.real_path))


class RemoveLayer(ReferenceLayer):
    """Remove existing layer"""
    def __init__(self, layer_path, model):
        idx = model.lookup_layer(layer_path).layer_idx()
        super(RemoveLayer, self).__init__(layer_path, idx, model, None)
        self.text = "Removed reference to {}".format(layer_path)

    @processing
    def undo(self):
        super(RemoveLayer, self).redo()
        self.setText(self.text)

    @processing
    def redo(self):
        super(RemoveLayer, self).undo()
        self.setText(self.text)


class MuteToggleLayer(NxtCommand):

    """Toggles muting an existing layer"""

    def __init__(self, layer_path, model):
        super(MuteToggleLayer, self).__init__(model)
        self.layer_path = layer_path
        self.model = model
        self.layer_paths = []

    def undo(self):
        self.toggle_state()
        for layer_path in self.layer_paths:
            self.undo_effected_layer(layer_path)

    def redo(self):
        self.layer_paths = []
        self.toggle_state()
        for layer_path in self.layer_paths:
            self.redo_effected_layer(layer_path)

    @processing
    def toggle_state(self):
        layer = self.model.lookup_layer(self.layer_path)
        if layer is self.model.top_layer:
            state = not layer.get_muted(local=True)
            layer.set_muted(state)
            self.layer_paths.append(layer.real_path)
        else:
            state = not layer.get_muted(local=False)
            self.model.top_layer.set_mute_over(layer.filepath, state)
            self.layer_paths.append(self.model.top_layer.real_path)
        self.model.update_comp_layer(rebuild=True)
        self.model.layer_mute_changed.emit((self.layer_path,))
        self.setText("Toggle {} muted.".format(layer.get_alias()))


class SoloToggleLayer(NxtCommand):

    """Toggles soloing an existing layer"""

    def __init__(self, layer_path, model):
        super(SoloToggleLayer, self).__init__(model)
        self.layer_path = layer_path
        self.model = model
        self.layer_paths = []

    def undo(self):
        self.toggle_state()
        for layer_path in self.layer_paths:
            self.undo_effected_layer(layer_path)

    def redo(self):
        self.layer_paths = []
        self.toggle_state()
        for layer_path in self.layer_paths:
            self.redo_effected_layer(layer_path)

    @processing
    def toggle_state(self):
        layer = self.model.lookup_layer(self.layer_path)

        if layer is self.model.top_layer:
            state = not layer.get_soloed(local=True)
            layer.set_soloed(state)
            self.layer_paths.append(layer.real_path)
        else:
            state = not layer.get_soloed(local=False)
            self.model.top_layer.set_solo_over(layer.filepath, state)
            self.layer_paths.append(self.model.top_layer.real_path)
        self.model.update_comp_layer(rebuild=True)
        self.model.layer_solo_changed.emit((self.layer_path,))
        self.setText("Toggle {} soloed.".format(layer.get_alias()))


class SetLayerColor(NxtCommand):
    def __init__(self, color, layer_path, model):
        """Sets the color for a given layer, if the layer is not a top layer
        the top layer store an overrides.
        :param color: string of new layer alias (name)
        :param layer_path: real path of layer
        :param model: StageModel
        """
        super(SetLayerColor, self).__init__(model)
        self.layer_path = layer_path
        self.color = color
        self.old_color = ''
        self.model = model
        self.stage = model.stage

    @processing
    def undo(self):
        layer = self.model.lookup_layer(self.layer_path)
        if layer is self.model.top_layer:
            layer.color = self.old_color
        else:
            layer.set_color_over(self.old_color)
        self.undo_effected_layer(self.model.top_layer.real_path)
        self.model.layer_color_changed.emit(self.layer_path)

    @processing
    def redo(self):
        layer = self.model.lookup_layer(self.layer_path)
        if layer is self.model.top_layer:
            self.old_color = layer.get_color(local=True)
            layer.color = self.color
        else:
            self.old_color = layer.get_color(fallback_to_local=False)
            layer.set_color_over(self.color)
        self.redo_effected_layer(self.model.top_layer.real_path)
        self.model.layer_color_changed.emit(self.layer_path)
        self.setText("Set {} color to {}".format(layer.filepath, self.color))


class SetLayerLock(NxtCommand):
    def __init__(self, lock, layer_path, model):
        """Sets the color for a given layer, if the layer is not a top layer
        the top layer store an overrides.
        :param lock: bool of the desired lock state, if None is passed its
        considered a revert.
        :param layer_path: real path of layer
        :param model: StageModel
        """
        super(SetLayerLock, self).__init__(model)
        self.layer_path = layer_path
        self.lock = lock
        self.old_lock = None
        self.model = model
        self.stage = model.stage
        self.prev_target_layer_path = None

    @processing
    def undo(self):
        layer = self.model.lookup_layer(self.layer_path)
        if layer is self.model.top_layer:
            layer.lock = self.old_lock
        else:
            layer.set_locked_over(self.old_lock)
        self.undo_effected_layer(self.model.top_layer.real_path)
        self.model.layer_lock_changed.emit(self.layer_path)
        if self.prev_target_layer_path:
            prev_tgt = self.model.lookup_layer(self.prev_target_layer_path)
            if prev_tgt != self.model.target_layer:
                self.model._set_target_layer(prev_tgt)

    @processing
    def redo(self):
        layer = self.model.lookup_layer(self.layer_path)
        self.prev_target_layer_path = self.model.get_layer_path(self.model.target_layer, LAYERS.TARGET)
        self.old_lock = layer.get_locked(fallback_to_local=False)
        layer.set_locked_over(self.lock)
        self.redo_effected_layer(self.model.top_layer.real_path)
        self.model.layer_lock_changed.emit(self.layer_path)
        move_tgt = layer == self.model.target_layer
        if move_tgt:
            self.model._set_target_layer(self.model.top_layer)
            logger.warning('You locked your target layer, setting target layer to TOP layer.')
            self.model.request_ding.emit()
        self.setText("Set {} lock to {}".format(layer.filepath, self.lock))


def _add_node_hierarchy(base_node_path, model, layer):
    stage = model.stage
    comp_layer = model.comp_layer
    new_node_paths = []
    new_nodes = []
    node_hierarchy = nxt_path.str_path_to_node_namespace(base_node_path)
    new_node_table, dirty = stage.add_node_hierarchy(node_hierarchy,
                                                     parent=None, layer=layer,
                                                     comp_layer=comp_layer)

    for nn_p, n in new_node_table:
        display_node = comp_layer.lookup(nn_p)
        if display_node is not None:
            display_child_order = getattr(display_node,
                                          INTERNAL_ATTRS.CHILD_ORDER)
            old_child_order = getattr(n, INTERNAL_ATTRS.CHILD_ORDER)
            new_child_order = list_merger(display_child_order,
                                          old_child_order)
            setattr(n, INTERNAL_ATTRS.CHILD_ORDER, new_child_order)
        new_node_paths += [nn_p]
        new_nodes += [n]
    return new_nodes, new_node_paths, dirty


def undo_debug(cmd, start):
    update_time = str(int(round((time.time() - start) * 1000)))
    logger.debug("Undo " + cmd.text() + " | " + update_time + "ms")


def redo_debug(cmd, start):
    update_time = str(int(round((time.time() - start) * 1000)))
    logger.debug(cmd.text() + " | " + update_time + "ms")
