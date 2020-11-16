# Built-in
import os
import json
import copy
import logging
import time
from collections import OrderedDict

# Internal
import nxt_io
import nxt_path
import nxt_node
from . import UNTITLED
from constants import GRAPH_VERSION
from runtime import Console

logger = logging.getLogger(__name__)


class SAVE_KEY(object):
    VERSION = 'version'
    ALIAS = 'alias'
    MUTE = 'mute'
    SOLO = 'solo'
    REFERENCES = 'references'
    COMP_ORVERRIDES = 'comp_overrides'
    COLOR = 'color'
    META_DATA = 'meta_data'
    NODES = 'nodes'
    CWD = 'cwd'
    FILEPATH = 'filepath'
    REAL_PATH = 'real_path'
    ATTRS = 'attrs'
    NAME = 'name'


class META_DATA_KEY(object):
    POSITIONS = 'positions'
    COLLAPSE = 'collapse'
    COLORS = 'colors'
    ALIASES = 'aliases'


class LAYERS(object):
    COMP = '<display>'
    TARGET = '<target>'
    TOP = '<top>'


class AUTHORING:
    CREATE = 'create'
    REFERENCE = 'reference'
    ABOVE = 0
    BELOW = 1


class LayerReturnTypes(object):
    Node = 'Node'  # Return a node or list of nodes
    Path = 'Path'  # Return a node path or list of node paths
    NodeTable = 'NodeTable'  # Return a list of lists [[NodePath, Node]]
    NameDict = 'NameDict'  # Return a dict where k is node NAME and v is node
    PathDict = 'PathDict'  # Return a dict where k is node PATH and v is node
    Boolean = 'Boolean'  # Return if there is at least one child


class SpecLayer(object):
    RETURNS = LayerReturnTypes

    @classmethod
    def load_from_filepath(cls, filepath):
        layer_data = nxt_io.load_file_data(filepath)
        return cls.load_from_layer_data(layer_data)

    @classmethod
    def load_from_layer_data(cls, layer_data):
        return cls(layer_data)

    def __init__(self, layer_data=None):
        if layer_data is None:
            layer_data = {}
        self._cached_children = {}
        self._cached_implied_children = {}
        self._name = UNTITLED
        self._layer_idx = 0
        self.mute = False
        self.solo = False
        self.filepath = layer_data.get(SAVE_KEY.FILEPATH)
        self.real_path = layer_data.get(SAVE_KEY.REAL_PATH)
        self.cwd = layer_data.get(SAVE_KEY.CWD)
        if self.filepath:
            file_name = os.path.basename(self.filepath)
        else:
            file_name = UNTITLED
        self.alias = layer_data.get(SAVE_KEY.ALIAS, file_name)
        self.comp_overrides = layer_data.get(SAVE_KEY.COMP_ORVERRIDES, {})
        self.sub_layer_paths = []
        self.sub_layers = []
        for layer_path in layer_data.get(SAVE_KEY.REFERENCES, []):
            if not layer_path:
                continue
            self.sub_layer_paths += [layer_path]
            self.sub_layers += [{SAVE_KEY.FILEPATH: layer_path}]
        self.parent_layer = layer_data.get('parent_layer', None)
        meta_data = layer_data.get(SAVE_KEY.META_DATA, {})
        self.positions = meta_data.get(META_DATA_KEY.POSITIONS, {})
        self.collapse = meta_data.get(META_DATA_KEY.COLLAPSE, {})
        self.aliases = meta_data.get(META_DATA_KEY.ALIASES, {})
        self.colors = meta_data.get(META_DATA_KEY.COLORS, {})
        self.color = layer_data.get(SAVE_KEY.COLOR, None)
        self.spec_list = []
        self._nodes_path_as_key = {}
        self._nodes_node_as_key = {}
        self._construct_node_specs(layer_data)
        self.refresh()

    def get_cwd(self):
        path = getattr(self, SAVE_KEY.CWD)
        if path:
            return path
        path = self.real_path
        if path:
            return os.path.dirname(path)
        return os.getcwd()

    def _construct_node_specs(self, layer_data):
        self.spec_list = []
        self._nodes_path_as_key = {}
        self._nodes_node_as_key = {}
        nodes = order_nodes_dict(layer_data.get(SAVE_KEY.NODES, {}))
        for node_path, node_data in nodes.items():
            parent_path = nxt_path.get_parent_path(node_path)
            root_name = nxt_path.node_name_from_node_path(node_path)
            node_data['name'] = root_name
            node_data[nxt_node.INTERNAL_ATTRS.SOURCE_LAYER] = self.real_path
            root_spec_node = nxt_node.create_spec_node(node_data, self,
                                                       parent_path=parent_path)
            root_parent_path = getattr(root_spec_node,
                                       nxt_node.INTERNAL_ATTRS.PARENT_PATH)
            root_node_path = nxt_path.join_node_paths(root_parent_path,
                                                      root_name)
            self.spec_list += [root_spec_node]
            self._nodes_path_as_key[root_node_path] = root_spec_node
            self._nodes_node_as_key[root_spec_node] = root_node_path
            self.clear_node_child_cache(root_node_path)

    def refresh(self):
        """Re-populates the node table, and sets nodes' source layer.
        """
        self._node_table = []
        for path, node in self._nodes_path_as_key.items():
            for attr in get_node_local_attr_names(path, [self]):
                source_attr = attr + nxt_node.META_ATTRS.SOURCE
                setattr(node, source_attr, (self.real_path, path))
            node_ns = nxt_path.str_path_to_node_namespace(path)
            self._node_table += [[node_ns, node]]
            self.clear_node_child_cache(path)
        self.sort_node_table()

    def sort_node_table(self):
        self._node_table = sort_multidimensional_list(self._node_table,
                                                      sort_by_idx=0)

    def layer_idx(self):
        return self._layer_idx

    def lookup(self, node_path):
        return self._nodes_path_as_key.get(node_path)

    def node_exists(self, node_path):
        return bool(self.lookup(node_path))

    def get_exec_in(self, node_path):
        node = self.lookup(node_path)
        parent_path = getattr(node, nxt_node.INTERNAL_ATTRS.PARENT_PATH)
        if node and parent_path == nxt_path.WORLD:
            try:
                return getattr(node, nxt_node.INTERNAL_ATTRS.EXECUTE_IN)
            except AttributeError:
                pass
        return None

    def get_node_path(self, node):
        return self._nodes_node_as_key.get(node)

    def ancestors(self, node_path, return_type=LayerReturnTypes.Node,
                  include_implied=False):
        if include_implied and return_type != LayerReturnTypes.Path:
            raise TypeError('When including implied nodes, {} is an '
                            'unsupported return type'.format(return_type))
        if include_implied:
            return nxt_path.all_ancestor_paths(node_path)
        ancestor_nodes = []
        ancestor_paths = []
        node_table = []
        name_dict = {}
        if not isinstance(node_path, (str, unicode)):
            node_path = self.get_node_path(node_path)
        node = self.lookup(node_path)
        parent_path = getattr(node, nxt_node.INTERNAL_ATTRS.PARENT_PATH)
        if node:
            while parent_path != nxt_path.WORLD:
                _node = self.lookup(parent_path)
                if _node is None:
                    parent_path = nxt_path.get_parent_path(parent_path)
                    continue
                if return_type == LayerReturnTypes.Boolean:
                    return True
                elif return_type == LayerReturnTypes.Node:
                    ancestor_nodes += [_node]
                elif return_type == LayerReturnTypes.Path:
                    ancestor_paths += [parent_path]
                elif return_type == LayerReturnTypes.NodeTable:
                    node_table += [[parent_path, _node]]
                elif return_type == LayerReturnTypes.NameDict:
                    key = getattr(node, nxt_node.INTERNAL_ATTRS.NAME)
                    name_dict[key] = _node
                node = _node
                ppath_attr = nxt_node.INTERNAL_ATTRS.PARENT_PATH
                parent_path = getattr(node, ppath_attr)

        if return_type == LayerReturnTypes.Node:
            return ancestor_nodes
        elif return_type == LayerReturnTypes.Path:
            return ancestor_paths
        elif return_type == LayerReturnTypes.NodeTable:
            return node_table
        elif return_type == LayerReturnTypes.NameDict:
            return name_dict
        elif return_type == LayerReturnTypes.Boolean:
            return False

    def children(self, node_path=nxt_path.WORLD,
                 return_type=LayerReturnTypes.Node, ordered=False,
                 include_implied=False):
        if include_implied and return_type != LayerReturnTypes.Path:
            raise ValueError('When including implied, can only return path. '
                             'Nothing else exists for implicit nodes.')
        children_nodes = []
        children_paths = []
        node_table = []
        name_dict = {}
        if not node_path:
            if return_type in (LayerReturnTypes.Node, LayerReturnTypes.Path,
                               LayerReturnTypes.NodeTable):
                return []
            elif return_type == LayerReturnTypes.NameDict:
                return {}
            elif return_type == LayerReturnTypes.Boolean:
                return False
            else:
                logger.error('Invalid return type provided')
                return None
        child_order = []
        implied_children = []
        # Look up real children cache
        children_cache = self._cached_children.get(node_path)
        if node_path == nxt_path.WORLD:
            children_cache = None
        if children_cache is not None:
            children_nodes = children_cache[LayerReturnTypes.Node][:]
            children_paths = children_cache[LayerReturnTypes.Path][:]
            node_table = children_cache[LayerReturnTypes.NodeTable][:]
            name_dict = copy.copy(children_cache[LayerReturnTypes.NameDict])
            cache_real = False
        else:
            self._cached_children[node_path] = {LayerReturnTypes.Node:
                                                children_nodes,
                                                LayerReturnTypes.Path:
                                                children_paths,
                                                LayerReturnTypes.NodeTable:
                                                node_table,
                                                LayerReturnTypes.NameDict:
                                                name_dict}
            cache_real = True
        # Lookup implied cache
        cache_implied = False
        if include_implied:
            implied_c_cache = self._cached_implied_children.get(node_path)
            if node_path == nxt_path.WORLD:
                implied_c_cache = None
            if implied_c_cache is not None:
                implied_children = implied_c_cache[LayerReturnTypes.Path][:]
                if return_type == LayerReturnTypes.Boolean and not cache_real:
                    return bool(implied_children + children_paths)
            else:
                path_implied = {LayerReturnTypes.Path: implied_children}
                self._cached_implied_children[node_path] = path_implied
                cache_implied = True
        re_cache = cache_implied or cache_real
        if re_cache:
            for path, node in self._nodes_path_as_key.items():
                if cache_real:
                    parent_path = getattr(node,
                                          nxt_node.INTERNAL_ATTRS.PARENT_PATH)
                    if parent_path == node_path:
                        children_nodes += [node]
                        children_paths += [path]
                        node_table += [[path, node]]
                        key = getattr(node, nxt_node.INTERNAL_ATTRS.NAME)
                        name_dict[key] = node
                if not include_implied or not cache_implied:
                    continue
                if nxt_path.is_ancestor(path, node_path):
                    trim_depth = nxt_path.get_path_depth(node_path) + 1
                    trimmed = nxt_path.trim_to_depth(path, trim_depth)
                    if trimmed not in implied_children:
                        implied_children += [trimmed]
        if cache_real:
            k = LayerReturnTypes.Path
            self._cached_children[node_path][k] = children_paths[:]
        if include_implied:
            for imp in implied_children:
                if imp not in children_paths:
                    children_paths += [imp]
        if return_type == LayerReturnTypes.Boolean:
            return bool(children_paths)
        if ordered:
            node = self.lookup(node_path)
            if include_implied and not node:
                child_order = []
            else:
                co_attr = nxt_node.INTERNAL_ATTRS.CHILD_ORDER
                child_order = getattr(node, co_attr)
        if child_order:
            ordered_child_nodes = []
            ordered_child_paths = []
            ordered_node_table = []
            for child_name in child_order:
                # return type NODE
                for n in children_nodes:
                    c_name = getattr(n, nxt_node.INTERNAL_ATTRS.NAME)
                    if c_name == child_name:
                        ordered_child_nodes += [n]
                # return type PATH
                for p in children_paths:
                    if nxt_path.node_name_from_node_path(p) == child_name:
                        ordered_child_paths += [p]
                # return type TABLE
                for item in node_table:
                    p, n = item
                    if nxt_path.node_name_from_node_path(p) == child_name:
                        ordered_node_table += [item]
            # return type NODE
            for n in children_nodes:
                if n not in ordered_child_nodes:
                    ordered_child_nodes += [n]
            children_nodes = ordered_child_nodes
            # return type PATH
            for p in children_paths:
                if p not in ordered_child_paths:
                    ordered_child_paths += [p]
            children_paths = ordered_child_paths
            # return type TABLE
            for item in node_table:
                p, n = item
                if p not in ordered_node_table:
                    ordered_node_table += [item]
            node_table = ordered_node_table

        if return_type == LayerReturnTypes.Node:
            return children_nodes
        elif return_type == LayerReturnTypes.Path:
            return children_paths
        elif return_type == LayerReturnTypes.NodeTable:
            return node_table
        elif return_type == LayerReturnTypes.NameDict:
            return name_dict
        elif return_type == LayerReturnTypes.Boolean:
            return False
        else:
            logger.error('Invalid return type provided')
            return None

    def descendants(self, node_path=nxt_path.WORLD,
                    return_type=LayerReturnTypes.Path, ordered=False,
                    include_implied=False):
        if return_type not in (LayerReturnTypes.Node, LayerReturnTypes.Path,
                               LayerReturnTypes.NodeTable,):
            raise TypeError('Unsupported return type {}'.format(return_type))
        if node_path == nxt_path.WORLD:
            if ordered:
                raise ValueError('Cannot get ordered descendants of the world')
            return self._world_descendants(return_type,
                                           include_implied=include_implied)
        if ordered:
            if return_type is not LayerReturnTypes.Path:
                raise ValueError('Ordered descedants can only return paths.')
            return self._ordered_descendants(node_path,
                                             include_implied=include_implied)
        descendants = self.children(node_path, return_type,
                                    include_implied=include_implied)
        more_descendants = descendants
        while more_descendants:
            _temp = []
            if return_type == LayerReturnTypes.Path:
                for d_pth in more_descendants:
                    _temp += self.children(d_pth, return_type,
                                           include_implied=include_implied)
            elif return_type == LayerReturnTypes.NodeTable:
                for d_pth, d in more_descendants:
                    _temp += self.children(d_pth, return_type,
                                           include_implied=include_implied)
            descendants += _temp
            more_descendants = _temp
        return descendants

    def _ordered_descendants(self, node_path, include_implied=False):
        desc = []
        for child_path in self.children(node_path, ordered=True,
                                        return_type=LayerReturnTypes.Path,
                                        include_implied=include_implied):
            desc += [child_path]
            desc += self._ordered_descendants(child_path,
                                              include_implied=include_implied)
        return desc

    def _world_descendants(self, return_type, include_implied=False):
        if include_implied and return_type != LayerReturnTypes.Path:
            raise ValueError('When including implied, can only return path. '
                             'Nothing else exists for implicit nodes.')
        if return_type == LayerReturnTypes.Path:
            paths = self._nodes_path_as_key.keys()
            if nxt_path.WORLD in paths:
                paths.remove(nxt_path.WORLD)
            if not include_implied:
                return paths
            implied_paths = set()
            for real_path in paths:
                ancest_paths = nxt_path.all_ancestor_paths(real_path)
                implied_paths = implied_paths.union(ancest_paths)
            if nxt_path.WORLD in implied_paths:
                implied_paths.remove(nxt_path.WORLD)
            return implied_paths.union(paths)
        if return_type == LayerReturnTypes.Node:
            nodes = self._nodes_node_as_key.keys()
            world_node = self._nodes_path_as_key.get(nxt_path.WORLD)
            if world_node:
                nodes.remove(world_node)
            return nodes
        if return_type == LayerReturnTypes.NodeTable:
            node_table = []
            for path, node in self._nodes_path_as_key.items():
                if path is nxt_path.WORLD:
                    continue
                node_table += [[path, node]]
            return node_table
        raise TypeError('Unsupported return type {}'.format(return_type))

    def clear_node_child_cache(self, node_path):
        try:
            self._cached_children.pop(node_path)
        except KeyError:
            pass
        try:
            self._cached_implied_children.pop(node_path)
        except KeyError:
            pass

    def get_exec_order(self, start_path):
        if start_path == nxt_path.WORLD:
            return []
        start_root_path = nxt_path.get_root_path(start_path)
        exec_order = []
        start_found = False
        root_exec_order = self.get_root_exec_order(start_root_path)
        for root_path in root_exec_order:
            if not start_found and root_path == start_path:
                start_found = True
            node = self.lookup(root_path)
            enabled = nxt_node.get_node_enabled(node)
            if enabled is None:
                enabled = True
            if not enabled:
                continue
            if start_found:
                exec_order += [root_path]
            path_rt_type = LayerReturnTypes.Path
            disabled_desc = []
            for desc_path in self.descendants(node_path=root_path,
                                              ordered=True,
                                              return_type=path_rt_type):
                if not start_found and desc_path == start_path:
                    start_found = True
                desc_node = self.lookup(desc_path)
                enabled = nxt_node.get_node_enabled(desc_node)
                if enabled is None:
                    enabled = True
                if enabled:
                    for potential_ancestor in disabled_desc:
                        if nxt_path.is_ancestor(desc_path, potential_ancestor):
                            enabled = False
                            break
                if not enabled:
                    disabled_desc += [desc_path]
                    continue
                if start_found:
                    exec_order += [desc_path]
        return exec_order

    def get_root_exec_order(self, start_root_path):
        exec_order = [start_root_path]
        prev_root_path = start_root_path
        while True:
            for root in self.children():
                try:
                    exec_in = getattr(root, nxt_node.INTERNAL_ATTRS.EXECUTE_IN)
                    match = exec_in == prev_root_path
                except AttributeError:
                    continue
                if not match:
                    continue
                prev_root_path = self.get_node_path(root)
                exec_order += [prev_root_path]
                break  # for loop
            else:
                break  # while loop
        return exec_order

    def get_muted(self, local=False):
        muted = getattr(self, SAVE_KEY.MUTE, False)
        if not local:
            ref_data = get_comped_layer_overs(self, SAVE_KEY.COMP_ORVERRIDES)
            r_dat = ref_data.get(self.filepath, {})
            muted = r_dat.get(SAVE_KEY.MUTE, muted)
        return muted

    def set_muted(self, state):
        self.mute = state

    def set_mute_over(self, layer_path, state):
        ref_data = get_comped_layer_overs(self, SAVE_KEY.COMP_ORVERRIDES)
        r_dat = ref_data.get(layer_path, {})
        r_dat[SAVE_KEY.MUTE] = state
        ref_data[layer_path] = r_dat
        self.comp_overrides = ref_data

    def get_soloed(self, local=False):
        soloed = getattr(self, SAVE_KEY.SOLO, False)
        if not local:
            ref_data = get_comped_layer_overs(self, SAVE_KEY.COMP_ORVERRIDES)
            r_dat = ref_data.get(self.filepath, {})
            soloed = r_dat.get(SAVE_KEY.SOLO, soloed)
        return soloed

    def set_soloed(self, state):
        self.solo = state

    def set_solo_over(self, layer_path, state):
        ref_data = get_comped_layer_overs(self, SAVE_KEY.COMP_ORVERRIDES)
        r_dat = ref_data.get(layer_path, {})
        r_dat[SAVE_KEY.SOLO] = state
        ref_data[layer_path] = r_dat
        self.comp_overrides = ref_data

    def add_reference(self, layer_path=None, layer=None, insert_idx=None):
        """Given a layer path, a layer object, or both, add a reference to
        specified layer on this layer, optionally at a specified insert index.

        :param layer_path: Path to use as reference path, defaults to None,
        if None is given, defaults to given `layer.real_path`
        :type layer_path: str, optional
        :param layer: layer to add as reference layer in this layer
        :type layer: SpecLayer
        :param insert_idx: index to insert given layer at, defaults to None,
        if None is given, defaults to lowest reference layer.
        :type insert_idx: int, optional
        :return: index given layer was inserted at.
        :rtype: int
        :raises ValueError: If not provided with a layer path or layer.
        """
        if not (layer_path or layer):
            raise ValueError("Must specify layer path or layer to reference.")
        if insert_idx is None:
            insert_idx = len(self.sub_layer_paths)
        if layer_path is None:
            layer_path = layer.real_path
        self.sub_layer_paths.insert(insert_idx, layer_path)
        sub_layer_data = {SAVE_KEY.FILEPATH: layer_path}
        if layer is not None:
            sub_layer_data['layer'] = layer
        self.sub_layers.insert(insert_idx, sub_layer_data)

    def get_references(self):
        refs = []
        for ref in self.sub_layers:
            refs += [ref[SAVE_KEY.FILEPATH]]
        return refs

    def get_alias(self, local=False, fallback_to_local=True):
        """Get the layer's alias (nice name). By default the local alias is
        retuned, if local is False the parent layer's opinion of the alias is
        returned.
        :param local: If True the local opinion is returned, if False the
        strongest override opinion is returned.
        :type local: bool
        :param fallback_to_local: if True and local is False and there is no
        override opinion the local alias is returned. If false and no
        override opinion is found None is returned.
        :return: string of layer alias or None
        """
        alias = getattr(self, SAVE_KEY.ALIAS, None)
        if not local:
            aliases = get_comped_layer_overs(self, META_DATA_KEY.ALIASES)
            if fallback_to_local:
                fallback = alias
            else:
                fallback = None
            alias = aliases.get(self.filepath, fallback)
        return alias

    def set_alias(self, alias):
        self.alias = alias

    def set_alias_over(self, alias):
        """Set a alias override on the root parent of a layer.
        :param alias: new alias string
        """
        layer_path = self.filepath
        root = get_root_parent(self)
        if not root:
            logger.error('Can not set alias override on top layer!')
        if alias is None:
            if layer_path in root.aliases.keys():
                root.aliases.pop(layer_path)
        else:
            root.aliases[layer_path] = alias

    def get_color(self, local=True, fallback_to_local=True):
        """Get the layer's color. By default the local color is
        retuned, if local is False the parent layer's opinion of the alias is
        returned.
        :param local: bool
        :param fallback_to_local: if True and local is False and there is no
        override opinion the local color is returned. If false and no
        override opinion is found None is returned.
        :return: string of layer alias
        """
        color = getattr(self, SAVE_KEY.COLOR, None)
        if not local:
            colors = get_comped_layer_overs(self, META_DATA_KEY.COLORS)
            if fallback_to_local:
                fallback = color
            else:
                fallback = None
            color = colors.get(self.filepath, fallback)
        return color

    def set_color_over(self, color):
        """Set a color override on the root parent of a layer.
        :param color: hex color
        """
        layer_path = self.filepath
        root = get_root_parent(self)
        if not root:
            logger.error('Can not set colors override on top layer!')
        if color is None:
            if layer_path in root.colors.keys():
                root.colors.pop(layer_path)
        else:
            root.colors[layer_path] = color

    def save(self, filepath=None):
        """Save this layer, optionally to new, given filepath.

        :param filepath: file path to save to, defaults to None
        :type filepath: str, optional
        """
        filepath = filepath or self.real_path
        # Update graph name
        graph_name = os.path.splitext(os.path.basename(filepath))[0]
        if self.get_alias(local=True) == UNTITLED:
            self.set_alias(graph_name)
        save_data = self.get_save_data()
        try:
            json.dumps(save_data, indent=4, sort_keys=False)
        except TypeError:
            logger.error("Failed to save file!")
            # TODO: Should raise here, but its out of scope for what I'm
            #  working on right now.
            return
        logger.info("Save Data Generated")
        nxt_io.save_file_data(save_data=save_data, filepath=filepath)
        if filepath != self.real_path:
            self.real_path = filepath
            self.propegate_real_path()
        return save_data

    def get_meta_data(self):
        positions = OrderedDict(sorted(self.positions.items(),
                                       key=lambda x: x[0]))
        collapsed = OrderedDict(sorted(self.collapse.items(),
                                       key=lambda x: x[0]))
        aliases = OrderedDict(sorted(self.aliases.items(), key=lambda x: x[0]))
        colors = OrderedDict(sorted(self.colors.items(), key=lambda x: x[0]))
        meta_data = OrderedDict()
        if aliases:
            meta_data[META_DATA_KEY.ALIASES] = aliases
        if colors:
            meta_data[META_DATA_KEY.COLORS] = colors
        if positions:
            meta_data[META_DATA_KEY.POSITIONS] = positions
        if collapsed:
            meta_data[META_DATA_KEY.COLLAPSE] = collapsed
        return meta_data

    def get_comp_overrides(self):
        return OrderedDict(sorted(self.comp_overrides.items(),
                                  key=lambda x: x[0]))

    def get_save_data(self):
        """Returns save data for this layer.
        """
        save_dict = {
            SAVE_KEY.VERSION: GRAPH_VERSION.VERSION_STR,
            SAVE_KEY.ALIAS: self.get_alias(local=True),
            SAVE_KEY.MUTE: self.get_muted(local=True),
            SAVE_KEY.SOLO: self.get_soloed(local=True),
            SAVE_KEY.REFERENCES: self.get_references(),
            SAVE_KEY.COMP_ORVERRIDES: self.get_comp_overrides(),
            SAVE_KEY.COLOR: self.color,
            SAVE_KEY.META_DATA: self.get_meta_data(),
            SAVE_KEY.NODES: self.get_nodes_save_data()}
        rm = []
        for k, v in save_dict.items():
            if v in ((), [], {}):
                rm += [k]
        for k in rm:
            save_dict.pop(k)
        return self.order_save_dict(save_dict)

    def order_save_dict(self, save_dict):
        """Given a save dictionary, returns an ordered dictionary where the
        save keys are ordered correctly. Leftover keys are put at the end.
        :param data: dictionary to order
        :type data: dict
        :return: ordered version of given dictionary
        :rtype: OrderedDcit
        """
        # order keys
        keys_order = (SAVE_KEY.VERSION, SAVE_KEY.ALIAS, SAVE_KEY.COLOR,
                      SAVE_KEY.MUTE, SAVE_KEY.SOLO, SAVE_KEY.REFERENCES,
                      SAVE_KEY.COMP_ORVERRIDES, SAVE_KEY.META_DATA,
                      SAVE_KEY.NODES, SAVE_KEY.REAL_PATH)

        result = OrderedDict()
        data_keys = save_dict.keys()
        for key in keys_order:
            if key in data_keys:
                result[key] = save_dict[key]
                data_keys.remove(key)
        # leftovers
        for key in data_keys:
            result[key] = save_dict[key]
        return result

    def get_nodes_save_data(self):
        """Gets an ordered dict of all of the spec nodes
        :return: OrderedDict
        """
        nodes_dict = OrderedDict()
        for spec_node in self.spec_list:
            node_data = nxt_node.get_node_as_dict(spec_node)
            node_path = self.get_node_path(spec_node)
            nodes_dict[node_path] = node_data
        return order_nodes_dict(nodes_dict)

    def propegate_real_path(self):
        """Update nodes source layer to current real path
        """
        for node in self.descendants(return_type=LayerReturnTypes.Node):
            setattr(node, nxt_node.INTERNAL_ATTRS.SOURCE_LAYER, self.real_path)


class CompLayer(SpecLayer):
    @classmethod
    def load_from_layer_data(cls, layer_data):
        raise NotImplementedError

    def __init__(self):
        super(CompLayer, self).__init__({})
        self._name = 'CompositeLayer'
        self._layer_range = (0, 0)
        self._dirty_map = {}
        self._sublayer_node_tables = []
        self.runtime = False
        self.running = False
        self._console = Console(_globals={}, _locals={}, node_path='STAGE')
        self.cache_layer = CacheLayer()

    def layer_idx(self):
        return self._layer_range[0]

    def get_node_dirties(self, node_path):
        """Get all nodes that depend on the given node path. The given node
        path will be the 0th item in the return list.
        :param node_path: String of node path
        :return: List of string node paths
        """
        concerns = self._dirty_map.get(node_path, [])[:]
        new_concerns = [node_path] + concerns
        while new_concerns:
            _tmp = []
            for concern in new_concerns:
                found = self._dirty_map.get(concern, [])
                for item in found:
                    if item not in concerns + _tmp:
                        _tmp += [item]
            new_concerns = _tmp
            concerns += _tmp
        return concerns


class CacheLayer(SpecLayer):
    def __init__(self):
        super(CacheLayer, self).__init__({})
        self.nodes = {}
        self.node_time_map = {}
        self.node_times = []

    def was_during_node_exec(self, time_float):
        """Checks if given time float is within any executed node's exec
        timeframe.
        :param time_float: float of time
        :return: bool
        """
        for enter_time, exit_time in reversed(self.node_times):
            if time_float >= enter_time and exit_time is None:
                return True
            if enter_time <= time_float <= exit_time:
                return True
        return False

    def set_node_enter_time(self, node_path, t=0.):
        if not t:
            t = time.time()
        node_runs = self.node_time_map.get(node_path, [])
        time_entry = [[t, None]]
        node_runs += time_entry
        self.node_times += time_entry
        self.node_time_map[node_path] = node_runs

    def set_node_exit_time(self, node_path, t=0.):
        if not t:
            t = time.time()
        try:
            node_runs = self.node_time_map[node_path]
        except IndexError:
            raise IndexError('No start time set for {}'.format(node_path))
        for run_time in node_runs:
            if run_time[1] is None:
                run_time.pop(1)
                run_time += [t]
                return
        raise ValueError('No exec tuples for {} have a missing end '
                         'time!'.format(node_path))

    def get_node_run_time(self, node_path, idx=-1):
        try:
            enter_time, exit_time = self.node_time_map[node_path][idx]
        except (KeyError, IndexError):
            raise ValueError('No time for {} at index {}'.format(node_path,
                                                                 idx))
        return exit_time - enter_time

    def lookup(self, node_path):
        return self.nodes.get(node_path)

    def add_node(self, node_path, node):
        cached_code = getattr(node, nxt_node.INTERNAL_ATTRS.CACHED_CODE, '\n')
        spl_code = cached_code.split('\n')
        setattr(node, nxt_node.INTERNAL_ATTRS.COMPUTE, spl_code)
        self.nodes[node_path] = node

    def save(self, filepath):
        save_data = self.get_save_data()
        nxt_io.save_file_data(save_data=save_data, filepath=filepath)
        return save_data

    def get_save_data(self):
        save_data = {
            'version': GRAPH_VERSION.VERSION_STR,
            'nodes': {}
        }
        for path, node in self.nodes.items():
            save_data['nodes'][path] = nxt_node.get_node_as_dict(node)
        return save_data

    @classmethod
    def load_from_layer_data(cls, layer_data):
        new_layer = cls()
        result_nodes = {}
        name_attr = nxt_node.INTERNAL_ATTRS.NAME
        name_key = nxt_node.INTERNAL_ATTRS.as_save_key(name_attr)
        for node_path, node_data in layer_data.get('nodes', {}).items():
            parent_path = nxt_path.get_parent_path(node_path)
            node_name = nxt_path.node_name_from_node_path(node_path)
            node_data[name_key] = node_name
            spec_node = nxt_node.create_spec_node(node_data, new_layer,
                                                  parent_path)
            code_lines = getattr(spec_node, nxt_node.INTERNAL_ATTRS.COMPUTE)
            code = '\n'.join(code_lines)
            setattr(spec_node, nxt_node.INTERNAL_ATTRS.CACHED_CODE, code)
            result_nodes[node_path] = spec_node
        new_layer.nodes = result_nodes
        return new_layer


def get_active_layers(layers):
    """Given a list of layers, return those that should contribute to comp.

    If there are soloed layers, only the soloed layers that are not muted
    will be returned. If there are not soloed layers, only the non-muted
    layers will be returned.

    :param layers: list of layers to filter
    :type layers: list
    :return: list of layers that should contribute to a comp.
    :rtype: list
    """
    soloed_layers = get_soloed_layers(layers)
    potential_layers = soloed_layers or layers
    result_layers = []
    for layer in potential_layers:
        if layer.get_muted():
            continue
        result_layers += [layer]
    return result_layers


def get_soloed_layers(layers):
    """Given a list of layers, return only those that are soloed

    :param layers: list of layers to filter
    :type layers: list
    :return: list of layers that are soloed.
    :rtype: list
    """
    return [layer for layer in layers if layer.get_soloed()]


def get_muted_layers(layers):
    """Given a list of layers, return only those that are muted

    :param layers: list of layers to filter
    :type layers: list
    :return: list of layers that are muted.
    :rtype: list
    """
    return [layer for layer in layers if layer.get_muted()]


def get_node_local_attr_names(node_path, layers):
    """Get all attribute names that are local to the given node path within
    the given layers.

    NOTE that layers are filtered to active layers.

    :param node_path: node path to find local attributes of
    :type node_path: str
    :param layers: list of layers to look for attributes of given node within
    :type layers: list
    :return: list of local attributes found in given layers
    :rtype: list
    """
    local_attrs = []
    # TODO should we filter for active layers or expect callers to?
    active_layers = get_active_layers(layers)
    for layer in active_layers:
        node = layer.lookup(node_path)
        if not node:
            continue
        for attr in node.__dict__.keys():
            if attr in local_attrs:
                continue
            if attr in nxt_node.INTERNAL_ATTRS.PROTECTED:
                continue
            if attr.endswith(nxt_node.META_ATTRS._suffix):
                continue
            local_attrs += [attr]
    return local_attrs


def get_comped_layer_overs(layer, over_dict_attr):
    over_dict = {}
    over_dict.update(getattr(layer, over_dict_attr, {}))
    parent = layer.parent_layer
    while parent:
        over_dict.update(getattr(parent, over_dict_attr, {}))
        parent = parent.parent_layer
    return over_dict


def get_root_parent(layer):
    parent = layer.parent_layer
    root = None
    while parent:
        root = parent
        parent = parent.parent_layer
    return root


def order_nodes_dict(node_dict):
    """Given a dictionary mapping node paths to node data, return an ordered
    dict where the keys are sorted.

    :param node_dict: dictionary mapping node paths to node data
    :type node_dict: dict
    :return: ordered dctionary with keys sosrted
    :rtype: OrderedDict
    """
    unsorted_paths = node_dict.keys()
    sorted_paths = sorted(unsorted_paths)
    ordered_nodes = OrderedDict()
    for path in sorted_paths:
        ordered_nodes[path] = node_dict[path]
    return ordered_nodes


def sort_multidimensional_list(multi_list, sort_by_idx):
    """Takes a multi-dimensional list and sorts it by the length of a sub-list
    item. The item who's length we sort by is
    determined by the idx parameter.
    If your input is:
    ```
    sort_multidimensional_list(
    [
        [[1,2,3], ['a', 'b']],
        [[4,5,6], ['a']]
    ], idx = 1)
    ```
    Your output will be:
    ```
    [
        [[1,2,3], ['a']],
        [[4,5,6], ['a', 'b']]
    ]
    ```
    :param multi_list: multi-dimensional list
    :param sort_by_idx: Index of sub list item to sort by
    :return: list
    """
    list_len = len(multi_list)
    i = 0
    while i <= list_len:
        ii = 0
        while ii < (list_len - i - 1):
            item_len = len(multi_list[ii][sort_by_idx])
            next_item_len = len(multi_list[ii + 1][sort_by_idx])
            if item_len > next_item_len:
                _temp = multi_list[ii]
                multi_list[ii] = multi_list[ii + 1]
                multi_list[ii + 1] = _temp
            ii += 1
        i += 1
    return multi_list
