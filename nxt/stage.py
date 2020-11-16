# Built-in
import copy
import logging
import os
import re
import sys
import time
import types
from ast import literal_eval
from collections import OrderedDict

# Internal
import nxt_io
import nxt_path
import tokens
from . import DATA_STATE, UNTITLED
from nxt_node import (SpecNode, CompNode, get_node_attr, get_node_as_dict,
                      has_opinion, get_opinion, has_stronger_opinion,
                      get_node_path, get_node_enabled, list_merger,
                      create_spec_node, META_ATTRS, INTERNAL_ATTRS)
from nxt_layer import (SpecLayer, CompLayer, SAVE_KEY, META_DATA_KEY,
                       sort_multidimensional_list, get_active_layers,
                       get_node_local_attr_names)
from tokens import TOKENTYPE, plugin_tokens, Token
from runtime import GraphError, GraphSyntaxError, get_traceback_lineno

logger = logging.getLogger(__name__)


class CompArc(object):
    # Constants
    REFERENCE = 'reference'
    PARENT = 'parent'
    INSTANCE = 'instance'
    ALL_ARCS = (REFERENCE, PARENT, INSTANCE)
    # Comp arc(s) that happen before any hierarchy discovery
    PRE_PROXY_ARCS = [REFERENCE]
    # Comp arcs that happen after hierarchies are discovered and ephemeral
    # nodes are created
    POST_PROXY_ARCS = [PARENT, INSTANCE]
    # Mapping of comp arcs to tuples of attrs that should be brut force comped
    INHERITANCE_MAP = {REFERENCE: (INTERNAL_ATTRS.START_POINT,
                                   INTERNAL_ATTRS.ENABLED,
                                   INTERNAL_ATTRS.EXECUTE_IN,
                                   INTERNAL_ATTRS.INSTANCE_PATH,
                                   INTERNAL_ATTRS.COMMENT,
                                   INTERNAL_ATTRS.COMPUTE),
                       INSTANCE: (INTERNAL_ATTRS.ENABLED,
                                  INTERNAL_ATTRS.COMMENT,
                                  INTERNAL_ATTRS.COMPUTE),
                       PARENT: ()}
    # Mapping of arc to the internal attr that controls it
    ATTR_NAMES = {INSTANCE: INTERNAL_ATTRS.INSTANCE_PATH,
                  PARENT: INTERNAL_ATTRS.PARENT_PATH}

    @staticmethod
    def get_arc(comp_node, node_to_check, comp_layer):
        """
        :param comp_node:
        :param node_to_check:
        :param comp_layer: CompLayer
        :return: CompArc or None
        """
        parent_path = getattr(comp_node, INTERNAL_ATTRS.PARENT_PATH)
        inst_path = getattr(comp_node, INTERNAL_ATTRS.INSTANCE_PATH) or '/'
        comp_path = nxt_path.join_node_paths(parent_path,
                                             getattr(comp_node,
                                                     INTERNAL_ATTRS.NAME))
        check_parent_path = getattr(node_to_check,
                                    INTERNAL_ATTRS.PARENT_PATH) or '/'
        check_name = getattr(node_to_check, INTERNAL_ATTRS.NAME)
        if check_name == nxt_path.WORLD:
            check_path = nxt_path.WORLD
        else:
            check_path = nxt_path.join_node_paths(check_parent_path, check_name)

        if comp_path == check_path:
            return CompArc.REFERENCE
        # Check if instance path is the same as the node_to_check path
        # if it is not we check if the node to check is a descendant of the
        # instant path and finally if all that fails we check if the node to
        # check is in the instance trace. We check in this order to cut down
        # on speed cost as much as possible.
        if parent_path == check_path and nxt_path.is_ancestor(comp_path,
                                                              check_path):
            return CompArc.PARENT
        if (inst_path == check_path or
                nxt_path.is_ancestor(check_path, inst_path) or
                node_to_check in Stage.get_instance_sources(comp_node, [],
                                                            comp_layer)):
            return CompArc.INSTANCE

        return None

    @staticmethod
    def get_bases_arc_dict(comp_node, comp_layer):
        """Returns a dict mapping nodes from the bases tuple to their comp
        arc. If there is no node for an arc its corresponding key will not be
        present in the dict.
        {REFERENCE: [SpecNode, SpecNode],
        PARENT: CompNode,
        INSTANCE: CompNode}
        :param comp_node: CompNode
        :param comp_layer: CompLayer
        :return: dict
        """
        comp_arcs = {}
        for b in comp_node.__bases__:
            arc_name = CompArc.get_arc(comp_node, b, comp_layer)
            if arc_name == CompArc.REFERENCE:
                comp_arcs.setdefault(arc_name, [])
                ref_list = comp_arcs[arc_name]
                ref_list += [b]
                continue
            comp_arcs[arc_name] = b
        return comp_arcs

    class Modes(object):
        REPLACE = 'REPLACE'
        ADD = 'ADD'
        REMOVE = 'REMOVE'


class Stage:
    # TODO: Maybe convert all attr lists to tuples?
    protected_attrs = list(INTERNAL_ATTRS.PROTECTED)
    meta_attrs = META_ATTRS.ALL

    def __init__(self, layer_data=dict, name=UNTITLED):
        """The `Stage` holds a list of sub_layer objects. Its job is to be a
        comp machine and a central api for most data inquiries.
        :param layer_data: Valid dict of a save file
        :param name: Stage name, defaults to the UNTITLED constant
        """
        if layer_data is dict:
            layer_data = {}
        self.debug = False
        self.uid = nxt_uuid(f=True)
        self._sub_layers = []
        self._active_sub_layers = []
        self._filepath = layer_data.get('_filepath', 'untitled.nxt')
        self.cached = None
        self.execute_order = None
        self.current_node = None
        if layer_data:
            self.load_from_file(layer_data)
        else:
            self.new_layer(0, {'name': name})

    @property
    def next_node(self):
        if self.execute_order and self.current_node:
            if self.current_node in self.execute_order:
                index = self.execute_order.index(self.current_node)
                next_index = index + 1
                if next_index < len(self.execute_order):
                    return self.execute_order[next_index]

    @property
    def prev_node(self):
        if self.execute_order and self.current_node:
            if self.current_node in self.execute_order:
                index = self.execute_order.index(self.current_node)
                prev_index = index - 1
                if prev_index > 0:
                    return self.execute_order[prev_index]

    @property
    def filepath(self):
        return self._filepath

    @filepath.setter
    def filepath(self, filepath):
        self._filepath = filepath
        self.top_layer.filepath = filepath

    @property
    def _name(self):
        # TODO: Layers should have a name and an alias
        return self.top_layer.alias

    @_name.setter
    def _name(self, name):
        self.top_layer.alias = name

    @property
    def loaded_files(self):
        return [l.filepath for l in self._sub_layers]

    @property
    def reference_layers(self):
        # TODO: Refactor to "sub_layers"
        return self._sub_layers

    @property
    def top_layer(self):
        # TODO: Refactor to root layer maybe?
        if self._sub_layers:
            return self._sub_layers[0]

    def get_layer(self, layer_alias):
        for layer in self._sub_layers:
            if layer.get_alias() == layer_alias:
                return layer

    def new_sublayer(self, layer_data=None, idx=0):
        new_sublayer = self.new_layer(idx, layer_data=layer_data)
        sub_layer_data = {SAVE_KEY.FILEPATH: new_sublayer.filepath,
                          'layer': new_sublayer}
        # This if/else should get defactored out. It handles fixing the meta
        # data used by the layer manager to display nested layers.
        # I plan to move this into its own function when I add the ability to
        # rearrange layers.
        try:
            parent_layer = new_sublayer.parent_layer
        except AttributeError:
            parent_layer = None
        if parent_layer is not None:
            if new_sublayer.filepath not in parent_layer.sub_layer_paths:
                parent_layer.sub_layer_paths.insert(0, new_sublayer.filepath)
            inserted = False
            for sl_dict in parent_layer.sub_layers:
                if sl_dict[SAVE_KEY.FILEPATH] == new_sublayer.filepath:
                    sl_dict['layer'] = new_sublayer
                    inserted = True
                    break
            if not inserted:
                parent_layer.sub_layers.insert(0, sub_layer_data)
        else:
            for lower_layer in self._sub_layers[idx + 1:]:
                lower_file_path = lower_layer.filepath
                skip = False
                for higher_layer in reversed(self._sub_layers[:idx - 1]):
                    if lower_file_path in higher_layer.sub_layer_paths:
                        skip = True
                        break
                if skip:
                    continue
                lower_real_path = lower_layer.real_path
                lower_sub_layer_data = {SAVE_KEY.FILEPATH: lower_real_path,
                                        'layer': lower_layer}
                if lower_layer.filepath not in new_sublayer.sub_layer_paths:
                    new_sublayer.sub_layer_paths.append(lower_layer.filepath)
                inserted = False
                for sl_dict in new_sublayer.sub_layers:
                    if sl_dict[SAVE_KEY.FILEPATH] == lower_layer.filepath:
                        sl_dict['layer'] = lower_layer
                        inserted = True
                        break
                if not inserted:
                    lower_sub_layer_data['layer'].parent_layer = new_sublayer
                    new_sublayer.sub_layers.append(lower_sub_layer_data)
        # Recursively load sub layers from the new layer
        for ref in new_sublayer.sub_layers:
            if ref.get('layer'):
                continue
            file_path = ref[SAVE_KEY.FILEPATH]
            d = os.path.dirname(layer_data[SAVE_KEY.REAL_PATH])
            real_file_path = nxt_path.full_file_expand(file_path, d)
            deep_sub_layer_data = nxt_io.load_file_data(real_file_path)
            deep_sub_layer_data['parent_layer'] = new_sublayer
            deep_sub_layer_data[SAVE_KEY.FILEPATH] = file_path
            deep_sub_layer_data[SAVE_KEY.REAL_PATH] = real_file_path
            self.new_sublayer(deep_sub_layer_data, idx=idx + 1)
        else:
            new_sublayer.save()
        for idx, sub_layer in enumerate(self._sub_layers):
            sub_layer._layer_idx = idx
        return new_sublayer

    def remove_sublayer(self, layer):
        if isinstance(layer, int):
            layer = self._sub_layers[layer]
        file_path = layer.filepath
        layer_data = layer.sub_layers
        for remove_sub_data in layer_data:
            layer_data.remove(remove_sub_data)
            ref_layer = remove_sub_data.get('layer')
            if not ref_layer:
                continue
            self.remove_sublayer(ref_layer)
        for sub_layer in self._sub_layers:
            if sub_layer is layer:
                continue
            if file_path in sub_layer.sub_layer_paths:
                sub_layer.sub_layer_paths.remove(file_path)
            sub_layer_data = sub_layer.sub_layers
            rm_d = [d for d in sub_layer_data
                    if d[SAVE_KEY.FILEPATH] == file_path]
            for rd in rm_d:
                ref_layer = rd['layer']
                if ref_layer is layer:
                    sub_layer_data.remove(rd)
        if layer in self._sub_layers:
            self._sub_layers.remove(layer)
        for i, layer in enumerate(self._sub_layers):
            layer._layer_idx = i

    @property
    def total_nodes(self):
        total_nodes = 0
        for l in self._sub_layers:
            total_nodes += len(l.spec_list)
        return total_nodes

    @property
    def total_roots(self):
        total_roots = 0
        for l in self._sub_layers:
            total_roots += len(l._children)
        return total_roots

    @staticmethod
    def check_for_layer_ref_cycle(parent_layer, check_layer_path):
        real_path = check_layer_path
        checking_layer = parent_layer
        while checking_layer is not None:
            if checking_layer.real_path == real_path:
                logger.error("Layer reference cycle detected! Layer `{}` "
                             "detected referencing "
                             "its ancestor "
                             "`{}`.".format(parent_layer.real_path, real_path))
                return True
            checking_layer = checking_layer.parent_layer
        return False

    @classmethod
    def load_from_filepath(cls, filepath):
        layer_data = nxt_io.load_file_data(filepath)
        return cls(layer_data=layer_data)

    def load_from_file(self, layer_data, parent_layer=None):
        """Loads from filepath into a layer. Calls itself for sub-layers it finds.
        :param layer_data: Clean dict of an nxt save file
        :param parent_layer: `Layer` object that this layer will be
        sub-layered under.
        If you are creating a top layer it should be `None`
        :return: Layer object
        """
        if not layer_data:
            raise Exception("No layer data provided!")
        real_path = layer_data['real_path']
        layer_data['parent_layer'] = parent_layer
        logger.info('Opening file: ' + real_path)
        parent_layer = self.new_layer(len(self._sub_layers), layer_data)
        if not parent_layer:
            return
        # chdir allows recursive loads to use paths relative to parent file.
        old_cwd = os.getcwd()
        os.chdir(os.path.dirname(real_path))
        for sub_layer_path in layer_data.get(SAVE_KEY.REFERENCES, []):
            try:
                layer_data = nxt_io.load_file_data(sub_layer_path)
                if not layer_data:
                    continue
            except IOError as e:
                logger.error(e)
                logger.error("Failed to open reference layer in file: "
                             "\"{}\"".format(real_path))
                try:
                    parent_layer.sub_layer_paths.remove(sub_layer_path)
                except ValueError:
                    pass
                bad_layer_dat = []
                for sub_layer_dat in parent_layer.sub_layers:
                    if sub_layer_dat.get(SAVE_KEY.FILEPATH) == sub_layer_path:
                        bad_layer_dat += [sub_layer_dat]
                for dat in bad_layer_dat:
                    parent_layer.sub_layers.remove(dat)
                continue
            self.load_from_file(layer_data, parent_layer=parent_layer)
        os.chdir(old_cwd)

    def get_layer_save_data(self, layer_idx):
        layer = self._sub_layers[layer_idx]
        return layer.get_save_data()

    @staticmethod
    def stash_node(node):
        """Converts node into dict of {'attr': 'value'}. Builtin object attrs are
        skipped. Dir is used to get the attr names so both NodeSpec and
        CompNode objects work.
        :param node: NodeSpec or CompNode
        :return: dict
        """
        data = {}
        for k in dir(node):
            if k in INTERNAL_ATTRS.BUILTINS:
                continue
            data[k] = getattr(node, k)
        return data

    def get_stash_data(self, layer):
        """Parses every descendant of a layer and gets the stash data for
        each node. It returns a dict of {'node/path': {'attr': 'value'}}.
        :param layer: SpecLayer or CompLayer
        :return: dict
        """
        comp_data = {}
        r = layer.RETURNS.NodeTable
        for path, node in layer.descendants(return_type=r):
            data = self.stash_node(node)
            comp_data[path] = data
        return comp_data

    @staticmethod
    def legalize_name(name):
        """Returns given `name` without leading numeral, and matching
        `\w` regex: (a-z, A-Z, 0-9, _)
        Replaces illegal characters with underscore.
        """
        if name[0].isdigit():
            name = '_' + name
        pattern = re.compile(r'\W')
        return re.sub(pattern, '_', name)

    def get_unique_node_name(self, name, layer, parent_path=None,
                             layer_only=False):
        """Get an unused node name. If given a name preference, the resulting
        name will increment an integer if needed to create a unique name. If
        layer only is False and the layer provided is not a comp layer a
        re-comp will be executed. Because its slow a full re-comp will only
        be kicked off if the layer arg is a spec layer and the layer only
        kwarg is false.
        Bear in mind that calling this function does not reserve that name
        for future use, so if the name is not used before this function is
        called again before a name is used, it may produce duplicate results.
        :param name: The name that is desired.
        :type name: str
        :param layer: Layer object used as context for a unique name
        :type layer: SpecLayer or CompLayer
        :param parent_path: the given name preference will be tested against
        this node's children's names
        :type parent_path: str
        :param layer_only: If false a new comp layer will be created (slow)
        :type layer_only: bool
        :return: an unused node name.
        :rtype: str
        """
        # validate potential name
        if name is not None:
            name = self.legalize_name(name)
            # cannot be in the illegal node name list below
            illegal_node_names = ['__name__']
            if name in illegal_node_names:
                name = name + '1'
        else:
            name = 'node'
        if not layer_only and isinstance(layer, SpecLayer):
            layer = self.build_stage(from_idx=0)
        test_path = nxt_path.join_node_paths(parent_path, name)
        if not layer.lookup(test_path):
            # Already unique
            return name
        # Find valid name by incrementing trailing number as needed.
        trailing_num = 1
        test_name = name
        while True:
            test_ns = nxt_path.join_node_paths(parent_path, test_name)
            if not layer.lookup(test_ns):
                break
            trailing_num += 1
            test_name = name + str(trailing_num)
        return test_name

    def get_unique_attr_name(self, node_path, layer, attr_name=None):
        """Returns a unique attr name after comparing preferred name to given
        node's existing attr names.
        :param node_path: Node containing attrs to check
        :type node_path: str
        :param layer: Layer object
        :type layer: SpecLayer or CompLayer
        :param attr_name: Preferences for name of new attr
        :type attr_name: str | None
        :return: valid attribute name
        :rtype: str
        """
        # validate attribute attr_name
        # TODO: Validate not shadowing
        if attr_name is not None:
            attr_name = self.legalize_name(attr_name)
        else:
            attr_name = 'attr'

        # handle attr_name collisions with other attributes on the given node
        # by appending a digit
        if isinstance(layer, CompLayer):
            s, e = layer._layer_range
            layers = self._sub_layers[s:e]
        else:
            layers = [layer]
        base_name = attr_name.rstrip('0123456789')
        trailing_digits = attr_name[len(base_name):]
        if trailing_digits:
            num_suffix = int(trailing_digits)
        else:
            num_suffix = 1
        test_name = attr_name
        while True:
            illegal_names = tuple(get_node_local_attr_names(node_path, layers))
            illegal_names += INTERNAL_ATTRS.PROTECTED
            if test_name not in illegal_names:
                break
            num_suffix += 1
            test_name = base_name + str(num_suffix)

        return test_name

    def add_node_hierarchy(self, node_hierarchy, parent=None, layer=None,
                           comp_layer=None):
        layer = layer or self.top_layer
        node_hierarchy_names = node_hierarchy
        created_node_table = []
        dirty_nodes = []
        # Create nodes
        i = 0
        for node_name in node_hierarchy_names:
            node_ns = node_hierarchy[:i + 1]
            node_path = nxt_path.node_namespace_to_str_path(node_ns)
            node = layer.lookup(node_path)
            if node:
                node = self.get_node_spec(node)
                parent = node
                dirty_nodes += [node_path]
            else:
                nodes, _dirty_nodes = self.add_node(name=node_name,
                                                    parent=parent,
                                                    layer=layer,
                                                    comp_layer=comp_layer,
                                                    fix_names=False)
                parent = nodes[0]
                # We know the nodes list will only have 1 node in it because
                # we didn't send a data dict with children
                created_node_table += [[node_path, nodes[0]]]
                dirty_nodes += _dirty_nodes
            i += 1
        layer.refresh()
        return created_node_table, dirty_nodes

    @staticmethod
    def add_node_to_comp_layer(path, comp_node, comp_layer, ns=None,
                               add_to_child_order=True):
        """Simply deals with adding a comp node to the comp layer. This
        method does not deal with adjusting the node's base classes tuple.
        Note: this method does not extend the dirty map.
        :param path: Node path of the node to add
        :param comp_node: CompNode object
        :param comp_layer: CompLayer
        :param ns: Optional namespace list (saves time if provided)
        :param add_to_child_order: If true the new node's name will be added
        to its parent's child order.
        :return: CompNode
        """
        is_comp_node = comp_node.__name__ == CompNode.__name__
        if not is_comp_node:
            comp_node = CompNode.new(spec_node=comp_node)
        if ns is None:
            ns = nxt_path.str_path_to_node_namespace(path)
        name = getattr(comp_node, INTERNAL_ATTRS.NAME)
        comp_layer._node_table += [[ns, comp_node]]
        comp_layer._nodes_path_as_key[path] = comp_node
        comp_layer._nodes_node_as_key[comp_node] = path
        comp_layer.clear_node_child_cache(path)
        parent_node = None
        parent_path = getattr(comp_node, INTERNAL_ATTRS.PARENT_PATH)
        comp_layer.clear_node_child_cache(parent_path)
        if add_to_child_order:
            parent_node = comp_layer.lookup(parent_path)
        if parent_node is not None:
            child_order = getattr(parent_node, INTERNAL_ATTRS.CHILD_ORDER)
            if name not in child_order:
                new_co = list_merger(child_order, [name])
                setattr(parent_node, INTERNAL_ATTRS.CHILD_ORDER, new_co)
        return comp_node

    def add_node(self, name='node', data=None, parent=None, layer=None,
                 fix_names=True, comp_layer=None):
        """Add a new node to this graph. If nothing is specified,
        an empty node is created. If no layer index is given the stage top
        layer is used. The preferred name will be changed if it
        clashes with an existing used name. Unless fix names is False.
        :param name: Preferred name for the new node
        :type name: str
        :param data: Data for the new node
        :type data: dict
        :param parent: String of node path or Node object which will be cast
        to a node path.
        :type parent: NodeSpec or string
        :param layer: Layer object or layer index.
        :type layer: SpecLayer or int
        :param fix_names: If True the input name will be made unique
        :type fix_names: bool
        :param comp_layer: Layer to do a targeted re-comp on
        :type comp_layer: CompLayer
        :returns: NodeSpec
        """
        start = time.time()
        # List for nodes who become dirty in while we add a node
        dirty_nodes = []
        if layer is None:
            layer = self.top_layer
        elif isinstance(layer, int):
            try:
                layer = self._sub_layers[layer]
            except IndexError:
                logger.error("Invalid layer idx {}, "
                             "using top layer.".format(layer))
                layer = self.top_layer
        elif isinstance(layer, CompLayer):
            logger.error("Comp layers are not a valid layer arg type, "
                         "defaulting to top layer.")
            layer = self.top_layer
        # Validate comp layer
        is_comp_layer = False
        if comp_layer:
            is_comp_layer = isinstance(comp_layer, CompLayer)
        do_targeted_comp = comp_layer and is_comp_layer
        # Default parent path is WORLD
        parent_path = nxt_path.WORLD
        # get parent
        if not isinstance(parent, basestring):
            if parent and isinstance(parent, SpecLayer):
                parent_path = nxt_path.WORLD
            elif parent:
                parent = self.get_node_spec(parent)
                parent_name = getattr(parent, INTERNAL_ATTRS.NAME)
                parent_p_path = getattr(parent, INTERNAL_ATTRS.PARENT_PATH)
                parent_path = nxt_path.join_node_paths(parent_p_path,
                                                       parent_name)
        else:
            parent_path = parent
        # create node
        if fix_names:
            name = self.get_unique_node_name(name=name,
                                             layer=comp_layer or layer,
                                             parent_path=parent_path,
                                             layer_only=bool(comp_layer))
        data = data or {}
        data['name'] = name
        if do_targeted_comp:
            key = INTERNAL_ATTRS.as_save_key(INTERNAL_ATTRS.CHILD_ORDER)
            child_order = data.get(key)
        else:
            child_order = None
        new_node = create_spec_node(data, layer, parent_path=parent_path)
        new_nodes = [new_node]
        node_parent_path = getattr(new_node, INTERNAL_ATTRS.PARENT_PATH)
        node_path = nxt_path.join_node_paths(node_parent_path, name)
        layer.spec_list.append(new_node)
        layer._nodes_path_as_key[node_path] = new_node
        layer._nodes_node_as_key[new_node] = node_path
        layer.clear_node_child_cache(node_path)
        layer.clear_node_child_cache(node_parent_path)
        node_ns = nxt_path.str_path_to_node_namespace(node_path)
        layer._node_table += [[node_ns, new_node]]
        setattr(new_node, INTERNAL_ATTRS.SOURCE_LAYER, layer.real_path)
        new_path = layer.get_node_path(new_node)
        logger.info("Added node: " + new_path, links=[new_path])
        if not do_targeted_comp:
            return_nodes = new_nodes
            dirty_children = [get_node_path(n) for n in
                              layer.children(node_path)]
            new_children = []
            for child_data in data.get('children', []):
                # Children will get the same fix names arg value as the parent
                child_name = child_data.get('name')
                _new_nodes, child_dirties = self.add_node(name=child_name,
                                                          data=child_data,
                                                          parent=new_node,
                                                          layer=layer,
                                                          fix_names=fix_names)
                new_children += _new_nodes
                dirty_children += child_dirties
            return_nodes += new_children
            # Early exit if no/invalid comp layer
            return return_nodes, [new_path] + dirty_children
        comp_layer.clear_node_child_cache(node_path)
        return_nodes = new_nodes
        comp_node = self.targeted_comp_pre_proxies(spec_node=new_node,
                                                   new_node_path=node_path,
                                                   comp_layer=comp_layer,
                                                   target_layer=layer)
        proxy_map = self.targeted_comp_proxies(comp_node=comp_node,
                                               node_path=new_path,
                                               comp_layer=comp_layer)
        dirty_nodes = self.targeted_comp_post_proxies(proxy_map=proxy_map,
                                                      comp_layer=comp_layer)
        new_children = []
        for child_data in data.get('children', []):
            # Children will get the same fix names arg value as the parent
            child_name = child_data.get('name')
            _new_nodes, child_dirties = self.add_node(name=child_name,
                                                      data=child_data,
                                                      parent=new_node,
                                                      layer=layer,
                                                      comp_layer=comp_layer,
                                                      fix_names=fix_names)
            new_children += _new_nodes
            dirty_nodes += child_dirties
        return_nodes += new_children
        if child_order is not None:
            dirty_nodes += self.set_node_child_order(new_node,
                                                     child_order,
                                                     target_layer=layer,
                                                     comp_layer=comp_layer)
        dirty_nodes = list(set(dirty_nodes))
        update_time = str(int(round((time.time() - start) * 1000)))
        dirty_count = str(len(dirty_nodes))
        debug = "Time add node(s): " + update_time + "ms | " + dirty_count + \
                " node(s) are now dirty"
        logger.debug(debug)
        return return_nodes, dirty_nodes

    def duplicate_node(self, node=None, layer=None, descendants=True):
        """Duplicates a given node spec and returns a list of the nodes created.
        Multiple nodes can be created if the target and comp layer are
        not the same and descendants is set to True.
        :param node: NodeSpec object
        :param layer: Layer object on which the duplicated node
        should be created
        :param descendants: If true node descendants will be duplicated
        on the target layer
        :return: list of node specs created
        """
        if not node:
            return []
        node = self.get_node_spec(node)
        created_nodes = []
        dirty_nodes = []
        name = getattr(node, INTERNAL_ATTRS.NAME)
        parent_path = getattr(node, INTERNAL_ATTRS.PARENT_PATH)
        parent = layer
        if parent_path == '':
            # This should only happen when duplicating world node.
            parent_path = nxt_path.WORLD
            if descendants:
                logger.error("Cannot duplicate descendants of world node")
                descendants = False
        if parent_path is not nxt_path.WORLD:
            parent = layer.lookup(parent_path)
            if not parent:
                parent_ns = nxt_path.str_path_to_node_namespace(parent_path)
                node_table, dirty = self.add_node_hierarchy(parent_ns,
                                                            parent=None,
                                                            layer=layer)
                # Extract nodes from node table
                nn = [n[1] for n in node_table]
                dirty_nodes += dirty
                created_nodes += nn
                parent = created_nodes[-1]

        data = get_node_as_dict(node)
        new_nodes, dirty = self.add_node(name=name, data=data, parent=parent,
                                         layer=layer.layer_idx())
        dirty_nodes += dirty
        created_nodes += new_nodes

        def dupe_descendants(new_parent, ref_parent, layer):
            ref_path = layer.get_node_path(ref_parent)
            created = []
            dirty = []
            for ref_child in layer.children(ref_path):
                name = getattr(ref_child, INTERNAL_ATTRS.NAME)
                data = get_node_as_dict(ref_child)
                parent = new_parent
                lay_idx = layer.layer_idx()
                new, new_dirty = self.add_node(name=name, data=data,
                                               parent=parent, layer=lay_idx)
                dirty += new_dirty
                created += new
                desc_parent = new[-1]
                new_desc, desc_dirty = dupe_descendants(desc_parent, ref_child,
                                                        layer)
                dirty += desc_dirty
                created += new_desc
            return created, dirty
        if descendants:
            desc_created, desc_dirty = dupe_descendants(new_nodes[-1], node,
                                                        layer)
            dirty_nodes += desc_dirty
            created_nodes += desc_created
        return created_nodes, dirty_nodes

    def delete_node(self, node, layer, comp_layer=None, remove_layer_data=True,
                    delete_descendants=False, other_removed_nodes=None):
        """Deletes the given spec node. Returns a bool of success and a list
        of dirty node paths. If a comp layer is provided deleted nodes are
        removed from the dirty map.
        :param node: SpecNode
        :param layer: SpecLayer
        :param comp_layer: CompLayer
        :param remove_layer_data: If true, start, position, and collapse data
        is removed from the layer(s)
        :param delete_descendants: If true all descendants are deleted as well
        :param other_removed_nodes: A list of other node paths that are going
        to be deleted in the same event loop as the given node.
        Has no effect if comp_layer is None.
        :type other_removed_nodes: list (must be list not tuple)
        :return: (bool, list)
        """
        if not node:
            logger.debug('Cannot delete, node {} is invalid'.format(node))
            return False, []
        if not isinstance(layer, SpecLayer):
            logger.error("You can not delete nodes from this layer type!"
                         " {}".format(type(layer)))
            return False, []
        if not other_removed_nodes:
            other_removed_nodes = []
        node_parent_path = getattr(node, INTERNAL_ATTRS.PARENT_PATH)
        name = getattr(node, INTERNAL_ATTRS.NAME)
        node_path = nxt_path.join_node_paths(node_parent_path, name)
        remove_node_paths = [node_path]
        descendants = layer.descendants(node_path, layer.RETURNS.Path,
                                        include_implied=True)
        if delete_descendants:
            remove_node_paths += descendants
        specs_to_remove = []
        # Fixme: Does not account for deleting child proxy nodes
        for remove_path in remove_node_paths:
            remove_node = layer.lookup(remove_path)
            specs_to_remove += [remove_node]
            layer.spec_list.remove(remove_node)
            rm_parent_path = getattr(remove_node, INTERNAL_ATTRS.PARENT_PATH)
            layer._nodes_path_as_key.pop(remove_path)
            layer._nodes_node_as_key.pop(remove_node)
            layer.clear_node_child_cache(node_path)
            layer.clear_node_child_cache(rm_parent_path)
            parent_node = layer.lookup(rm_parent_path)
            if parent_node:
                new_child_order = getattr(parent_node, INTERNAL_ATTRS.CHILD_ORDER)
                rm_name = getattr(remove_node, INTERNAL_ATTRS.NAME)
                pop_from_co = delete_descendants or not descendants
                if rm_name in new_child_order and pop_from_co:
                    new_child_order.remove(rm_name)
            if remove_layer_data:
                try:
                    layer.positions.pop(remove_path)
                except KeyError:
                    pass
                try:
                    layer.collapse.pop(remove_path)
                except KeyError:
                    pass
        layer.refresh()
        if comp_layer is None:
            return True, remove_node_paths
        idx = 0
        comps_to_remove = []
        dirty_nodes = []
        proxies_to_keep = []
        paths_to_keep = []
        for remove_path in remove_node_paths:
            comp_node = comp_layer.lookup(remove_path)
            spec_node = specs_to_remove[idx]
            other_specs = []
            dirties = comp_layer.get_node_dirties(remove_path)
            dirty_nodes += dirties
            for base in comp_node.__bases__:
                is_comp_node = base.__name__ == CompNode.__name__
                if is_comp_node:
                    break
                if self.get_node_source_layer(base) is not layer:
                    other_specs += [base]
            if not other_specs or getattr(comp_node, INTERNAL_ATTRS.PROXY):
                parent_path = nxt_path.get_parent_path(remove_path)
                parent_node = comp_layer.lookup(parent_path)
                parent_inst = getattr(parent_node,
                                      INTERNAL_ATTRS.INSTANCE_PATH, None)
                rt = comp_layer.RETURNS.NameDict
                parent_inst_children = comp_layer.children(parent_inst,
                                                           return_type=rt)
                node_name = getattr(comp_node, INTERNAL_ATTRS.NAME)
                if node_name in parent_inst_children.keys():
                    inst_src = getattr(comp_node, INTERNAL_ATTRS.INSTANCE_PATH)
                    if inst_src not in other_removed_nodes:
                        proxies_to_keep += [(inst_src, remove_path)]
                        paths_to_keep += [remove_path]
                # This node path no longer exists
                comps_to_remove += [[remove_path, comp_node, dirties]]
                idx += 1
                continue
            bases_list = [b for b in comp_node.__bases__ if b is not spec_node]
            old_child_order = self.get_node_child_order(comp_node)
            new_child_order = []
            for b in bases_list:
                arc = CompArc.get_arc(comp_node, b, comp_layer)
                if arc == CompArc.PARENT:
                    continue
                base_co = self.get_node_child_order(b)
                new_child_order = list_merger(base_co, new_child_order)
            self._replace_base_classes(comp_node, tuple(bases_list))
            if old_child_order != new_child_order:
                setattr(comp_node, INTERNAL_ATTRS.CHILD_ORDER, new_child_order)
                self.propagate_child_order(remove_path, old_child_order,
                                           new_child_order, comp_layer)
            dirty_nodes += [remove_path]
            idx += 1
        for path, comp_node, dirties in comps_to_remove:
            _dirty, deleted = self.ripple_delete(path, comp_node, layer,
                                                 comp_layer, dirties)
            if path in paths_to_keep:
                for item in deleted:
                    if item not in proxies_to_keep:
                        proxies_to_keep += [item]
            dirty_nodes += _dirty
        # Remove from dirty map after everything since the loop above
        # needs the dirty map intact
        for path, _, _ in comps_to_remove:
            remove_dirty_map = None
            for concern in comp_layer.get_node_dirties(path):
                node = comp_layer.lookup(concern)
                remove_dirty_map = not node and getattr(node,
                                                        INTERNAL_ATTRS.PROXY,
                                                        False)
            if remove_dirty_map:
                self.remove_from_dirty_map(path, comp_layer._dirty_map)
        restored_proxies = []
        for inst_src, path in proxies_to_keep:
            proxy = self.create_instance_node(inst_src, path, comp_layer)
            restored_proxies += [proxy]
            proxy_map = self.targeted_comp_proxies(proxy, path, comp_layer)
            self.targeted_comp_post_proxies(proxy_map, comp_layer)
            if path in other_removed_nodes:
                rm = comp_layer.get_node_dirties(path) + [path]
                for r in rm:
                    if r in other_removed_nodes:
                        other_removed_nodes.remove(r)
            if path not in dirty_nodes:
                dirty_nodes += [path]
        return True, dirty_nodes

    @staticmethod
    def remove_node_from_comp_layer(path, comp_node, comp_layer, ns=None,
                                    rm_from_child_order=True,
                                    rm_layer_data=True):
        is_comp_node = comp_node.__name__ == CompNode.__name__
        if not is_comp_node:
            raise TypeError("Wong node type provided, only CompNodes are "
                            "accepted.")
        if ns is None:
            ns = nxt_path.str_path_to_node_namespace(path)
        name = getattr(comp_node, INTERNAL_ATTRS.NAME)
        parent_path = getattr(comp_node, INTERNAL_ATTRS.PARENT_PATH)
        comp_layer._node_table.remove([ns, comp_node])
        comp_layer._nodes_path_as_key.pop(path)
        comp_layer._nodes_node_as_key.pop(comp_node)
        comp_layer.clear_node_child_cache(path)
        comp_layer.clear_node_child_cache(parent_path)
        if rm_from_child_order:
            comp_layer.clear_node_child_cache(parent_path)
            parent_node = comp_layer.lookup(parent_path)
            try:
                child_order = getattr(parent_node, INTERNAL_ATTRS.CHILD_ORDER)
            except AttributeError:
                child_order = []
            if parent_node is not None and name in child_order:
                child_order.remove(name)
        if rm_layer_data:
            if path in comp_layer.collapse.keys():
                comp_layer.collapse.pop(path)

    def ripple_delete(self, path, comp_node, target_layer, comp_layer,
                      dirties=()):
        dirty_nodes = []
        deleted = []
        deleted_paths = []
        name = getattr(comp_node, INTERNAL_ATTRS.NAME)
        if not dirties:
            dirties = comp_layer.get_node_dirties(path)
        kill_inst_path = []
        for dirty_path in dirties:
            dirty_node = comp_layer.lookup(dirty_path)
            # It is possible for nodes to be dirtied by more than one
            # node and therefore be deleted already
            if dirty_node is None:
                continue
            dirty_node_inst_path = getattr(dirty_node,
                                           INTERNAL_ATTRS.INSTANCE_PATH, None)
            kill = True
            if dirty_node_inst_path:
                inst_source = comp_layer.lookup(dirty_node_inst_path)
                while inst_source:
                    if inst_source is comp_node:
                        break
                    kill = getattr(inst_source, INTERNAL_ATTRS.PROXY)
                    if not kill:
                        break
                    inst_path = getattr(inst_source,
                                        INTERNAL_ATTRS.INSTANCE_PATH, None)
                    if inst_path == path:
                        inst_source = None
                    else:
                        inst_source = comp_layer.lookup(inst_path)
            if getattr(dirty_node, INTERNAL_ATTRS.PROXY) and kill:
                self.remove_node_from_comp_layer(dirty_path, dirty_node,
                                                 comp_layer)
                deleted += [(dirty_node_inst_path, dirty_path)]
                deleted_paths += [dirty_path]
                target_layer_parent = getattr(dirty_node,
                                              INTERNAL_ATTRS.PARENT_PATH)
                tgt_parent = target_layer.lookup(target_layer_parent)
                tgt_parent_children = target_layer.children(target_layer_parent)
                rm_name = getattr(dirty_node, INTERNAL_ATTRS.NAME)
                if tgt_parent and rm_name not in tgt_parent_children:
                    tgt_parent_co = getattr(tgt_parent,
                                            INTERNAL_ATTRS.CHILD_ORDER)
                    if rm_name in tgt_parent_co:
                        tgt_parent_co.remove(rm_name)
            elif kill:
                kill_inst_path += [dirty_path]
            bases_list = [b for b in dirty_node.__bases__ if
                          b is not comp_node]
            self._replace_base_classes(dirty_node, tuple(bases_list))
        inst_src, is_inst = get_opinion(comp_node,
                                        INTERNAL_ATTRS.INSTANCE_PATH)
        is_proxy = getattr(comp_node, INTERNAL_ATTRS.PROXY)
        pop_from_co = True
        if is_inst:
            inst_src_pp = nxt_path.get_parent_path(inst_src)
            rt = comp_layer.RETURNS.NameDict
            src_children = comp_layer.children(inst_src_pp,
                                               return_type=rt).keys()
            tgt_children = target_layer.children(nxt_path.get_parent_path(path),
                                                 return_type=rt).keys()
            if name not in src_children or (not is_proxy and
                                            name not in tgt_children):
                pop_from_co = False
        self.remove_node_from_comp_layer(path, comp_node, comp_layer,
                                         rm_from_child_order=pop_from_co)
        deleted += [(inst_src, path)]
        deleted_paths += [path]
        if is_inst:
            # Get inst root
            inst_root = nxt_path.get_root_path(inst_src)
            # Get inst root descendants
            root_descendants = comp_layer.descendants(inst_root,
                                                      include_implied=True)
            if root_descendants and path not in root_descendants:
                rt = comp_layer.RETURNS.Path
                descendants = comp_layer.descendants(path, rt)
                des_rm = []
                for p in descendants:
                    d = comp_layer.lookup(p)
                    if getattr(d, INTERNAL_ATTRS.PROXY):
                        d_dirt = comp_layer.get_node_dirties(p)
                        des_rm += [p] + d_dirt
                dirty_nodes += des_rm
                for p in des_rm:
                    d = comp_layer.lookup(p)
                    if d is None:
                        continue
                    self.remove_node_from_comp_layer(p, d, comp_layer)
                    d_inst_src = getattr(d, INTERNAL_ATTRS.INSTANCE_PATH, None)
                    deleted += [(d_inst_src, p)]
                    deleted_paths += [p]
            elif root_descendants and path in root_descendants:
                self.create_instance_node(inst_src, path, comp_layer)
        for inst_tgt_path in kill_inst_path:
            inst_tgt = comp_layer.lookup(inst_tgt_path)
            if inst_tgt is None:
                continue
            inst_attr = INTERNAL_ATTRS.INSTANCE_PATH
            inst_path = getattr(inst_tgt, inst_attr, None)
            opinions = get_historical_opinions(inst_tgt, inst_attr,
                                               comp_layer, include_local=True)
            if opinions:
                historical_opinion = opinions[0].get(META_ATTRS.VALUE)
            else:
                historical_opinion = None
            if inst_path in deleted_paths:
                setattr(inst_tgt, INTERNAL_ATTRS.INSTANCE_PATH,
                        historical_opinion)

        return dirty_nodes, deleted

    def parent_nodes(self, nodes, parent_path, layer):
        """Make the given parent path the parent of all the given nodes.
        :param nodes: Nodes that will become children of the parent.
        :type nodes: list | [tree.CompTreeNode]
        :param parent_path: Node that will be the parent.
        :type parent_path: comptree.CompTreeNode
        :param layer: Layer object
        :type layer: SpecLayer
        :return: Dictionary of the changed children paths in the format
        {<old path> : <new path>}
        :rtype: dict
        """
        result_paths = {}
        old_paths = []
        _path_data = layer._nodes_path_as_key
        _node_data = layer._nodes_node_as_key
        _collapse_data = layer.collapse
        _top_collapse_data = self.top_layer.collapse
        if not nodes:
            logger.error('No nodes provided!')
            return result_paths
        if not isinstance(layer, SpecLayer):
            logger.error('Wrong layer type sent! Layer must be SpecLayer but '
                         '{} was received.'.format(type(layer)))
            return result_paths
        if not isinstance(parent_path, (str, unicode)):
            logger.error("Invalid parent path {}".format(parent_path))
            return result_paths
        for node in nodes:
            old_path = layer.get_node_path(node)
            node_parent_path = getattr(node, INTERNAL_ATTRS.PARENT_PATH)
            name = getattr(node, INTERNAL_ATTRS.NAME)
            if node_parent_path != nxt_path.WORLD:
                old_parent_node = layer.lookup(node_parent_path)
                if old_parent_node is not None:
                    child_order = getattr(old_parent_node,
                                          INTERNAL_ATTRS.CHILD_ORDER)
                    if name in child_order:
                        child_order.remove(name)
                else:
                    ancestors = layer.ancestors(old_path)
                    if ancestors:
                        ancestor = ancestors[0]
                        ancestor_path = layer.get_node_path(ancestors[0])
                        ancestor_path += nxt_path.NODE_SEP
                        split_path = old_path.split(ancestor_path, 1)[1]
                        split_path = nxt_path.NODE_SEP + split_path
                        dummy_root = nxt_path.get_root_path(split_path)
                        child_name = nxt_path.node_name_from_node_path(dummy_root)
                        co = getattr(ancestor, INTERNAL_ATTRS.CHILD_ORDER)
                        if child_name in co:
                            co.remove(child_name)
            new_parent_node = layer.lookup(parent_path)
            new_name = self.get_unique_node_name(name=name,
                                                 layer=layer,
                                                 parent_path=parent_path)
            setattr(node, INTERNAL_ATTRS.NAME, new_name)
            if new_parent_node is not None:
                child_order = getattr(new_parent_node,
                                      INTERNAL_ATTRS.CHILD_ORDER)
                if new_name not in child_order:
                    # The new name will be in the list if this is called from
                    # the parent undo function
                    child_order += [new_name]
            # Update our target node
            new_path = nxt_path.join_node_paths(parent_path, new_name)
            setattr(node, INTERNAL_ATTRS.PARENT_PATH, parent_path)
            _path_data[new_path] = _path_data.pop(old_path)
            _node_data[node] = new_path
            layer.clear_node_child_cache(new_path)
            layer.clear_node_child_cache(old_path)
            layer.clear_node_child_cache(parent_path)
            # Update descendants nodes
            old_paths += [old_path]
            for path, n in _path_data.items():
                if path == new_path:
                    continue
                # Update all other paths that start with the old path
                if nxt_path.is_ancestor(path, old_path):
                    updated_path = nxt_path.replace_ancestor(path, old_path,
                                                             new_path)
                    _path_data[updated_path] = _path_data.pop(path)
                    _node_data[n] = updated_path
                    n_parent_path = getattr(n, INTERNAL_ATTRS.PARENT_PATH)
                    new_parent_path = nxt_path.replace_ancestor(n_parent_path,
                                                                old_path,
                                                                new_path)
                    layer.clear_node_child_cache(path)
                    layer.clear_node_child_cache(updated_path)
                    layer.clear_node_child_cache(new_parent_path)
                    setattr(n, INTERNAL_ATTRS.PARENT_PATH, new_parent_path)

            # Update layer data
            if old_path in _collapse_data.keys():
                _collapse_data[new_path] = _collapse_data.pop(old_path)
            not_top = layer is not self.top_layer
            if not_top and old_path in _top_collapse_data.keys():
                old_collapsed = self.top_layer.collapse.pop(old_path)
                self.top_layer.collapse[new_path] = old_collapsed

        # Refresh the layer to regenerate and sort the node table
        layer.refresh()
        idx = 0
        # Generate the results dict
        for old_path in old_paths:
            node = nodes[idx]
            new_path_in_layer = layer.get_node_path(node)
            node_parent_path = getattr(node, INTERNAL_ATTRS.PARENT_PATH)
            node_name = getattr(node, INTERNAL_ATTRS.NAME)
            expected_new_path = nxt_path.join_node_paths(node_parent_path,
                                                         node_name)
            # Test that the paths really did change
            bad_old_path = old_path == expected_new_path
            bad_path_in_layer = new_path_in_layer != expected_new_path
            if bad_old_path or bad_path_in_layer:
                raise Exception("Parenting failed! Resulting node paths are "
                                "not what we expected.")
            result_paths[old_path] = expected_new_path
            idx += 1
        return result_paths

    def add_node_attr(self, node, attr, attr_data, layer, tracked=True):
        # TODO default values for args? If so, fix test_tokens.py
        node_path = layer.get_node_path(node)
        attr = self.get_unique_attr_name(node_path, layer, attr)
        # Parse for attrs
        for sub_attr, value in attr_data.items():
            if sub_attr == 'source':
                continue
            if sub_attr == 'value':
                # We assume you've validated before now that the attr name
                # your sending is allowable.
                setattr(node, attr, value)
                continue
            meta_attr = META_ATTRS._prefix + sub_attr + META_ATTRS._suffix
            if meta_attr not in META_ATTRS.ALL:
                logger.warning('Invalid meta attr supplied! '
                               '"{}"'.format(sub_attr))
                continue
            full_meta_attr = attr + meta_attr
            setattr(node, full_meta_attr, value)
        if tracked:
            source = (layer.real_path, node_path)
            setattr(node, attr + META_ATTRS.SOURCE, source)
        return attr

    def delete_node_attr(self, node, attr_name):
        node = self.get_node_spec(node)
        if not self.node_attr_exists(node, attr_name):
            return False
        for meta_attr_suffix in self.meta_attrs:
            meta_attr = attr_name + meta_attr_suffix
            if hasattr(node, meta_attr):
                delattr(node, meta_attr)
        delattr(node, attr_name)
        return True

    def rename_node_attr(self, node, attr_name, new_attr_name, layer):
        node = self.get_node_spec(node)
        node_path = layer.get_node_path(node)
        # get valid new name
        new_name = self.get_unique_attr_name(node_path, layer,
                                             attr_name=new_attr_name)
        # rename
        if attr_name in get_node_local_attr_names(node_path, [layer]):
            setattr(node, new_name, getattr(node, attr_name))
            delattr(node, attr_name)
            for meta_attr_suffix in self.meta_attrs:
                meta_attr = attr_name + meta_attr_suffix
                if hasattr(node, meta_attr):
                    new_meta_attr_name = new_name + meta_attr_suffix
                    setattr(node, new_meta_attr_name, getattr(node, meta_attr))
                    delattr(node, meta_attr)

    def set_node_name(self, node, name, layer, force=False):
        """Set's the name of a node. This by definition changes the path to
        the node. Default behavior is to prevent clashing node names when
        stage is built to given `layer`. If `force` is true, will accept
        clashing names.
        TODO is it worthwhile to reverse this api? Where "forcing" is default
        and one would have to opt-into fixes via fix=True?

        :param node: Node to change name of.
        :type node: NodeSpec
        :param name: Name to change to.
        :type name: str
        :param layer: Context to prevent clashing node name, defaults to None.
        :type layer: Layer, optional
        :param force: If True, allows clashing node names, defaults to False.
        :type force: bool, optional
        """
        # validate the new name
        # RIP retaliative_old_node_path 2019-2020
        node = self.get_node_spec(node)
        parent_path = getattr(node, INTERNAL_ATTRS.PARENT_PATH)
        source_layer = self.get_node_source_layer(node)
        if source_layer is not layer:
            logger.error("The node provided does not belong to the layer "
                         "provided")
            raise TypeError("Layer provided is not the same object as the "
                            "node's source layer")
        old_node_path = layer.get_node_path(node)
        rt = layer.RETURNS.Path
        children_paths = layer.children(old_node_path, return_type=rt,
                                        include_implied=True)
        children = []
        for child_path in children_paths:
            child_node = layer.lookup(child_path)
            if child_node is not None:
                children += [child_node]

        if not force:
            name = self.get_unique_node_name(name=name, layer=layer,
                                             parent_path=parent_path)
        old_name = getattr(node, INTERNAL_ATTRS.NAME)
        setattr(node, INTERNAL_ATTRS.NAME, name)
        new_node_path = nxt_path.join_node_paths(parent_path, name)
        parent_node = layer.lookup(parent_path)
        if parent_node:
            child_order = getattr(parent_node, INTERNAL_ATTRS.CHILD_ORDER)
        else:
            child_order = []
        if parent_node and old_name in child_order:
            child_order_copy = child_order[:]
            del child_order[:]
            for item in child_order_copy:
                if item != old_name:
                    child_order += [item]
                else:
                    child_order += [name]

        layer_data_dicts = [META_DATA_KEY.POSITIONS, META_DATA_KEY.COLLAPSE,
                            '_nodes_path_as_key']
        for data_dict in layer_data_dicts:
            active_dict = getattr(layer, data_dict)
            if old_node_path in active_dict.keys():
                active_dict[new_node_path] = active_dict.pop(old_node_path)
        if layer is not self.top_layer:
            active_dict = self.top_layer.positions
            if old_node_path in active_dict.keys():
                active_dict[new_node_path] = active_dict.pop(old_node_path)
        if node not in layer._nodes_node_as_key.keys():
            raise Exception("Node rename failed!")
        layer._nodes_node_as_key[node] = new_node_path
        layer.clear_node_child_cache(new_node_path)
        layer.clear_node_child_cache(old_node_path)
        if children:
            self.parent_nodes(children, new_node_path, layer)
        layer.refresh()
        return new_node_path

    def transfer_node_data(self, target_node, target_layer, source_node,
                           source_layer, include_inherit=False):
        """Transfers data from one node to another. If the source arg is a
        node object a source layer must also be provided.
        :param target_node: NodeSpec
        :param source_node: CompNode, NodeSpec or node data dict
        :param source_layer: Layer object
        :param target_layer: SpecLayer object
        :param include_inherit: Bool passed to get_node_data
        :return: None
        """
        if not isinstance(source_node, dict):
            data = self.get_node_data(source_node, source_layer,
                                      include_inherit)
        else:
            data = source_node
        self.set_node_data(target_node, data, target_layer)

    def set_node_data(self, node, node_data, layer):
        node_path = layer.get_node_path(node)
        # Source tracked attrs
        for internal_attr in INTERNAL_ATTRS.TRACKED:
            attr_key = INTERNAL_ATTRS.as_save_key(internal_attr)
            if internal_attr is INTERNAL_ATTRS.COMPUTE:
                attr_key = 'code'  # TODO: Refactor see #656
            val = node_data.get(attr_key)
            allow = internal_attr in INTERNAL_ATTRS.ALLOW_NO_OPINION
            if has_opinion(val) or allow:
                setattr(node, internal_attr, val)
                setattr(node, internal_attr + META_ATTRS.SOURCE,
                        (layer.real_path, node_path))
        # Un-tracked attrs
        for internal_attr in INTERNAL_ATTRS.UNTRACKED:
            attr_key = INTERNAL_ATTRS.as_save_key(internal_attr)
            val = node_data.get(attr_key)
            allow = internal_attr in INTERNAL_ATTRS.ALLOW_NO_OPINION
            if has_opinion(val) or allow:
                setattr(node, internal_attr, val)
        # User attrs
        attrs = node_data.get('attributes', {})
        for attr, attr_data in attrs.items():
            self.node_setattr_data(node, attr, layer, True, **attr_data)

    def node_setattr_data(self, node, attr, layer, create, comp_layer=None,
                          **values):
        node_path = layer.get_node_path(node)
        local_attrs = tuple(get_node_local_attr_names(node_path, [layer]))
        value_set = False
        dirties = []
        if attr == INTERNAL_ATTRS.NAME:
            new_name = values.get(META_ATTRS.VALUE)
            if not new_name:
                logger.warning('Cannot set node name to none')
                return
            if 'force' in values:
                force = values['force']
            else:
                force = False
            return self.set_node_name(node, new_name, layer, force=force)
        tracked = (attr not in INTERNAL_ATTRS.PROTECTED or
                   attr in INTERNAL_ATTRS.TRACKED)
        for sub_attr, value in values.items():
            if isinstance(value, unicode):
                if value == u'':
                    value = None
                elif value.startswith('"'):
                    pass
                else:
                    value = str(value)
            if sub_attr != META_ATTRS.VALUE:
                meta_attr = META_ATTRS._prefix + sub_attr + META_ATTRS._suffix
                # Fixme: Do we need to test for this case twice?
                if meta_attr not in META_ATTRS.ALL:
                    logger.warning('Invalid meta attr supplied! '
                                   '"{}"'.format(sub_attr))
                    continue
                full_attr_name = attr + meta_attr
            else:
                full_attr_name = attr
                value_set = True
            # Only set attr if its not a python builtin
            if attr in local_attrs + INTERNAL_ATTRS.ALL:
                # Child order
                if attr == INTERNAL_ATTRS.CHILD_ORDER:
                    self.set_node_child_order(node, value, layer, comp_layer)
                    continue
                if attr == INTERNAL_ATTRS.INSTANCE_PATH:
                    inst_path = values.get(META_ATTRS.VALUE)
                    dirties += self.set_node_instance_path(node, inst_path,
                                                           layer, comp_layer)
                    continue
                if attr == INTERNAL_ATTRS.COMPUTE:
                    code_lines = values.get(META_ATTRS.VALUE)
                    self.set_node_code_lines(node, code_lines, comp_layer)
                    continue
                # Any other attrs
                setattr(node, full_attr_name, value)
                if sub_attr == META_ATTRS.VALUE and tracked:
                    type_name = determine_nxt_type(value)
                    setattr(node, attr + META_ATTRS.TYPE, type_name)
                    source = (layer.real_path, node_path)
                    setattr(node, attr + META_ATTRS.SOURCE, source)
            elif create:
                self.add_node_attr(node, attr, dict(**values), layer=layer)
                local_attrs += (attr,)
        if not value_set:
            return
        if attr == INTERNAL_ATTRS.PARENT_PATH:
            # TODO: Targeted re-comp of parent here
            pass
        elif attr == INTERNAL_ATTRS.INSTANCE_PATH:
            # TODO: Targeted re-comp of instance here
            return dirties
        return attr

    def set_node_instance_path(self, node, instance_path, target_layer,
                               comp_layer=None):
        """Sets the node's instance path to the given path and sets the
        source meta attr.
        :param node: Node object
        :type node: SpecNode
        :param instance_path: Node path of instance source
        :type instance_path: str
        :param target_layer: Target spec layer
        :type target_layer: SpecLayer
        :param comp_layer: Comp layer to do targeted change to
        :type comp_layer: CompLayer
        :return: None
        """
        node_path = target_layer.get_node_path(node)
        if instance_path is not None:
            instance_path = str(instance_path)
        unchanged = True
        dirty_nodes = []
        if comp_layer:
            comp_node = comp_layer.lookup(node_path)
            unchanged = has_stronger_opinion(comp_node,
                                             INTERNAL_ATTRS.INSTANCE_PATH,
                                             target_layer.real_path)
            if not unchanged:
                old_inst_path = getattr(comp_node,
                                        INTERNAL_ATTRS.INSTANCE_PATH, None)
                dirty_nodes = comp_layer.get_node_dirties(old_inst_path)
                if old_inst_path:
                    dirty_nodes += self.targeted_uncomp(comp_node, comp_layer,
                                                        target_layer,
                                                        arcs=[CompArc.INSTANCE])
                expanded = None
                if has_opinion(instance_path):
                    expanded = nxt_path.expand_relative_node_path(instance_path,
                                                                  node_path)
                else:
                    ip = INTERNAL_ATTRS.INSTANCE_PATH
                    prev_inst_paths = get_historical_opinions(comp_node, ip,
                                                              comp_layer)
                    for dat in prev_inst_paths:
                        path = dat[META_ATTRS.VALUE]
                        if has_opinion(path):
                            np = node_path
                            expanded = nxt_path.expand_relative_node_path(path,
                                                                          np)
                            break
                setattr(comp_node, INTERNAL_ATTRS.INSTANCE_PATH, expanded)
                setattr(comp_node,
                        INTERNAL_ATTRS.INSTANCE_PATH + META_ATTRS.SOURCE,
                        (target_layer.real_path, node_path))
        setattr(node, INTERNAL_ATTRS.INSTANCE_PATH, instance_path)
        setattr(node, INTERNAL_ATTRS.INSTANCE_PATH + META_ATTRS.SOURCE,
                (target_layer.real_path, node_path))
        if comp_layer and not unchanged:
            proxy_map = self.targeted_comp_proxies(comp_node, node_path,
                                                   comp_layer)
            dirty_nodes += self.targeted_comp_post_proxies(proxy_map,
                                                           comp_layer)
        return list(set(dirty_nodes))

    @staticmethod
    def remove_node_instance(node):
        """Removes the instance path and meta attr from the node.
        :param node: Node object
        :type node: SpecNode
        :return: None
        """
        # Building should be handled by the model not the stage
        if hasattr(node, INTERNAL_ATTRS.INSTANCE_PATH):
            delattr(node, INTERNAL_ATTRS.INSTANCE_PATH)
            delattr(node, INTERNAL_ATTRS.INSTANCE_PATH + META_ATTRS.SOURCE)

    def safe_get_node_instance(self, comp_node, comp_layer, expanded=True):
        """Safely gets the instance from a node
        :param comp_node: CompNode object
        :param comp_layer: CompLayer object
        :param expanded: If True relative paths will be expanded
        :return: (CompNode, NodePath)
        """
        inst_path = get_node_attr(comp_node, INTERNAL_ATTRS.INSTANCE_PATH)
        if not has_opinion(inst_path):  # The node's inst path might be None
            return None, inst_path
        node_path = get_node_path(comp_node)
        if expanded:
            real_path = nxt_path.expand_relative_node_path(inst_path, node_path)
        else:
            real_path = self.get_uncomped_opinion(comp_node,
                                                  INTERNAL_ATTRS.INSTANCE_PATH)
        instance_node = comp_layer.lookup(real_path)
        return instance_node, real_path

    def node_setattr_comment(self, node, attr_name, layer, comment=None,
                             create=False):
        self.node_setattr_data(node, attr_name, layer, create,
                               comment=comment)

    def lookup_layer(self, layer_path):
        """Finds and returns a layer object from the sub layers list who's
        real path matches the layer path arg.
        :param layer_path: String of real file path to layer's save file
        :return: Layer Object
        """
        for layer in self._sub_layers:
            if layer.real_path == layer_path:
                return layer
        if layer_path:
            logger.warning('Layer not found: {}'.format(layer_path))
        return None

    def get_node_source_layer(self, node):
        """Gets the source layer object for a given node.
        :param node: NodeSpec or CompNode
        :return: Layer object or None
        """
        layer_real_path = getattr(node, INTERNAL_ATTRS.SOURCE_LAYER)
        return self.lookup_layer(layer_real_path)

    @staticmethod
    def get_uncomped_opinion(node, attr):
        if node.__name__ != SpecNode.__name__:
            bases = node.__bases__
        else:
            bases = (node,)
        for base in bases:
            if base.__name__ == SpecNode.__name__ and hasattr(base, attr):
                return getattr(base, attr)

    @staticmethod
    def get_node_attr_comment(node_object, attr):
        comment_attr = attr + META_ATTRS.COMMENT
        if hasattr(node_object, comment_attr):
            return getattr(node_object, comment_attr)
        else:
            return None

    def get_node_attr_names(self, node):
        attrs = []
        for attr in dir(node):
            if attr in attrs:
                continue
            if attr in self.protected_attrs:
                continue
            if attr.endswith(META_ATTRS._suffix):
                continue
            attrs += [attr]
        return attrs

    def get_node_instanced_attr_names(self, node, comp_layer):
        if not isinstance(comp_layer, CompLayer):
            logger.error('Wrong layer type supplied, must be comp layer!')
            return []
        attrs = []
        node_path = comp_layer.get_node_path(node)
        s, e = comp_layer._layer_range
        layers = self._sub_layers[s:e]
        local_attrs = get_node_local_attr_names(node_path, layers)
        parent_path = getattr(node, INTERNAL_ATTRS.PARENT_PATH)
        parent = comp_layer.lookup(parent_path)
        if parent:
            p_loc = get_node_local_attr_names(parent_path, layers)
            p_inherits = self.get_node_inherited_attr_names(parent, comp_layer)
            inherited = p_loc + p_inherits
            p_inst_attrs = self.get_node_instanced_attr_names(parent,
                                                              comp_layer)
            attrs += [a for a in p_inst_attrs if a not in inherited]
        else:
            inherited = []
        try:
            instance_path = getattr(node, INTERNAL_ATTRS.INSTANCE_PATH)
        except AttributeError:
            instance_path = None
        instance = comp_layer.lookup(instance_path)
        if not instance_path or not instance:
            return attrs
        invalid_list = self.protected_attrs + inherited + local_attrs
        for attr in dir(instance):
            if attr in attrs:
                continue
            if attr in invalid_list:
                continue
            if attr.endswith(META_ATTRS._suffix):
                continue
            attrs += [attr]
        return attrs

    def get_node_attr_value(self, node, attr_name, layer, resolved=True):
        """Get the value of the specified attr from the specified node,
        optionally resolved.
        :param node: node that contains attr.
        :type node: nxt_node.Node
        :param attr_name: name of the attr you would like the value from.
        :type attr_name: str
        :param resolved: whether to resolve the value of the attr and return it
        :type resolved: bool
        :param layer: Layer object
        :type layer: Layer or CompLayer
        :return: value of the requested attribute, if found, else None
        """
        layer = layer or self.top_layer
        try:
            attr_val = getattr(node, attr_name)
        except AttributeError:
            attr_val = ''

        if resolved and attr_val:
            attr_val = self.resolve(node, attr_val, layer, attr_name=attr_name)
            return str(attr_val)
        if attr_name in INTERNAL_ATTRS.PROTECTED:
            return attr_val
        # get the raw version of this attribute value
        if attr_val is None:
            attr_val = ''
        elif not attr_val:
            attr_val = str(attr_val)
        return attr_val

    @staticmethod
    def get_node_attr_source(node, attr_name):
        """Tries to find the node who truly holds the local attribute via
        recursively looking for the _source__nxt meta attribute.
        :param node: Node who has access to the attr_name
        :param attr_name: Name of attribute you want to find the source node for
        nodes (stored in the ._inherit attr). Usually this is True except in
        some edgecases like finding the source of _compute.
        :return: Node object or None if no source found (None is not expected)
        """
        source_attr = attr_name + META_ATTRS.SOURCE
        try:
            source_layer, source_path = getattr(node, source_attr)
            return source_layer, source_path
        except AttributeError:
            return '', ''

    def get_node_attr_data(self, node, attr_name, layer, quiet=False):
        for meta_attr in META_ATTRS.ALL:
            if attr_name.endswith(meta_attr):
                attr_name = attr_name.split(meta_attr)[0]
                break
        if not self.node_attr_exists(node, attr_name):
            node_path = layer.get_node_path(node)
            if not quiet:
                msg = "The node {} does not have the attr \"{}\""
                logger.error(msg.format(node_path, attr_name),
                             links=[node_path])
            return {}
        value = getattr(node, attr_name)
        meta_attrs = {META_ATTRS.VALUE: value}
        for meta_attr_suffix in self.meta_attrs:
            meta_attr = attr_name + meta_attr_suffix
            pretty_name = meta_attr_suffix.split(META_ATTRS._prefix)[1]
            if hasattr(node, meta_attr):
                meta_attrs[pretty_name] = getattr(node, meta_attr)

        attr_data = OrderedDict(sorted(meta_attrs.items(),
                                       key=lambda x: x[0].lower()))
        # attr_data[attr_name] = sorted_meta_attrs
        return attr_data

    def get_node_data(self, node, layer, include_inherit=False):
        node_data = {}
        node_path = layer.get_node_path(node)
        for internal_attr in INTERNAL_ATTRS.PROTECTED:
            if internal_attr in INTERNAL_ATTRS.BUILTINS:
                continue
            try:
                val = getattr(node, internal_attr)
            except AttributeError:
                val = None
            if (has_opinion(val) or internal_attr in
                    INTERNAL_ATTRS.ALLOW_NO_OPINION):
                key = INTERNAL_ATTRS.as_save_key(internal_attr)
                if internal_attr is INTERNAL_ATTRS.COMPUTE:
                    key = 'code'  # TODO: Refactor see #656
                node_data[key] = val
        if include_inherit:
            all_attrs = self.get_node_attr_names(node)
        else:
            if isinstance(layer, CompLayer):
                s, e = layer._layer_range
                layers = self._sub_layers[s:e]
            else:
                layers = [layer]
            all_attrs = get_node_local_attr_names(node_path, layers)
        attr_data = {}
        for attr in set(all_attrs):
            data = {}
            val = self.get_node_attr_value(node, attr_name=attr, layer=layer,
                                           resolved=False)
            comment = self.get_node_attr_comment(node, attr)
            data[META_ATTRS.VALUE] = val
            data[META_ATTRS.as_save_key(META_ATTRS.COMMENT)] = comment
            # if data:
            attr_data[attr] = data
        node_data['attributes'] = attr_data
        return node_data

    @staticmethod
    def get_tokens_from(string, token_type=TOKENTYPE.ALL):
        """Returns a list of token strings the given `string` contains.
        TODO Token syntax should be changed to make each token type
        explicit rather than assuming attr refs for random strings.
        Tokens can be attribute references that look like
        `${<NodeName>.<ChildNodeName>.<AttributeName>}` at the most verbose,
        `${<AttributeName>}` at a minimum.
        or tokens can be file tokens that look like
        `${file::<filepath, relative or absolute>}`
        i.e. `${file::../otherfile.txt}`
        :return: List of tokens as found.
        :rtype: list
        """
        if not isinstance(string, str):
            if isinstance(string, unicode):
                string = str(string)
            else:
                return []
        all_tokens = tokens.get_atomic_tokens(string)
        if token_type == TOKENTYPE.ALL:
            return all_tokens
        filtered_tokens = []
        for token in all_tokens:
            if Stage.determine_token_type(token) == token_type:
                filtered_tokens.append(token)
        return filtered_tokens

    @staticmethod
    def next_token_partition(text):
        """partition given `text` on a token that appears
        resolvable(contains no sub tokens). Returns in a tuple:
        (before_token, token_content, after_token), losing the token prefix
        and suffix in the partition.

        :param text: text to find a token from, and partition
        :type text: str
        :return: before_token, token_content, after_token
        :rtype: tuple(str, str, str)
        """
        before, sep, after_bef = text.rpartition(nxt_path.TOKEN_PREFIX)
        if not sep:
            return (None, None, None)
        token, sep, after = after_bef.partition(nxt_path.TOKEN_SUFFIX)
        if not sep:
            # msg = 'bad resolve formatting, cannot find closer for {}'
            # msg = msg.format(before + nxt_path.TOKEN_PREFIX)
            # logger.error(msg)
            return (None, None, None)
        return before, token, after

    @staticmethod
    def determine_token_type(token_str):
        if not token_str:
            return None
        for plugin_token in plugin_tokens:
            if plugin_token.detect(token_str):
                return plugin_token
        if token_str.startswith(TOKENTYPE.FILE.prefix):
            return TOKENTYPE.FILE
        if token_str.startswith(TOKENTYPE.FILEPATH.prefix):
            return TOKENTYPE.FILEPATH
        if token_str.startswith(TOKENTYPE.CONTENTS.prefix):
            return TOKENTYPE.CONTENTS
        elif token_str == TOKENTYPE.PATH.prefix:
            return TOKENTYPE.PATH
        elif token_str == TOKENTYPE.COLOR.prefix:
            return TOKENTYPE.COLOR
        return TOKENTYPE.ATTR

    def resolve(self, node, text, layer, **kwargs):
        text = str(text)
        resolved = text
        for token in tokens.get_standalone_tokens(text):
            token_content = tokens.get_token_content(token)
            token_type = Stage.determine_token_type(token_content)
            rep = 'BADRESOLVE'
            if token_type:
                cleaned = token_content[len(token_type.prefix):]
            else:
                cleaned = token_content
            if isinstance(token_type, Token) and callable(token_type.resolve):
                rep = token_type.resolve(self, node, cleaned, layer, **kwargs)
            elif token_type == TOKENTYPE.FILE:
                rep = self.resolve_file_token(node, cleaned, layer)
            elif token_type == TOKENTYPE.FILEPATH:
                rep = self.resolve_file_path_token(node, cleaned, layer)
            elif token_type == TOKENTYPE.CONTENTS:
                rep = self.resolve_contents_token(node, cleaned, layer)
            elif token_type == TOKENTYPE.ATTR:
                rep = self.resolve_attr_ref_token(node, token_content, layer)
            elif token_type == TOKENTYPE.PATH:
                rep = layer.get_node_path(node)
            elif token_type == TOKENTYPE.COLOR:
                source_layer = self.get_node_source_layer(node)
                rep = source_layer.color
            else:
                logger.warning('Unknown token:"{}" '.format(token_content))
            if rep is None:
                logger.warning('Failed to resolve: {}'.format(token_content))
                rep = ''
            resolved = resolved.replace(token, rep)
        return resolved

    def resolve_attr_ref_token(self, node, text, layer):
        """Resolve an attribute ref string into the value contained at that
        attribute.
        Attr refs look like: `${/<NodeName>/<ChildNodeName>.<AttributeName>}`
        at the most verbose, `${<AttributeName>}` at a minimum.

        :param node: node resolve is started from
        :type node: Node
        :param text: text to resolve
        :type text: str
        :param layer: Layer object for context of this resolve
        :type layer: Layer
        :return: attribute value given text refers to
        :rtype: str
        """
        attr_ref = self.resolve(node, text, layer)
        ref_path, ref_attr_name = nxt_path.path_attr_partition(attr_ref)
        if ref_path and ref_attr_name:
            attr_name = ref_attr_name
            source_path = ref_path
        else:
            attr_name = attr_ref
            source_path = layer.get_node_path(node)
        # If this attr ref is to another node, go there and get the value
        if source_path:
            node_path = layer.get_node_path(node)
            source_path = nxt_path.expand_relative_node_path(source_path,
                                                             node_path)
            resolve_source_node = layer.lookup(source_path)
            return self.get_node_attr_value(resolve_source_node,
                                            attr_name=attr_name, layer=layer,
                                            resolved=True)
        # NOTE: attr ref hierarchy is defined here.
        try:
            local_val = getattr(node, attr_name)
        except AttributeError:
            local_val = self.get_node_attr_value(node, attr_name, layer,
                                                 resolved=True)
        if local_val:
            return local_val
        warning_template = 'Failed to resolve attr "{}" on "{}"'
        warning = warning_template.format(attr_ref, layer.get_node_path(node))
        logger.warning(warning)
        return '"${' + attr_ref + '}"'

    def resolve_file_path_token(self, node, text, start_layer):
        """Uses pathing module to attempt to expand given `token_str` into
        a file path. Path is treated as a relative path to start layer's real
        file path.
        :param node: node resolve is started from
        :type node: Node
        :param text: text to resolve
        :type text: str
        :param start_layer: Layer object who's file path is used to resolve
        the given token
        :type start_layer: Layer
        :return: file path
        :rtype: str
        """
        token_str = self.resolve(node, text, start_layer)
        cwd = start_layer.get_cwd()
        if not cwd:
            cwd = os.getcwd()
            msg = ("No layer path found for {layer}, "
                   "using cwd:{new} for file token resolution.")
            logger.debug(msg.format(layer=start_layer._name, new=cwd))
        return nxt_path.full_file_expand(token_str, start=cwd)

    def resolve_file_token(self, node, text, start_layer):
        """Generates a file path using resolution of path token logic, but
        only returns a path if the file exists.

        :param node: node resolve is started from
        :type node: Node
        :param text: text to resolve
        :type text: str
        :param start_layer: Layer object who's file path is used to resolve
        the given token
        :type start_layer: Layer
        :return: file path or empty string
        :rtype: str
        """
        resolved = self.resolve(node, text, start_layer)
        full_path = self.resolve_file_path_token(node, resolved, start_layer)
        if not os.path.exists(full_path):
            return ''
        return full_path

    def resolve_contents_token(self, node, text, layer):
        """Resolves to the text file contents of file path as a string.

        :param node: node resolve is started from
        :type node: Node
        :param text: text to resolve
        :type text: str
        :param layer: Layer object for context of this resolve
        :type layer: Layer
        :return: string contents of file, if found, otherwise empty string
        :rtype: str
        """
        file_path = self.resolve(node, text, layer)
        try:
            with open(file_path) as fp:
                contents = fp.read()
        except IOError:
            logger.error('Failed to get contents of {}'.format(file_path))
            return ''
        # pipe contents back through resolve in case contents have tokens.
        return self.resolve(node, contents, layer)

    def infer_lower_comp(self, comp_node, comp_layer, active_layers=None,
                         depth=1, inferred_comp_layer=None):
        """Infer a new comp node based on the provided args. This method
        attempts to shift the composition for a node to a different comp
        depth. The default depth is 1 which means it will infer a new comp
        node as though the comp's display layer was 1 layer below the
        provided `comp_layer`'s display layer. None is returned if it is not
        possible to infer a new comp node based on the args provided. If the
        depth is 0 the comp node is returned unchanged. If the depth is < 0
        None is returned as this method infers lower comps (high numbers are
        lower layers). If no inferred_comp_layer is provided one is created.
        Its only use is to hold pointers to inferred nodes as they are
        created, within this method it is treated like a real comp layer,
        however it is not returned or intended to be returned.
        :param comp_node: Comp node to be used as the source for the inference.
        :type comp_node: CompNode
        :param comp_layer: Comp layer used to inform us what spec layers to
        consider.
        :type comp_layer: CompLayer
        :param active_layers: If no active layers are provided they will be
        calculated from the comp layer's range using the depth arg. If the
        caller of this method already knows the active layers it should pass
        them here to improve the speed of the inferred comp.
        :type active_layers: list or None
        :param depth: number of layers to rollback the comp
        :type depth: int
        :param inferred_comp_layer: Temporary comp layer used to hold inferred
        nodes, if not is provided one will be created and passed to further
        recursions of this method.
        :type inferred_comp_layer: CompLayer
        :return: CompNode or None
        """
        if depth == 0:
            return comp_node
        if not inferred_comp_layer:
            inferred_comp_layer = CompLayer()
        path = get_node_path(comp_node)
        inferred_comp = inferred_comp_layer.lookup(path)
        if inferred_comp:
            return inferred_comp
        display_idx, end_idx = comp_layer._layer_range
        if not active_layers:
            requested_layers = self._sub_layers[display_idx + depth:end_idx+1]
            active_layers = get_active_layers(requested_layers)
        if not active_layers or depth < 0:
            return None
        is_proxy = getattr(comp_node, INTERNAL_ATTRS.PROXY)
        is_divergent = self._check_if_inst_diverges(path, comp_layer,
                                                    active_layers)
        if is_divergent:
            logger.warning('Divergent instance detected, historical values '
                           'may yield un-expected results!')
        specs = self.get_specs_at_path(path, active_layers)
        dummy_spec = SpecNode.new({INTERNAL_ATTRS.NAME:
                                       getattr(comp_node, INTERNAL_ATTRS.NAME),
                                   INTERNAL_ATTRS.PARENT_PATH:
                                       getattr(comp_node,
                                               INTERNAL_ATTRS.PARENT_PATH),
                                   INTERNAL_ATTRS.INSTANCE_PATH:
                                       getattr(comp_node,
                                               INTERNAL_ATTRS.INSTANCE_PATH),
                                   INTERNAL_ATTRS.PROXY: is_proxy,
                                   INTERNAL_ATTRS.SOURCE_LAYER: None})
        inferred_comp = CompNode.new(spec_node=dummy_spec)
        self.add_node_to_comp_layer(path, inferred_comp, inferred_comp_layer,
                                    add_to_child_order=False)
        if specs:
            self._replace_base_classes(inferred_comp, tuple(specs))
        ancestor_paths = nxt_path.all_ancestor_paths(path) + [nxt_path.WORLD]
        ancestors = []
        parent = None
        proxy_map = {}
        inferred_comp_proxy_map = {}
        for ancestor_path in reversed(ancestor_paths):
            specs = self.get_specs_at_path(ancestor_path, active_layers)
            if not specs:
                ancestors += [None]
                continue
            spec = specs[0]
            ancestor = inferred_comp_layer.lookup(ancestor_path)
            if ancestor:
                parent = ancestor
                continue
            ancestor = CompNode.new(spec_node=spec)
            ancestors += [ancestor]
            ancestor_proxy_map = {CompArc.PARENT: parent}
            parent = ancestor
            self.add_node_to_comp_layer(ancestor_path, ancestor,
                                        inferred_comp_layer,
                                        add_to_child_order=False)
            self._replace_base_classes(ancestor, tuple(specs))
            inst_path = getattr(ancestor, INTERNAL_ATTRS.INSTANCE_PATH)
            for spec in reversed(specs):
                val, op = get_opinion(spec, INTERNAL_ATTRS.INSTANCE_PATH)
                if op and val != inst_path:
                    inst_path = val
            setattr(ancestor, INTERNAL_ATTRS.INSTANCE_PATH, inst_path)
            ancestor_inst_comp_src = comp_layer.lookup(inst_path)
            if ancestor_inst_comp_src:
                ancestor_inst = self.infer_lower_comp(ancestor_inst_comp_src,
                                                      comp_layer,
                                                      active_layers,
                                                      depth,
                                                      inferred_comp_layer)
                ancestor_proxy_map[CompArc.INSTANCE] = ancestor_inst
            proxy_map[ancestor] = ancestor_proxy_map
            self.targeted_comp_post_proxies(proxy_map)
            proxy_map = {}
        inst_path = None
        if parent:
            name = getattr(inferred_comp, INTERNAL_ATTRS.NAME)
            parent_inst = getattr(parent, INTERNAL_ATTRS.INSTANCE_PATH)
            children = comp_layer.children(parent_inst,
                                           return_type=comp_layer.RETURNS.Path)
            for p in children:
                if nxt_path.node_name_from_node_path(p) == name:
                    inst_path = p
                    break
        inst = None
        if not inst_path:
            inst, inst_path = self.safe_get_node_instance(inferred_comp,
                                                          inferred_comp_layer,
                                                          expanded=True)
        infer_inst = False
        if inst_path and not inst:
            inst = comp_layer.lookup(inst_path)
            infer_inst = True
        inst_path = getattr(inferred_comp, INTERNAL_ATTRS.INSTANCE_PATH)
        base_paths = [get_node_path(b) for b in inferred_comp.__bases__]
        if inst and infer_inst and inst_path not in base_paths:
            inferred_inst = self.infer_lower_comp(inst, comp_layer,
                                                  active_layers, depth,
                                                  inferred_comp_layer)
            inferred_comp_proxy_map[CompArc.INSTANCE] = inferred_inst
        elif inst and inst_path not in base_paths:
            inferred_comp_proxy_map[CompArc.INSTANCE] = inst
        elif not inst and getattr(inferred_comp, INTERNAL_ATTRS.PROXY):
            return None
        parent_path = nxt_path.get_parent_path(path)
        if parent_path and parent_path not in base_paths:
            inferred_comp_proxy_map[CompArc.PARENT] = parent
        proxy_map[inferred_comp] = inferred_comp_proxy_map
        self.targeted_comp_post_proxies(proxy_map)
        return inferred_comp

    @staticmethod
    def _check_if_inst_diverges(path, comp_layer, active_layers):
        """Returns True or False depending if the historical instance the
        given path changes. Meaning if a lower layer has a different instance
        path this method would return True.
        :param path: String of node path
        :param comp_layer: CompLayer
        :param active_layers: List of active spec layers
        :return: bool
        """
        # TODO: If in the future we find that we must support this kind of
        #  behavior in file fallbacks or anything else we must work out a way
        #  to generate a divergent instance proxy node.
        ancestor_paths = nxt_path.all_ancestor_paths(path) + [nxt_path.WORLD]
        current_instances = {}
        for ancestor_path in reversed(ancestor_paths):
            ancestor = comp_layer.lookup(ancestor_path)
            ancestor_inst_path = getattr(ancestor, INTERNAL_ATTRS.INSTANCE_PATH,
                                         None)
            if ancestor_inst_path:
                current_instances[ancestor_path] = ancestor_inst_path

        for ancestor_path in reversed(ancestor_paths):
            for layer in active_layers:
                ancestor = layer.lookup(ancestor_path)
                if ancestor:
                    ancestor_inst_path = getattr(ancestor,
                                                 INTERNAL_ATTRS.INSTANCE_PATH,
                                                 None)
                    comp_inst_path = current_instances.get(ancestor_path)
                    comp_has_op = has_opinion(comp_inst_path)
                    ancestor_has_op = has_opinion(ancestor_inst_path)
                    has_op = comp_has_op and ancestor_has_op
                    if comp_inst_path != ancestor_inst_path and has_op:
                        src_layer = getattr(ancestor,
                                            INTERNAL_ATTRS.SOURCE_LAYER)
                        logger.debug('"{}" instance diverges \n'
                                     'from "{}" to "{}" \n'
                                     'on "{}"'.format(ancestor_path,
                                                      comp_inst_path,
                                                      ancestor_inst_path,
                                                      src_layer))
                        return True
        return False

    @staticmethod
    def get_specs_at_path(node_path, layers):
        """Give a node path and a list of layers this method will look up the
        node path on each layer and return a list of SpecNode objects at
        that path. If no node is found at the given path for any layer
        nothing will be added to the list, this may result in the return list
        length being shorter than the input layer list.
        :param node_path: string of node path
        :param layers: list of SpecLayer objects
        :return: list of SpecNode objects
        """
        specs = []
        for layer in layers:
            spec = layer.lookup(node_path)
            if spec is not None:
                specs += [spec]
        return specs

    def get_attr_as_real_data_type(self, node, attr, layer, _globals=None):
        """Resolves the attribute value specified and evaluates it to the python
        type it's syntax indicates, if possible.
        If node.attr is 5
            [${/node.attr}, 123]
            converts to
            [5, 123]
        :param node: Node object
        :param attr: String of name of node attr
        :param layer: Layer object used to resolve tokens in
        """
        unresolved = getattr(node, attr)
        if not isinstance(unresolved, (str, unicode)):
            return unresolved
        resolved = self.resolve(node, unresolved, layer)
        typ = determine_nxt_type(resolved)
        if typ not in ('NoneType', 'raw', 'str'):
            code_str = "{type_name}({value})".format(type_name=typ,
                                                     value=resolved)
            if not _globals:
                _globals = {}
            try:
                real = eval(code_str, _globals)
            except SyntaxError as err:
                node_path = layer.get_node_path(node)
                attr_path = nxt_path.make_attr_path(node_path, attr)
                # 2to3 check these tuples
                # There are 3 types of syntax error, they share tuple order
                err_type = type(err)
                after_args = list(err.args[1])
                # replace offending code with raw value of attr
                after_args[3] = resolved
                # offset position of error to match raw value
                # rather than code_str we built
                after_args[2] = after_args[2] - (len(typ) + 2)
                new_err = err_type(err.args[0], tuple(after_args))
                raise GraphSyntaxError(new_err, layer.real_path, attr_path,
                                       err.lineno)
            except Exception as err:
                lineno = get_traceback_lineno(err_depth=1)
                bad_line = resolved.split('\n')[lineno-1]
                node_path = layer.get_node_path(node)
                attr_path = nxt_path.make_attr_path(node_path, attr)
                _, _, tb = sys.exc_info()
                raise GraphError(err, tb, layer.real_path, attr_path, lineno,
                                 bad_line, err_depth=1)
        elif typ in ('raw', 'str'):
            real = resolved
        else:
            real = None
        return real

    def get_node_attr_external_sources(self, node, attr_name, layer):
        """Get a list of paths to attributes that the given attribute
        includes in it's value. This
        is similar to get_attr_refs, but excludes local attribute paths
        like ${self.attr_name} and ${attr_name}
        :param node: Node that contains attr.
        :type node: comptree.CompTreeNode
        :param attr_name: Name of attr
        :type attr_name: str
        :param layer: root node to find node under
        :type layer: comptree.CompTreeNode
        :return: List of paths to attributes that the given attribute
        includes in it's value
        :rtype: list
        """
        layer = layer or self.top_layer
        attr_value = self.get_node_attr_value(node, attr_name, layer,
                                              resolved=False)
        attr_tokens = self.get_tokens_from(str(attr_value),
                                           token_type=TOKENTYPE.ATTR)
        out_refs = []
        for token in attr_tokens:
            ref = tokens.get_token_content(token)
            if not nxt_path.is_attr_path(ref):
                continue
            node_path = layer.get_node_path(node)
            expanded = nxt_path.expand_relative_node_path(ref, node_path)
            out_refs.append(expanded)
        return out_refs

    def get_node_code_external_sources(self, node, layer):
        layer = layer or self.top_layer
        code_string = self.get_node_code_string(node=node, layer=layer,
                                                data_state=DATA_STATE.RAW)
        attr_tokens = self.get_tokens_from(code_string,
                                           token_type=TOKENTYPE.ATTR)
        out_refs = []
        for token in attr_tokens:
            ref = tokens.get_token_content(token)
            if not nxt_path.is_attr_path(ref):
                continue
            node_path = layer.get_node_path(node)
            expanded = nxt_path.expand_relative_node_path(ref, node_path)
            out_refs.append(expanded)
        return out_refs

    def get_node_code_string(self, node, layer, data_state=DATA_STATE.RAW):
        """Returns the compute code as a string where each line is on a new line.

        :param node: Node to retrieve compute string from.
        :type node: comptree.CompTreeNode

        :param data_state: Whether to return the code with attr_refs resolved or not.
        :type data_state: bool
        :param layer: node to consider root
        :type layer: comptree.CompTreeNode
        :return: The compute string of the given node.
        :rtype: str
        """
        if data_state not in [DATA_STATE.RAW, DATA_STATE.RESOLVED]:
            data_state = DATA_STATE.RAW
        code_lines = self.get_node_code_lines(node=node, layer=layer,
                                              data_state=data_state)
        return '\n'.join(code_lines)

    def get_node_code(self, node, layer, custom_code=None):
        """Converts node's compute lines into a code object. If an exception is
        raised while we try to compile the compute code we log it and
        raise a GraphError.
        :param node: CompNode
        :param layer: CompLayer
        :param custom_code: String of code to used instead of the node's
        actual compute.
        :return: code
        """
        if custom_code:
            func_lines = custom_code
            code_lines = func_lines.split('\n')
        else:
            resolved = DATA_STATE.RESOLVED
            code_lines = self.get_node_code_lines(node=node, layer=layer,
                                                        data_state=resolved)
            # Ensures the compute complies and executes with correct line
            # numbers even if the compute is/startswith huge comment.
            line_zero = ['self = self']
            func_lines = '\n'.join(line_zero + code_lines)
        path = layer.get_node_path(node)
        try:
            _code = compile(func_lines, path, 'exec')
        except SyntaxError as err:
            # 2to3 check these tuples
            lineno = err.lineno - 1
            # There are 3 types of syntax error, they share tuple order
            err_type = type(err)
            after_args = list(err.args[1])
            # replacing linenumber part with our offset line number
            after_args[1] = lineno
            new_err = err_type(err.args[0], tuple(after_args))
            raise GraphSyntaxError(new_err, layer.real_path, path, lineno)
        return _code, code_lines

    def get_node_code_lines(self, node, layer, data_state=DATA_STATE.RAW):
        """Returns a copy of the list of code lines on the given node.
        :param node: Node to retrieve compute string from.
        :type node: Node object
        :param layer: Layer object
        :type layer: SpecLayer or CompLayer
        :param data_state: if DATA_STATE.RESOLVED is received the compute
        lines will be resolved otherwise we return the raw value.
        :type data_state: str
        :return: The compute string of the given node.
        :rtype: str
        """
        code_lines = getattr(node, INTERNAL_ATTRS.COMPUTE, [])
        if data_state == DATA_STATE.RESOLVED:
            return [str(self.resolve(node, line, layer))
                    for line in code_lines]
        else:
            return code_lines[:]

    def set_node_code_lines(self, node, code_lines, comp_layer):
        node_path = get_node_path(node)
        comp_node = comp_layer.lookup(node_path)
        new_comp_lines = None
        if not code_lines:
            inst, _ = self.safe_get_node_instance(comp_node, comp_layer)
            if inst:
                new_comp_lines = getattr(inst, INTERNAL_ATTRS.COMPUTE)
        self.clear_code_lines(node)
        live_lines = getattr(node, INTERNAL_ATTRS.COMPUTE)
        live_lines.extend(code_lines)

        live_comp_code = getattr(comp_node, INTERNAL_ATTRS.COMPUTE)
        if not code_lines and new_comp_lines is None:
            arcs = CompArc.get_bases_arc_dict(comp_node, comp_layer)
            refs = arcs.get(CompArc.REFERENCE, [])
            for ref in refs:
                _code = getattr(ref, INTERNAL_ATTRS.COMPUTE)
                if _code:
                    new_comp_lines = _code
                    break
        if new_comp_lines is None:
            new_comp_lines = live_lines
        if live_comp_code is not live_lines or not live_lines:
            setattr(comp_node, INTERNAL_ATTRS.COMPUTE, new_comp_lines)
            live_comp_code = new_comp_lines

        for dirty_path in comp_layer.get_node_dirties(node_path):
            dirty_comp = comp_layer.lookup(dirty_path)
            if not dirty_comp:
                break
            arcs = CompArc.get_bases_arc_dict(dirty_comp, comp_layer)
            refs = arcs.get(CompArc.REFERENCE, [])
            stop = False
            for ref in refs:
                if getattr(ref, INTERNAL_ATTRS.COMPUTE):
                    stop = True
                    break
            if stop:
                break
            old_dirty_code = getattr(dirty_comp, INTERNAL_ATTRS.COMPUTE)
            if live_comp_code is old_dirty_code and old_dirty_code:
                break
            setattr(dirty_comp, INTERNAL_ATTRS.COMPUTE, live_comp_code)
        return live_lines

    @staticmethod
    def clear_code_lines(node):
        del getattr(node, INTERNAL_ATTRS.COMPUTE)[:]

    def get_node_local_attrs_data(self, node):
        raise NotImplementedError

    def create_instance_node(self, source_path, tgt_path, comp_layer,
                             new_tgt_ns=None):
        """Creates an instance node and adds it to the comp layer. Returns
        the new instance node if it isn't an implied node, otherwise returns
        False.
        :param source_path: String of path instancing from
        :param tgt_path: String of path instancing to (could be new node path)
        :param comp_layer: NxtCompLayer
        :param new_tgt_ns: Namespace list of tgt_path
        :return: NxtCompNode or False
        """
        implied = False
        if new_tgt_ns is None:
            new_tgt_ns = nxt_path.str_path_to_node_namespace(tgt_path)
        inst_source_node = comp_layer.lookup(source_path)
        if not inst_source_node:
            # return
            data = {INTERNAL_ATTRS.as_save_key(INTERNAL_ATTRS.NAME):
                        nxt_path.node_name_from_node_path(source_path)}
            inst_pp = nxt_path.get_parent_path(source_path)
            inst_source_node = create_spec_node(data, comp_layer,
                                                parent_path=inst_pp)
            implied = True

        target_parent_path = nxt_path.get_parent_path(tgt_path)
        existing_node = comp_layer.lookup(tgt_path)
        layer = self.lookup_layer(getattr(inst_source_node,
                                          INTERNAL_ATTRS.SOURCE_LAYER))
        if existing_node is None:
            i_dat = {INTERNAL_ATTRS.as_save_key(INTERNAL_ATTRS.NAME):
                         getattr(inst_source_node, INTERNAL_ATTRS.NAME),
                     INTERNAL_ATTRS.as_save_key(INTERNAL_ATTRS.COMMENT):
                         getattr(inst_source_node, INTERNAL_ATTRS.COMMENT),
                     INTERNAL_ATTRS.as_save_key(INTERNAL_ATTRS.ENABLED):
                         getattr(inst_source_node, INTERNAL_ATTRS.ENABLED),
                     INTERNAL_ATTRS.as_save_key(INTERNAL_ATTRS.SOURCE_LAYER):
                         getattr(inst_source_node, INTERNAL_ATTRS.SOURCE_LAYER),
                     INTERNAL_ATTRS.as_save_key(INTERNAL_ATTRS.PARENT_PATH):
                         target_parent_path}
            spec_node = create_spec_node(i_dat, layer,
                                         parent_path=target_parent_path,
                                         is_proxy=True)
            new_target = CompNode.new(spec_node=spec_node)
            self.add_node_to_comp_layer(tgt_path, new_target, comp_layer,
                                        ns=new_tgt_ns)
            # Setting the instance path on the comp node because it is
            # persistent if and when the node is localized.
            setattr(new_target, INTERNAL_ATTRS.INSTANCE_PATH, source_path)
            setattr(new_target,
                    INTERNAL_ATTRS.INSTANCE_PATH + META_ATTRS.SOURCE,
                    (layer.real_path, source_path))
        else:
            new_target = existing_node
            setattr(existing_node, INTERNAL_ATTRS.INSTANCE_PATH, source_path)
            setattr(existing_node,
                    INTERNAL_ATTRS.INSTANCE_PATH + META_ATTRS.SOURCE,
                    (layer.real_path, source_path))
        self.extend_dirty_map(source_path, tgt_path, comp_layer._dirty_map)
        if not implied:
            return new_target
        else:
            return False

    @staticmethod
    def namespace_merger(source_ns, target_ns):
        """Smartly merges instance namespaces `source_ns` into `target_ns`.
        Example 1:
            source = ['Character', 'build', 'legs', 'left']
            target = ['dummy', 'build', 'legs']
            return == ['dummy', 'build', 'legs', 'left']
        Example 2:
           source = ['control', 'create']
           target = ['leg', 'create', 'fk', 'controls', 'upper']
           return = ['leg', 'create', 'fk', 'controls', 'upper', 'create']
        :param source_ns: List of strings representing an instance source
        namespace
        :param target_ns: List of strings representing an instance
        target namespace
        :return: Merged list of string  representing an instance child
        namespace
        """
        len_source = len(source_ns)
        len_target = len(target_ns)
        target_parent_path = target_ns[:-1] if len_target > 1 and len_source else target_ns
        matched_path = target_parent_path
        changed = False
        if len_source > len_target and source_ns[0] != target_ns[0]:
            begin = 1 if len_source > 1 else 0
            source_suffix = source_ns[begin:]
            suffix_len = len(source_suffix)
            for i, item in enumerate(target_ns):
                snip = target_ns[i:i + suffix_len]
                if snip == source_suffix[:-begin]:
                    matched_path = matched_path[:i] + source_suffix
                    changed = True
            if not changed:
                matched_path = target_ns + source_ns[len_target:]
        elif len_target > len_source and len_source:
            begin = 1 if len_source > 1 else 0
            source_suffix = source_ns[begin:]
            suffix_len = len(source_suffix)
            for i, item in enumerate(target_ns):
                snip = target_ns[i:i + suffix_len]
                if snip == source_suffix[:-begin]:
                    matched_path = matched_path[:i] + source_suffix
                    changed = True
            if not changed:
                matched_path = target_ns + source_suffix
        elif len_target == len_source:
            for i, (s, t) in enumerate(zip(source_ns, target_ns)):
                if i == 0:
                    matched_path = [t]
                elif s == t:
                    matched_path += [t]
                elif i + 1 in range(len_target) and target_ns[i + 1] == s:
                    if source_ns[i - 1] == t:
                        matched_path += source_ns[i - 1:]
                    else:
                        matched_path += [t]
                        matched_path += source_ns[i:]
                    break
                elif i - 1 in range(len_source) and source_ns[i - 1] == t:
                    if source_ns[i - 1] == t:
                        matched_path += source_ns[i - 1:]
                    else:
                        matched_path += [t]
                        matched_path += source_ns[i:]
                else:
                    matched_path += source_ns[i:]
                    break
        elif len_source and source_ns[0] == target_ns[0]:
            longer = source_ns if len_source > len_target else target_ns
            short = source_ns if len_source < len_target else target_ns
            for i, item in enumerate(short):
                if i + 1 in range(len(longer)) and longer[i] != item:
                    matched_path = short[:i + 1] + longer[i + 1:]
        return matched_path

    def new_layer(self, logical_index=int, layer_data=dict):
        start = time.time()
        if logical_index is int:
            logical_index = len(self._sub_layers)
        if layer_data is dict:
            layer_data = {}
        layer = SpecLayer(layer_data)
        self.register_layer(layer, logical_index)
        build_time = str(int(round((time.time() - start) * 1000)))
        logger.info("New layer build time: " + build_time + 'ms')
        return layer

    def register_layer(self, layer, logical_index=None):
        if logical_index is None:
            logical_index = len(self._sub_layers)
        self._sub_layers.insert(logical_index, layer)
        layer._layer_idx = logical_index

    def build_stage(self, from_idx=0):
        build_start_time = time.time()
        sub_layer_count = len(self._sub_layers)
        comp_layer = CompLayer()
        comp_layer.uid = nxt_uuid(from_idx + sub_layer_count)
        comp_layer._layer_range = (from_idx, sub_layer_count)
        comp_layer.collapse = copy.copy(self.top_layer.collapse)
        # Pull out the layers we need for this comp based on the from_idx arg
        sub_layers = []
        i = sub_layer_count
        for layer in reversed(self._sub_layers):
            comp_layer.positions.update(layer.positions)
            comp_layer.collapse.update(layer.collapse)
            if i > from_idx:
                sub_layers = [layer] + sub_layers
            i -= 1
        # Assign layer parents
        self.assign_layer_parents(sub_layers)
        # Remove muted layers
        active_layers = get_active_layers(sub_layers)
        active_layer_count = len(active_layers)
        if active_layer_count < 1:
            logger.compinfo('All layers muted!')
            return comp_layer
        comp_layer.cwd = active_layers[0].get_cwd()
        comp_layer.real_path = active_layers[0].real_path
        # Would prefer to set this during console construction, would need
        # to move real path into comp layer construction.
        comp_layer._console.layer_path = comp_layer.real_path
        '''Organize all the nodes we're going to comp'''
        for sub_layer in active_layers:
            # Sort the layer node table since we do not know if its sorted
            sub_layer.sort_node_table()
            comp_layer._sublayer_node_tables += [sub_layer._node_table]
            del sub_layer
        if not comp_layer._sublayer_node_tables:
            logger.compinfo("No nodes found!")
            return comp_layer
        '''Pre proxy comp'''
        node_count = self.comp_pre_proxies(comp_layer=comp_layer)
        '''Proxy comp'''
        proxy_count, loops = self.comp_proxies(comp_layer=comp_layer,
                                               node_count=node_count)
        '''Post proxy comp'''
        root_count, total_count = self.post_proxy_comp(comp_layer=comp_layer)
        logger.compinfo(('Number of nodes -->', total_count))
        logger.compinfo(('Number of roots --> ', root_count))
        logger.compinfo(('Number of instances created --> ', proxy_count))
        logger.compinfo(('Number of layers --> ', active_layer_count))
        logger.compinfo(('Number of loops --> ', loops))
        build_time = str(int(round((time.time() - build_start_time) * 1000)))
        logger.compinfo("New comp layer created in: " + build_time + 'ms')
        return comp_layer

    def comp_pre_proxies(self, comp_layer):
        """Loops the pre comp arcs as defined by CompModes. This method
        expects that the following comp layer
        attributes are empty dicts or lists
        respectively.
            '_nodes_path_as_key'
            '_nodes_node_as_key'
            '_node_table'
        :param comp_layer: CompLayer
        :return: Int of node count
        """
        node_count = 0
        _path_data = comp_layer._nodes_path_as_key
        _node_data = comp_layer._nodes_node_as_key
        _node_table = comp_layer._node_table
        base_mapping = {}
        # Loop sub layers (strong to weak) and create/add empty comp nodes
        for sub_layer_node_table in comp_layer._sublayer_node_tables:
            for namespace, spec_node in sub_layer_node_table:
                # Get node path from its namespace
                comp_node_path = nxt_path.node_namespace_to_str_path(namespace)
                # If strong match stays None we just add the node to the layer
                stronger_match = comp_layer.lookup(comp_node_path)
                bases = base_mapping.get(comp_node_path, [])
                # Add this to the bases list
                bases += [spec_node]
                if stronger_match:
                    # Node is already a comp node, we'll deal with it later
                    continue
                # New comp node
                attrs = {INTERNAL_ATTRS.NAME: getattr(spec_node,
                                                      INTERNAL_ATTRS.NAME)
                         }
                comp_node = CompNode.new(spec_node=spec_node, attrs=attrs)
                self.add_node_to_comp_layer(path=comp_node_path,
                                            comp_node=comp_node,
                                            comp_layer=comp_layer, ns=namespace,
                                            add_to_child_order=False)
                base_mapping[comp_node_path] = bases
                node_count += 1
                del spec_node, namespace, comp_node_path, comp_node
        # Loop pre comp arcs
        for arc in CompArc.PRE_PROXY_ARCS:
            overload_attrs = set(CompArc.INHERITANCE_MAP[arc] +
                                 INTERNAL_ATTRS.TRACKED)
            if arc == CompArc.REFERENCE:
                # Loop the empty comp nodes we just created
                for ref_node_path, bases in base_mapping.items():
                    comp_node = comp_layer.lookup(ref_node_path)
                    # Populate the comp node bases tuple with node specs who
                    # share the same node path from different layers
                    self._replace_base_classes(comp_node, tuple(bases))
                    idx = 0
                    for spec_node in reversed(bases):
                        if idx == 0:
                            child_order = getattr(spec_node,
                                                  INTERNAL_ATTRS.CHILD_ORDER)
                            setattr(comp_node, INTERNAL_ATTRS.CHILD_ORDER,
                                    child_order)
                        for intern_attr in overload_attrs:
                            attr_value, has = get_opinion(spec_node,
                                                          intern_attr)
                            if has:
                                src_layer = getattr(spec_node,
                                                    INTERNAL_ATTRS.SOURCE_LAYER)
                                setattr(comp_node, intern_attr, attr_value)
                                src_attr = intern_attr + META_ATTRS.SOURCE
                                setattr(comp_node, src_attr, (src_layer,
                                                              ref_node_path))
                        idx += 1
                        if ref_node_path == nxt_path.WORLD:
                            continue
                        # Merge the child order from the spec to the comp node
                        spec_co = getattr(spec_node, INTERNAL_ATTRS.CHILD_ORDER)
                        comp_co = getattr(comp_node, INTERNAL_ATTRS.CHILD_ORDER)
                        child_order_overload = list_merger(spec_co,
                                                           comp_co)
                        setattr(comp_node, INTERNAL_ATTRS.CHILD_ORDER,
                                child_order_overload)
                        del spec_node
                    del bases, idx, comp_node, ref_node_path
            del arc
        return node_count

    def targeted_comp_pre_proxies(self, spec_node, new_node_path, comp_layer,
                                  target_layer):
        """Adds a single node to a comp layer, loops the same arcs as
        `pre_proxy_comp`, the logic is slightly different as we are doing
        targeted work on the comp layer.
        :param spec_node: SpecNode
        :param new_node_path: String of node path
        :param comp_layer: CompLayer
        :param target_layer: SpecLayer
        :return: CompNode
        """
        # Search the node path in the comp layer
        comp_node = comp_layer.lookup(new_node_path)
        reference_map = {CompArc.REFERENCE: None}
        if comp_node is None:
            comp_node = self.add_node_to_comp_layer(new_node_path, spec_node,
                                                    comp_layer)
        else:  # If a node exists at the node path we insert our new spec
            # into it's bases tuple
            tgt_idx = target_layer.layer_idx()
            existing_bases = list(comp_node.__bases__)
            bases = []
            inserted = False
            i = 0
            # Handle reference bases
            for base in existing_bases:
                is_comp_node = base.__name__ == CompNode.__name__
                src_layer = getattr(base, INTERNAL_ATTRS.SOURCE_LAYER)
                sub_layer = self.lookup_layer(src_layer)
                sub_layer_idx = sub_layer.layer_idx()
                # We assume there are no spec nodes after the first comp node
                # in the tuple
                if sub_layer_idx > tgt_idx or is_comp_node:
                    # If the spec node's layer index is higher than ours
                    # it means we need to insert before it as we are stronger
                    bases += [spec_node]
                    bases += [b for b in existing_bases[i:] if
                              CompArc.get_arc(comp_node, b, comp_layer) ==
                              CompArc.REFERENCE]
                    inserted = True
                    break
                i += 1
            if not inserted:  # Failsafe to insert new node into tuple
                bases += [spec_node]
            # Rough outline for future extension of pre proxy arcs
            reference_map[CompArc.REFERENCE] = tuple(bases)
            reference_map[CompArc.INSTANCE] = ()
            reference_map[CompArc.PARENT] = ()
            # Handle non-reference arcs
            for b in existing_bases[i:]:
                arc = CompArc.get_arc(comp_node, b, comp_layer)
                if not arc:
                    logger.critical('Unexpected base class found, please '
                                    're-comp!')
                    continue
                # References were taken care of in the above loop
                elif arc == CompArc.REFERENCE:
                    continue
                reference_map[arc] += (b,)

        for arc in CompArc.PRE_PROXY_ARCS:
            updated_base_classes = reference_map.get(arc)
            if not updated_base_classes:
                continue
            update = False
            for b in updated_base_classes:
                if b in comp_node.__bases__:
                    update = True
                    break
            if update:
                self._update_base_classes(comp_node, updated_base_classes)
            else:
                self._replace_base_classes(comp_node, updated_base_classes)

            overload_attrs = CompArc.INHERITANCE_MAP[arc]
            for spec_node in reversed(updated_base_classes):
                for intern_attr in INTERNAL_ATTRS.TRACKED:
                    attr_value, comp_has_op = get_opinion(spec_node,
                                                          intern_attr)
                    if not comp_has_op:
                        continue
                    src_layer = getattr(spec_node, INTERNAL_ATTRS.SOURCE_LAYER)
                    overload = intern_attr in overload_attrs
                    if overload and comp_has_op:
                        setattr(comp_node, intern_attr, attr_value)
                        src_attr = intern_attr + META_ATTRS.SOURCE
                        setattr(comp_node, src_attr, (src_layer, new_node_path))
        return comp_node

    def targeted_comp_proxies(self, comp_node, node_path, comp_layer):
        """Given a comp node and a comp layer this function will discover,
        generate, and add to the comp layer proxy nodes needed by the comp
        node. The newly generated nodes are not fully composited,
        this function simply creates the mapping for compping the new nodes.
        In the end it produces a proxy map used by the post_proxy_comp
        function. This process is iterative, not recursive.
        :param comp_node: NxtCompNode
        :param node_path: String of node path
        :param comp_layer: CompLayer
        :return: proxy_map dict
        """
        proxy_map = {}
        parent_path = getattr(comp_node, INTERNAL_ATTRS.PARENT_PATH)
        dirty_nodes = comp_layer.get_node_dirties(parent_path)
        proxy_targets = comp_layer.get_node_dirties(node_path)
        parent_node = comp_layer.lookup(parent_path)
        if not parent_node and parent_path != '':
            while parent_path != nxt_path.WORLD:
                parent_path = nxt_path.get_parent_path(parent_path)
                parent_node = comp_layer.lookup(parent_path)
                if parent_node:
                    break
        inst_path = getattr(comp_node, INTERNAL_ATTRS.INSTANCE_PATH, None)
        inst_path = nxt_path.expand_relative_node_path(inst_path, node_path)
        if inst_path != nxt_path.WORLD:
            instance_node = comp_layer.lookup(inst_path)
        else:
            instance_node = None
        proxy_map[comp_node] = {CompArc.PARENT: parent_node,
                                CompArc.INSTANCE: instance_node}
        for proxy_parent_path in dirty_nodes:
            if proxy_parent_path == node_path:
                continue
            comp_node_name = getattr(comp_node, INTERNAL_ATTRS.NAME)
            inst_tgt_path = nxt_path.join_node_paths(proxy_parent_path,
                                                     comp_node_name)
            inst_tgt_node = comp_layer.lookup(inst_tgt_path)
            if inst_tgt_node is not None:
                continue
            inst_node = self.create_instance_node(node_path,
                                                      inst_tgt_path,
                                                      comp_layer)
            if inst_node:
                arc_dict = proxy_map.get(inst_node, {})
                proxy_parent_node = comp_layer.lookup(proxy_parent_path)
                arc_dict[CompArc.PARENT] = proxy_parent_node
                arc_dict[CompArc.INSTANCE] = comp_node
                proxy_map[inst_node] = arc_dict
        for proxy_target_path in proxy_targets:
            if proxy_target_path == node_path:
                continue
            proxy_target = comp_layer.lookup(proxy_target_path)
            if proxy_target is None:
                continue
            arc_dict = proxy_map.get(proxy_target, {})
            arc_dict[CompArc.INSTANCE] = comp_node
            proxy_map[proxy_target] = arc_dict
        if not instance_node:
            return proxy_map
        inst_src_descendants = comp_layer.descendants(inst_path,
                                                      ordered=True)
        src_dirties = comp_layer.get_node_dirties(node_path)
        current_nodes = [comp_node]
        for des in inst_src_descendants:
            dirties = comp_layer.get_node_dirties(des)
            inst_src_node = comp_layer.lookup(des)
            for tgt_path in dirties:
                skip = False
                inst_node = comp_layer.lookup(tgt_path)
                if not inst_node:
                    for src_d in src_dirties:
                        if nxt_path.is_ancestor(tgt_path, src_d):
                            skip = True
                            break
                    if skip:
                        continue
                    inst_node = self.create_instance_node(des, tgt_path,
                                                          comp_layer)
                else:
                    cur_inst = getattr(inst_node,
                                       INTERNAL_ATTRS.INSTANCE_PATH, None)
                    if cur_inst != des:
                        setattr(inst_node, INTERNAL_ATTRS.INSTANCE_PATH, des)
                arc_dict = proxy_map.get(inst_node, {})
                proxy_parent_path = nxt_path.get_parent_path(tgt_path)
                proxy_parent_node = comp_layer.lookup(proxy_parent_path)
                arc_dict[CompArc.PARENT] = proxy_parent_node
                arc_dict[CompArc.INSTANCE] = inst_src_node
                proxy_map[inst_node] = arc_dict
                current_nodes += [inst_node]
        node_count = 0
        new_node_count = -1
        implied_proxies = []
        while node_count != new_node_count:
            new_node_count = node_count
            to_do = []
            new_nodes = []
            for node in current_nodes:
                node_path = comp_layer.get_node_path(node)
                to_do += self.discover_proxies(node_path, node, comp_layer)
            # Create and add new proxy nodes to the comp layer
            for new_tgt_ns, new_source_path, new_tgt_path, in to_do:
                implied = False
                if not comp_layer.lookup(new_tgt_path):
                    implied = self.create_instance_node(new_source_path,
                                                        new_tgt_path, comp_layer,
                                                        new_tgt_ns)
                    node_count += 1
                if not implied:
                    implied_node = comp_layer.lookup(new_tgt_path)
                    implied_proxies += [(implied_node, new_tgt_path,
                                         new_tgt_ns)]
                else:
                    new = comp_layer.lookup(new_tgt_path)
                    cur_inst = getattr(new,
                                       INTERNAL_ATTRS.INSTANCE_PATH, None)
                    if cur_inst != new_source_path:
                        setattr(new, INTERNAL_ATTRS.INSTANCE_PATH,
                                new_source_path)
                    inst_src_node = comp_layer.lookup(new_source_path)
                    arc_dict = proxy_map.get(new, {})
                    proxy_parent_path = nxt_path.get_parent_path(new_tgt_path)
                    proxy_parent_node = comp_layer.lookup(proxy_parent_path)
                    arc_dict[CompArc.PARENT] = proxy_parent_node
                    arc_dict[CompArc.INSTANCE] = inst_src_node
                    proxy_map[new] = arc_dict
                    new_nodes += [new]
            current_nodes += new_nodes
        for implied_proxy, implied_proxy_path, ns in implied_proxies:
            self.remove_node_from_comp_layer(implied_proxy_path,
                                             implied_proxy, comp_layer,
                                             ns=ns,
                                             rm_from_child_order=False,
                                             rm_layer_data=False)
        return proxy_map

    def discover_proxies(self, node_path, comp_node, comp_layer):
        """Given a node and the current comp layer this function will return
        a multi list of proxy nodes that need to be created. Its called
        discover because it must be called many times as we discover nodes
        that need to be created we don't yet know if those discoveries
        themselves need to generate proxies.
        The return is sorted by namespace depth, shallow to deep.
        :param node_path: String of node path
        :param comp_node: NxtCompNode
        :param comp_layer: CompLayer
        :return: sorted list of tuples [(target_ns, src_path, tgt_path)]
        """
        to_do = []
        namespace = nxt_path.str_path_to_node_namespace(node_path)
        instance_path = getattr(comp_node,
                                INTERNAL_ATTRS.INSTANCE_PATH, None)
        if not instance_path:
            return to_do
        _expand = nxt_path.expand_relative_node_path
        if instance_path == nxt_path.WORLD:
            logger.error("Invalid instance path on {}".format(node_path),
                         links=[node_path])
            return to_do
        real_inst_path = _expand(instance_path, node_path)
        setattr(comp_node, INTERNAL_ATTRS.INSTANCE_PATH, real_inst_path)
        self.extend_dirty_map(real_inst_path, node_path,
                              comp_layer._dirty_map)
        real_inst_ns = nxt_path.str_path_to_node_namespace(
            real_inst_path)
        len_real_instance_path = len(real_inst_ns)
        # Filter stray nodes
        if real_inst_path in comp_layer._nodes_path_as_key.keys():
            inst_source_node = comp_layer.lookup(real_inst_path)
            comp_co = getattr(comp_node, INTERNAL_ATTRS.CHILD_ORDER)
            inst_co = getattr(inst_source_node, INTERNAL_ATTRS.CHILD_ORDER)
            merged_child_order = list_merger(comp_co, inst_co)
            setattr(comp_node, INTERNAL_ATTRS.CHILD_ORDER, merged_child_order)

        '''Get children'''
        # Loop the children of the instance source and create proxy
        # nodes as needed
        children = comp_layer.children(real_inst_path,
                                       comp_layer.RETURNS.Path,
                                       include_implied=True)
        if children:
            offset = len(namespace)
        else:
            offset = 0
        for src_path in children:
            c_ns = nxt_path.str_path_to_node_namespace(src_path)
            # Handle instances from root node
            if len_real_instance_path == 1:
                split_idx = c_ns.index(real_inst_ns[0]) + 1
                trimmed_source_ns = namespace + c_ns[split_idx:]
                target_ns = trimmed_source_ns
            # Handle instances from a shallow to deep ns
            elif offset > len(c_ns):
                split_idx = c_ns.index(real_inst_ns[-1]) + 1
                trimmed_source_ns = namespace + c_ns[split_idx:]
                target_ns = trimmed_source_ns
            # Handle instances from a deep to a shallow ns
            else:
                trimmed_source_ns = c_ns[len_real_instance_path - offset:]
                target_ns = self.namespace_merger(trimmed_source_ns,
                                                  namespace)
            tgt_path = nxt_path.node_namespace_to_str_path(target_ns)
            target = comp_layer.lookup(tgt_path)
            if target:
                comp_layer.clear_node_child_cache(tgt_path)
                # Can be empty string to overload a lower layer
                ex_inst_path = getattr(target,
                                       INTERNAL_ATTRS.INSTANCE_PATH, None)
                if ex_inst_path is not '':
                    setattr(target, INTERNAL_ATTRS.INSTANCE_PATH, src_path)
            else:
                to_do += [(target_ns, src_path, tgt_path)]
        sort_multidimensional_list(to_do, 0)
        return to_do

    def comp_proxies(self, comp_layer, node_count):
        # Short variable names
        _path_data = comp_layer._nodes_path_as_key
        _node_data = comp_layer._nodes_node_as_key
        # Counters
        new_node_count = -1
        proxy_count = 0
        loops = 0
        strays = {}  # Requested instances that don't exist
        implied_proxies = []
        # Create all the proxy nodes called for by instance paths
        while node_count != new_node_count:
            new_node_count = node_count
            loops += 1
            added_inst_count = 0
            to_do = []
            for namespace, comp_node in comp_layer._node_table:
                node_path = nxt_path.node_namespace_to_str_path(namespace)
                to_do += self.discover_proxies(node_path, comp_node, comp_layer)
            sort_multidimensional_list(to_do, 0)
            # Create and add new proxy nodes to the comp layer
            for new_tgt_ns, new_source_path, new_tgt_path, in to_do:
                new = self.create_instance_node(new_source_path, new_tgt_path,
                                                comp_layer, new_tgt_ns)
                if not new:
                    implied_node = comp_layer.lookup(new_tgt_path)
                    implied_proxies += [(implied_node, new_tgt_path,
                                         new_tgt_ns)]
                node_count += 1
                added_inst_count += 1
            proxy_count += added_inst_count
        for implied_proxy, implied_proxy_path, ns in implied_proxies:
            proxy_count -= 1
            self.remove_node_from_comp_layer(implied_proxy_path,
                                             implied_proxy, comp_layer,
                                             ns=ns,
                                             rm_from_child_order=False,
                                             rm_layer_data=False)
        return proxy_count, loops

    def post_proxy_comp(self, comp_layer):
        roots = []  # List to track the root nodes
        root_count = 0  # Root node count
        total_count = 0  # Node count
        arc_idx = 0  # Used to avoid counting a node more than once
        # Instances must be sorted by their instance trace depth
        instance_sorted_nodes = self.sort_instances(comp_layer)
        for arc in CompArc.POST_PROXY_ARCS:
            overload_attrs = CompArc.INHERITANCE_MAP[arc]
            for _, comp_node in instance_sorted_nodes:
                base_path = None
                node_path = comp_layer.get_node_path(comp_node)
                if arc == CompArc.PARENT:
                    parent_path = getattr(comp_node, INTERNAL_ATTRS.PARENT_PATH)
                    if not parent_path:
                        del node_path, comp_node
                        continue
                    if not comp_layer.lookup(parent_path):
                        while parent_path != nxt_path.WORLD:
                            parent_path = nxt_path.get_parent_path(parent_path)
                            if comp_layer.lookup(parent_path):
                                break
                    base_path = parent_path
                elif arc == CompArc.INSTANCE:
                    try:
                        base_path = getattr(comp_node,
                                            INTERNAL_ATTRS.INSTANCE_PATH)
                    except AttributeError:
                        del node_path, comp_node
                        continue
                    if base_path == nxt_path.WORLD:
                        del node_path, comp_node
                        continue
                base = comp_layer._nodes_path_as_key.get(base_path)
                if not base:
                    if base_path and base_path != nxt_path.WORLD:
                        _node_data = comp_layer._nodes_node_as_key
                        _expand = nxt_path.expand_relative_node_path
                        cur_node_path = _node_data[comp_node]
                        real_path = _expand(base_path, cur_node_path)
                        if real_path != base_path:
                            real = '| ({})'.format(real_path)
                        else:
                            real = ''
                        t = (arc, base_path, real)
                        logger.error("Unable to find {} node "
                                     "for {}".format(arc, node_path),
                                     links=[node_path])
                        logger.debug('requested {} {}'.format(*t))
                    continue
                for attr in overload_attrs:
                    _, has_opinion = get_opinion(comp_node, attr)
                    attr_value, _ = get_opinion(base, attr)
                    if has_opinion:
                        continue
                    src_layer = getattr(base, INTERNAL_ATTRS.SOURCE_LAYER)
                    setattr(comp_node, attr, attr_value)
                    src_attr = attr + META_ATTRS.SOURCE
                    setattr(comp_node, src_attr, (src_layer, node_path))
                if arc == CompArc.INSTANCE:
                    self._safe_mro_add_base_class(comp_node, base)
                else:
                    self._add_base_class(comp_node, base)
                # Assemble roots and node count
                parent_path = getattr(comp_node, INTERNAL_ATTRS.PARENT_PATH)
                no_parent = parent_path == nxt_path.WORLD
                if no_parent and comp_node not in roots:
                    roots += [comp_node]
                    root_count += 1
                if arc_idx == 0:
                    total_count += 1
                del base, node_path, comp_node
            arc_idx += 1
        return root_count, total_count

    def targeted_comp_post_proxies(self, proxy_map, comp_layer=None):
        """Given a proxy map, this function finishes the compositing of nodes
        by mutating the base class tuple of each node in the proxy_map.
        The map is structured like this:
            High level terms:
                {dirty_node: arc_dict}
            Actual data:
                {NxtCompNode: {CompArc.PARENT: NxtCompNode or None,
                               CompArc.INSTANCE: NxtCompNode or None}}
        If any given arc key is None or missing in the arc dict no change is
        made in that loop.
        :param proxy_map: dict
        :param comp_layer: CompLayer
        :return: list of dirty node paths
        """
        dirty_nodes = []
        for arc in CompArc.POST_PROXY_ARCS:
            overload_attrs = CompArc.INHERITANCE_MAP[arc]
            for dirty_node, arc_dict in proxy_map.items():
                parent_path = getattr(dirty_node, INTERNAL_ATTRS.PARENT_PATH)
                name = getattr(dirty_node, INTERNAL_ATTRS.NAME)
                dirty_path = nxt_path.join_node_paths(parent_path, name)
                base = arc_dict.get(arc)
                if dirty_path not in dirty_nodes:
                    dirty_nodes += [dirty_path]
                if base is None:
                    continue

                for attr in overload_attrs:
                    _, has_op = get_opinion(dirty_node, attr)
                    if has_op:
                        continue
                    attr_value = getattr(base, attr, None)
                    src_layer = getattr(base, INTERNAL_ATTRS.SOURCE_LAYER)
                    setattr(dirty_node, attr, attr_value)
                    src_attr = attr + META_ATTRS.SOURCE
                    setattr(dirty_node, src_attr, (src_layer, dirty_path))
                self._safe_mro_add_base_class(dirty_node, base)
                if comp_layer:
                    dirty_nodes += comp_layer.get_node_dirties(dirty_path)
        return dirty_nodes

    def targeted_uncomp(self, comp_node, comp_layer,
                        target_layer, arcs=CompArc.ALL_ARCS):
        """For each arc in the arcs list remove the base class of the given
        node that corresponds to the arc name. Each arc name in the arcs list
        must map to an internal attr name in order to determine which base
        class to remove. See: CompArc.ATTR_NAMES
        Resulting in the comp node no longer inheriting from some or any arc(s).
        :param comp_node: NxtCompNode
        :param comp_layer: CompLayer
        :param target_layer: SpectLayer
        :param arcs: list of CompArc arcs
        :return: list of dirty node paths
        """
        dirties = []
        for arc in arcs:
            if arc == CompArc.REFERENCE:
                raise NotImplementedError('Can not un-comp reference arc.')
            internal_attr = CompArc.ATTR_NAMES[arc]
            arc_src_path = getattr(comp_node, internal_attr, None)
            base = comp_layer.lookup(arc_src_path)
            cur_bases = list(comp_node.__bases__)
            if base:
                cur_bases.remove(base)
            if arc == CompArc.INSTANCE:
                path = comp_layer.get_node_path(comp_node)
                parent_path = nxt_path.get_parent_path(path)
                parent_node = comp_layer.lookup(parent_path)
                if parent_node and parent_node not in cur_bases:
                    cur_bases += [parent_node]
                inst_path = getattr(comp_node, INTERNAL_ATTRS.INSTANCE_PATH,
                                    None)
                descendants = comp_layer.descendants(inst_path)
                for descendant in descendants:
                    dirties += comp_layer.get_node_dirties(descendant)
            self._replace_base_classes(comp_node, tuple(cur_bases))

        node_path = comp_layer.get_node_path(comp_node)
        descendants = comp_layer.descendants(node_path)
        ripple_deletes = set([d for d in dirties if d in descendants])
        for dirty_path in ripple_deletes:
            dirty_node = comp_layer.lookup(dirty_path)
            if dirty_node and getattr(dirty_node, INTERNAL_ATTRS.PROXY):
                self.ripple_delete(dirty_path, dirty_node, target_layer,
                                   comp_layer)
            elif dirty_node and CompArc.INSTANCE in arcs:
                tgt_node = target_layer.lookup(dirty_path)
                self.targeted_uncomp(dirty_node, comp_layer, target_layer,
                                     [CompArc.INSTANCE])
                tgt_inst = getattr(tgt_node, INTERNAL_ATTRS.INSTANCE_PATH, None)
                expanded = nxt_path.expand_relative_node_path(tgt_inst,
                                                              node_path)
                if expanded != getattr(dirty_node,
                                       INTERNAL_ATTRS.INSTANCE_PATH):
                    setattr(dirty_node, INTERNAL_ATTRS.INSTANCE_PATH, expanded)
        return dirties

    @staticmethod
    def _add_base_class(comp_node, base):
        if not base:
            logger.error('Invalid baseclass provided!')
            return
        comp_node.__bases__ += (base,)

    @staticmethod
    def _replace_base_classes(comp_node, bases):
        if None in bases:
            logger.error('Invalid baseclass(es) in provided bases tuple!')
            bases = tuple([b for b in bases if b is not None])
            if not bases:
                logger.critical('No valid bases found in the bases tuple!')
                return
        if bases != comp_node.__bases__:
            comp_node.__bases__ = bases
        return

    def _update_base_classes(self, comp_node, bases):
        existing = list(comp_node.__bases__)
        incoming = list(bases)
        updated_bases = tuple(list_merger(existing, incoming))
        self._replace_base_classes(comp_node, updated_bases)

    def _safe_mro_add_base_class(self, comp_node, base):
        current_bases = comp_node.__bases__
        if base in current_bases:
            return
        incoming_bases = base.__bases__
        safe_weak_bases = list(current_bases)
        changed = False
        for c in current_bases:
            for b in incoming_bases:
                incoming_mro = b.__mro__
                if c in incoming_mro and c in safe_weak_bases:
                    safe_weak_bases.remove(c)
                    changed = True
        if changed:
            safe_bases = tuple(safe_weak_bases) + (base,)
            self._replace_base_classes(comp_node, safe_bases)
        else:
            self._add_base_class(comp_node, base)

    def sort_instances(self, comp_layer):
        """Sorts instances based on the length of their trace list. An
        instance trace list is every node that is directly or indirectly
        instanced by the node in question.
        :param comp_layer: CompLayer
        :return: Sorted list of instance target nodes
        """
        inst_sorted_nodes = []
        for _, node in comp_layer._node_table:
            trace = self.get_instance_sources(node, [], comp_layer)
            inst_sorted_nodes += [(trace, node)]
        sort_multidimensional_list(inst_sorted_nodes, sort_by_idx=0)
        return inst_sorted_nodes

    @staticmethod
    def get_instance_sources(node, trace_list, comp_layer):
        """Fill a list (trace_list) with all of the nodes in the instance
        source trace of the node on the comp_layer. This function is
        recursive, the trace_list is passed forward during recursion.
        :param node: NxtCompNode
        :param trace_list: list object to be filled
        :param comp_layer: CompLayer
        :return: trace_list (same object you provided when calling)
        """
        try:
            inst_path = getattr(node, INTERNAL_ATTRS.INSTANCE_PATH)
        except AttributeError:
            return trace_list
        n = comp_layer.lookup(inst_path)
        if n is not None and n not in trace_list:
            trace_list += [n]
            Stage.get_instance_sources(n, trace_list, comp_layer)
        return trace_list

    def get_instance_targets(self, inst_source_path, target_list, comp_layer):
        returns = comp_layer.RETURNS.NodeTable
        for _, node in comp_layer.descendants(return_type=returns):
            try:
                inst_path = getattr(node, INTERNAL_ATTRS.INSTANCE_PATH)
            except AttributeError:
                continue
            if inst_path != inst_source_path:
                continue
            target_list += [self.get_node_spec(node)]
            node_path = comp_layer.get_node_path(node)
            self.get_instance_targets(node_path, target_list, comp_layer)
        return target_list

    @staticmethod
    def extend_dirty_map(node_path, concern, dirty_map):
        """Adds node path to concerns map if it is not in the dict and adds
        the concern to its concern list.
        :param node_path: String of node path
        :param concern: Node path of node that `node_path` should be
        concerned with
        :param dirty_map: Dict of concerns {node/path: [other/node/path]}
        :return: Dict
        """
        if node_path == nxt_path.WORLD or concern == nxt_path.WORLD:
            return dirty_map
        node_concerns = dirty_map.get(node_path, [])
        if not node_concerns:
            dirty_map[node_path] = node_concerns
        if concern != node_path and concern not in node_concerns:
            node_concerns += [concern]
        return dirty_map

    @staticmethod
    def remove_from_dirty_map(node_path, dirty_map):
        if node_path == nxt_path.WORLD:
            return dirty_map
        if node_path in dirty_map.keys():
            dirty_map.pop(node_path)
        for k, v in dirty_map.items():
            if node_path in v:
                v.remove(node_path)
        return dirty_map

    def get_layers_with_opinion(self, node_path, layer_list=None,
                                attr_name=None):
        """Returns all layers in given layer list(or current stage) that
        contain the given node_path. Ordered with the top layer at 0.

        :param node_path: path to find layers for.
        :type node_path: str
        :param layer_list: list of layers to check, defaults to None. If not
        given, all layers in stage will be checked.
        :type layer_list: list, optional
        :param attr_name: Optional: name of specific attr that must have an
        opinion at the given node path.
        :type attr_name: str
        :return: list of layers
        :rtype: list
        """
        if not layer_list:
            layer_list = self._sub_layers
        result_layers = []
        for layer in layer_list:
            if layer.node_exists(node_path):
                result_layers += [layer]
        if attr_name:
            for layer in result_layers[:]:
                _, has = get_opinion(layer.lookup(node_path), attr_name)
                if not has:
                    result_layers.remove(layer)
        return result_layers

    @staticmethod
    def assign_layer_parents(layer_list):
        """Loops the layers in the given layer list and sets their parent_layer
        attribute. Then the file path and layer keys are set in the parent
        layer's sub_layers dict.
        :return: None
        """
        for layer in layer_list:
            # Register the layer's file path and layer object in its parent
            # layer dict and set its parent layer object.
            layer_filepath = layer.filepath
            if layer.parent_layer:
                for parent_layer_dict in layer.parent_layer.sub_layers:
                    if parent_layer_dict[SAVE_KEY.FILEPATH] == layer_filepath:
                        parent_layer_dict['layer'] = layer
                        break

    def set_node_child_order(self, node, child_order, target_layer,
                             comp_layer=None):
        dirty = []
        node_path = target_layer.get_node_path(node)
        if node_path is None:
            logger.error("Failed to set child order on {}".format(node_path),
                         links=[node_path])
            return
        old_child_order = self.get_node_child_order(node)
        setattr(node, INTERNAL_ATTRS.CHILD_ORDER, child_order)
        if comp_layer:
            source_node = comp_layer.lookup(node_path)
            comp_safe_co = child_order[:]
            if old_child_order and not child_order:  # Must re-merge orders
                bases_dict = CompArc.get_bases_arc_dict(source_node, comp_layer)
                for ref in bases_dict.get(CompArc.REFERENCE, []):
                    ref_co = self.get_node_child_order(ref)
                    comp_safe_co = list_merger(comp_safe_co, ref_co)
                inst = bases_dict.get(CompArc.INSTANCE)
                if inst:
                    inst_co = self.get_node_child_order(inst)
                    comp_safe_co = list_merger(comp_safe_co, inst_co)
            setattr(source_node, INTERNAL_ATTRS.CHILD_ORDER, comp_safe_co)
            dirty = self.propagate_child_order(source_node_path=node_path,
                                               old_child_order=old_child_order,
                                               new_child_order=comp_safe_co,
                                               comp_layer=comp_layer)
        return dirty

    def propagate_child_order(self, source_node_path, old_child_order,
                              new_child_order, comp_layer):
        dirites = comp_layer.get_node_dirties(source_node_path)
        old_len = len(old_child_order)
        for dirty in dirites:
            inst_target = comp_layer.lookup(dirty)
            rt = comp_layer.RETURNS.Path
            inst_children = comp_layer.children(dirty, return_type=rt,
                                                ordered=True)
            inst_old = [nxt_path.node_name_from_node_path(p)
                        for p in inst_children]

            old_set = set(old_child_order)
            target_set = set(inst_old)
            updated_child_order = new_child_order[:]
            valid_sets = bool(old_set) and bool(target_set)
            if old_set.issubset(target_set) and valid_sets:
                i = 0  # Faster than enumerate or range(len())
                for _ in inst_old:
                    if inst_old[i:old_len + i] == old_child_order:
                        updated_child_order = inst_old[:]
                        updated_child_order[i:old_len + i] = new_child_order
                        break
                    i += 1
                if updated_child_order is new_child_order:
                    updated_child_order = inst_old
            elif old_set.intersection(target_set):
                updated_child_order = inst_old
            else:
                updated_child_order = inst_old + new_child_order
            setattr(inst_target, INTERNAL_ATTRS.CHILD_ORDER,
                    updated_child_order[:])
        return dirites

    @staticmethod
    def get_node_spec(node_object):
        node = node_object
        if node:
            object_name = node_object.__name__
            while object_name != SpecNode.__name__:
                node = node.__bases__[0]
                object_name = node.__name__
            return node

    @staticmethod
    def get_node_child_order(node):
        """Returns a copy of the node's child order list, thus mutation of the
        return value will not effect the node object.
        :param node: Node object
        :return: Copy of the child order list
        """
        return getattr(node, INTERNAL_ATTRS.CHILD_ORDER)[:]

    def get_reverted_child_order(self, node_path, target_layer, comp_layer):
        """Merges child order lists from lowest to highest layer, effectively
        removing any local edits to the child order of the `node`.
        :param node: Node object
        :return: Non-repeating list of strings representing node names.
        """
        comp_node = comp_layer.lookup(node_path)
        comp_child_order = self.get_node_child_order(comp_node)
        reverted_child_order = []
        for name in comp_child_order:
            child_path = nxt_path.join_node_paths(node_path, name)
            if target_layer.lookup(child_path):
                reverted_child_order += [name]
        rt = target_layer.RETURNS.NameDict
        for child_name, _ in target_layer.children(node_path,
                                                   return_type=rt).items():
            if child_name not in reverted_child_order:
                reverted_child_order += [child_name]
        return reverted_child_order

    @staticmethod
    def get_top_node(node, layer):
        ancestor_nodes = layer.ancestors(node)
        try:
            return ancestor_nodes[0]
        except IndexError:
            return None

    def get_node_inherited_attr_names(self, node, comp_layer):
        if not isinstance(comp_layer, CompLayer):
            logger.error('Wrong layer type supplied, must be comp layer!')
            return []
        attrs = []
        node_path = comp_layer.get_node_path(node)
        s, e = comp_layer._layer_range
        layers = self._sub_layers[s:e]
        local_attrs = get_node_local_attr_names(node_path, layers)
        parent_path = getattr(node, INTERNAL_ATTRS.PARENT_PATH)
        parent = comp_layer.lookup(parent_path)
        if not parent:
            while parent_path != nxt_path.WORLD:
                parent_path = nxt_path.get_parent_path(parent_path)
                parent = comp_layer.lookup(parent_path)
                if parent:
                    break
        if not parent:
            return attrs
        inst_attrs = self.get_node_instanced_attr_names(node, comp_layer)
        invalid_list = self.protected_attrs + inst_attrs + local_attrs
        for attr in dir(parent):
            if attr in attrs:
                continue
            if attr in invalid_list:
                continue
            if attr.endswith(META_ATTRS._suffix):
                continue
            attrs += [attr]
        return attrs

    @staticmethod
    def get_node_comment(node):
        """Returns the comment of the specified node.

        :param node: Node to get comment from.
        :type node: comptree.CompTreeNode

        :return: Comment of node.
        :rtype: str
        """
        try:
            comment = getattr(node, INTERNAL_ATTRS.COMMENT)
        except AttributeError:
            comment = None
        return comment

    @staticmethod
    def set_node_comment(node, comment, layer):
        """Sets the node comment
        :param node: SpecNode
        :param comment: String of node comment. NoneType is allowed
        :param layer: SpecLayer
        :return: None
        """
        node_path = layer.get_node_path(node)
        setattr(node, INTERNAL_ATTRS.COMMENT, comment)
        setattr(node, INTERNAL_ATTRS.COMMENT + META_ATTRS.SOURCE,
                (layer.real_path, node_path))

    @staticmethod
    def node_attr_exists(node, attr_name):
        """Check if node as the given attr.
        :param node: NxtNode
        :param attr_name: string of attr name
        :raises: AttributeError
        :return: bool
        """
        return hasattr(node, str(attr_name))

    def execute(self, start=None, layer=None, parameters=None):
        """Executes stage. Optionally at given start. Start can be a
        start point index, or a node path to start from. If no start is given
        will attempt to start at first start point. If more than one start
        node is present a random one will be chosen.

        :param start: Node path to start from, defaults to None
        :type start: str, optional
        :param layer: Layer to execute
        :type layer: CompLayer
        :param parameters: Optional dict of {'/node.attr': value} to be
        applied before execution begins.
        :type parameters: dict
        :raises IndexError: If start point index is not found.
        :raises ValueError: If given start node path cannot be found or if no
        start is specified and no start nodes can be found.
        :return: a runtime CompLayer object
        :rtype: CompLayer
        """
        if not layer:
            layer = self.build_stage(from_idx=0)

        if type(start) == str:
            if not layer.node_exists(start):
                msg = "Start node path {} not found".format(start)
                raise ValueError(msg)
            start_path = start
        else:
            start_nodes = self.get_layer_start_nodes(layer)
            if not start_nodes:
                raise ValueError("No start specified and no start nodes.")
            start_path = start_nodes[0]
        exec_order = layer.get_exec_order(start_path)
        return self.execute_nodes(exec_order, layer, parameters)

    def execute_nodes(self, node_paths, layer, parameters=None):
        """Execute nodes at given `node_paths` using given `layer`. Returns
        runtime layer object that if passed as layer argument to successive
        calls will "continue" execution with the same cached values.
        If parameters are provided they will be applied before the layer node
        runs, unless the layer provided (in the layer arg) is a runtime layer,
        in which case they will be applied before the first node is run.
        :param node_paths: node paths to execute
        :type node_paths: list
        :param layer: CompLayer to execute
        :type layer: CompLayer
        :param parameters: Optional dict of {'/node.attr': value} to be
        applied before execution begins.
        :type parameters: dict
        :raises ValueError: When layer argument has invalid value;
        GraphError: For any exception raised by a node's compute.
        :return: Runtime CompLayer that can be used for continued execution.
        :rtype: CompLayer
        """
        if not isinstance(layer, CompLayer):
            raise ValueError("Execute Nodes requires a comp layer.")
        if not layer.runtime:
            dup_comp = self.build_stage(layer.layer_idx())
            runtime_layer = self.setup_runtime_layer(dup_comp,
                                                     parameters=parameters)
        else:
            runtime_layer = layer
            if parameters:
                self.set_runtime_parameters(parameters, runtime_layer)
        for path in node_paths:
            curr_node = runtime_layer.lookup(path)
            if get_node_enabled(curr_node) is False:
                continue
            logger.execinfo("Executing: " + path, links=[path])
            runtime_layer.cache_layer.set_node_enter_time(path)
            try:
                run(runtime_layer, stage=self, rt_node=curr_node)
            finally:
                runtime_layer.cache_layer.set_node_exit_time(path)
            t = str(round(runtime_layer.cache_layer.get_node_run_time(path)))
            msg = "Time to execute {}: {} second(s)."
            logger.execinfo(msg.format(path, t), links=[path])
        return runtime_layer

    def execute_custom_code(self, code_string, node_path, layer):
        if not isinstance(layer, CompLayer):
            raise ValueError("Execute custom code requires a comp layer.")
        if not layer.runtime:
            dup_comp = self.build_stage(layer.layer_idx())
            runtime_layer = self.setup_runtime_layer(dup_comp)
        else:
            runtime_layer = layer
        exec_start = time.time()
        rt_node = runtime_layer.lookup(node_path)
        resolved_code = self.resolve(rt_node, code_string, runtime_layer)
        run(runtime_layer, stage=self, rt_node=rt_node,
            custom_code=resolved_code)
        exec_time = str(round((time.time() - exec_start)))
        logger.execinfo("Successfully ran snippet in: "
                        "{} second(s).".format(exec_time))

    @staticmethod
    def get_node_exec_in(node):
        try:
            return getattr(node, INTERNAL_ATTRS.EXECUTE_IN)
        except AttributeError:
            return None

    @staticmethod
    def set_node_exec_in(node, exec_in_path, layer):
        node_path = layer.get_node_path(node)
        setattr(node, INTERNAL_ATTRS.EXECUTE_IN, exec_in_path)
        setattr(node, INTERNAL_ATTRS.EXECUTE_IN + META_ATTRS.SOURCE,
                (layer.real_path, node_path))

    def set_node_enabled(self, node, state):
        """Sets the enabled state of the given node.
        :param node: Node object
        :param state: bool
        :return: bool of previous state
        """
        old_state = get_node_enabled(node)
        if node:
            node_spec = self.get_node_spec(node)
            setattr(node_spec, INTERNAL_ATTRS.ENABLED, state)
            return old_state

    @staticmethod
    def get_layer_start_nodes(layer):
        rt = layer.RETURNS.NodeTable
        return [nt[0] for nt in layer.descendants(return_type=rt)
                if getattr(nt[1], INTERNAL_ATTRS.START_POINT)]

    def set_runtime_parameters(self, parameters, runtime_layer):
        for attr_path, value in parameters.items():
            if not isinstance(attr_path, basestring):
                logger.error('Got an attr path "{}" that is not a string, '
                             'skipping it.'.format(attr_path))
                continue
            node_path = nxt_path.node_path_from_attr_path(attr_path=attr_path)
            node = runtime_layer.lookup(node_path)
            if node is None:
                logger.error('Got an invalid node path "{}"'.format(node_path))
                continue
            attr_name = nxt_path.attr_name_from_attr_path(attr_path)
            _, has_it = get_opinion(node, attr_name)
            if has_it:
                logger.info('Setting {} = {}'.format(attr_path, value),
                            links=[node_path])
            else:
                logger.warning('Creating attr {} = {}'.format(attr_path,
                                                              value),
                               links=[node_path])
            setattr(node, attr_name, str(value))

    def setup_runtime_layer(self, comp_layer=None, parameters=None):
        """Modifies given CompLayer for runtime use. If no comp layer is given
        the runtime layer is generated using all of the stage's sub_layers.
        :param comp_layer: CompLayer
        :param parameters: Optional dict of {'/node.attr': value} to be
        applied before layer node is executed.
        :return: A runtime CompLayer
        :rtype: CompLayer
        """
        if comp_layer is None:
            logger.info('No comp layer provided comping all layers for '
                        'execution')
            comp_layer = self.build_stage(from_idx=0)
        runtime_layer = comp_layer
        runtime_layer.runtime = True
        return_type = runtime_layer.RETURNS.NodeTable
        for path, node in runtime_layer.descendants(return_type=return_type):
            setattr(node, INTERNAL_ATTRS.NODE_PATH, path)
        # Set parameter overloads
        if parameters:
            self.set_runtime_parameters(parameters, runtime_layer)
        layer_node = comp_layer.lookup(nxt_path.WORLD)
        if not layer_node:
            spec_layer = SpecNode.new()
            layer_node = CompNode.new(spec_layer)
            self.add_node_to_comp_layer(nxt_path.WORLD, layer_node, comp_layer,
                                        add_to_child_order=False)

        def execute(paths=(), start=None, parameters=None):
            if (paths and start) or (not paths and not start):
                raise ValueError("Must give either a start point or a list of,"
                                 " node paths to run.")
            if start:
                self.execute(start=start, layer=runtime_layer,
                             parameters=parameters)
            else:
                self.execute_nodes(paths, runtime_layer, parameters=parameters)
        # Setup console for this runtime layer
        console_globals = {'STAGE': layer_node,
                           '__stage__': self,
                           'nxt_path': nxt_path,
                           'w': w,
                           'types': types,
                           'self': layer_node,
                           'execute': execute}
        runtime_layer._console.globals = console_globals
        _code, lines = self.get_node_code(layer_node, runtime_layer)
        runtime_layer._console.node_path = nxt_path.WORLD
        runtime_layer._console.running_lines = lines
        runtime_layer._console.runcode(_code)
        runtime_layer.cache_layer.add_node(nxt_path.WORLD, layer_node)
        return runtime_layer

    def save_to_temp(self, comp_layer, output_dir=None):
        """Saves the spec layers, that make up a comp layer, to an
        output dir. If no output_dir is provided one will be generated using
        tempfile.mkdtemp. The reference list of the sub-layers are converted
        to relative paths so they work with all the layers in the same
        folder. The cwd of each layer is set to the original location of the
        source layer.
        :param comp_layer: CompLayer
        :param output_dir: Path to output directory (defaults to a generated
        temp dir)
        :return: Path to temp top layer file
        """
        start = time.time()
        if not output_dir:
            output_dir = nxt_io.generate_temp_dir()
        s, e = comp_layer._layer_range
        layers = self._sub_layers[s:e]
        temp_path = None
        for layer in reversed(layers):
            save_data = layer.get_save_data()
            cwd = layer.get_cwd()
            save_data[SAVE_KEY.CWD] = cwd
            refs = save_data.get(SAVE_KEY.REFERENCES, [])
            idx = 0
            for ref in refs:
                ref_file_name = os.path.basename(ref)
                if ref_file_name == ref:
                    continue
                comp_overs = save_data.get(SAVE_KEY.COMP_ORVERRIDES, {})
                for path, over in comp_overs.items():
                    if path == ref:
                        comp_overs[ref_file_name] = comp_overs.pop(ref)
                refs[idx] = ref_file_name
                idx += 1
            file_name = os.path.basename(layer.real_path)
            temp_path = os.path.join(output_dir, file_name)
            nxt_io.save_file_data(save_data, temp_path)
        save_time = str(int(round((time.time() - start) * 1000)))
        logger.debug("{} layer(s) saved to temp dir in: {}ms".format((e-s)-1,
                                                                     save_time))
        return temp_path.replace(os.sep, '/')


def run(runtime_layer, stage=None, rt_node=None, custom_code=None):
    rt_path = runtime_layer.get_node_path(rt_node)
    frame_node = type('frame', (), {})
    setattr(frame_node, INTERNAL_ATTRS.NODE_PATH, rt_path)
    if custom_code:
        code = custom_code
    else:
        code = stage.get_node_code_string(node=rt_node,
                                          layer=runtime_layer,
                                          data_state=DATA_STATE.RESOLVED)
    setattr(rt_node, INTERNAL_ATTRS.CACHED_CODE, code)
    setattr(frame_node, INTERNAL_ATTRS.CACHED_CODE, code)
    # pre run cache is used to compare to post-exec attrs of during_run_node
    pre_run_cache = {}
    skip = INTERNAL_ATTRS.PROTECTED + (INTERNAL_ATTRS.CACHED_CODE,)
    console = runtime_layer._console
    graph_globals = console.globals
    for attr in dir(rt_node):
        if attr in skip:
            continue
        if attr.endswith(META_ATTRS._suffix):
            continue
        nxt_type = determine_nxt_type(getattr(rt_node, attr))
        setattr(rt_node, attr + META_ATTRS.SOURCE,
                (runtime_layer.real_path, rt_path))
        real = stage.get_attr_as_real_data_type(rt_node, attr, runtime_layer,
                                                _globals=graph_globals)
        if nxt_type in ['list', 'dict']:
            try:
                pre_run_cache[attr] = copy.deepcopy(real)
                setattr(frame_node, attr, copy.deepcopy(real))
            except RuntimeError:
                pre_run_cache[attr] = None
                setattr(frame_node, attr, real)
        else:
            pre_run_cache[attr] = real
            setattr(frame_node, attr, real)
    # Cache the node before exec so we can see what it tried to run if it fails
    runtime_layer.cache_layer.add_node(rt_path, frame_node)
    # Convert the compute string to a code object for running in console
    _code, lines = stage.get_node_code(rt_node, runtime_layer, custom_code)
    good_keys = graph_globals.keys()
    console.node_path = rt_path
    console.running_lines = lines
    console.globals['self'] = frame_node
    runtime_layer.running = True
    try:
        console.runcode(_code)
    except GraphError:
        if not console.run_as_global:
            clean_globals(lines, good_keys, console.globals)
        runtime_layer.running = False
        raise
    runtime_layer.running = False
    if not console.run_as_global:
        clean_globals(lines, good_keys, console.globals)
    for attr_name, pre_run_val in pre_run_cache.items():
        post_run_val = getattr(frame_node, attr_name)
        if pre_run_val == post_run_val:
            continue
        # Push only changed values back to rt_node, which represents
        # what is inherited by children/instances
        setattr(rt_node, attr_name, post_run_val)
    return console.globals


def clean_globals(code_lines, good_keys, global_dict):
    """Super hack that tries to remove non global keyword var from the globals
    :param code_lines: list of strings
    :param good_keys: list of expected global keys
    :param global_dict: global dict to clean
    :return: None
    """
    code_lines = [l for l in code_lines if not l.startswith(('#', "'", '"'))]
    cur_keys = global_dict.keys()
    sus_keys = [k for k in cur_keys if k not in good_keys]
    safe_keys = [] + good_keys
    for sus_key in sus_keys:
        for line in code_lines:
            if 'global {}'.format(sus_key) in line:
                safe_keys += [sus_key]
                break
    for bad_key in [k for k in cur_keys if k not in safe_keys]:
        global_dict.pop(bad_key)


def determine_nxt_type(value):
    vs = str(value)
    if len(vs) > 1 and (vs.startswith('"') and vs.endswith('"')) or (
            vs.startswith("'") and vs.endswith("'")):
        type_name = 'str'
    elif vs.startswith('${') and vs.endswith(
            '}'):  # In the event this is just an attr ref
        type_name = 'raw'
    elif vs.startswith('[') and vs.endswith(']'):
        type_name = 'list'
    elif vs.startswith('(') and vs.endswith(')'):
        type_name = 'tuple'
    elif vs.startswith('{') and vs.endswith('}'):
        type_name = 'dict'
    elif value is None:
        type_name = 'NoneType'
    else:
        try:
            type_name = type(literal_eval(value)).__name__
        except (ValueError, NameError, SyntaxError):
            type_name = 'raw'
    return type_name


def w(string, quote_type=0):
    """Wraps your string in quotes.
    :param string: Input string to be wrapped
    :type string: str
    :param quote_type: Int 1: ', 2: ", 3: ''', 4: \"\"\"
    :type quote_type: int or str
    Default is 1, any string can also be provided and we will wrap the
    string arg in that string ie w('Hello World', '$') returns '$Hello World$'
    :return: String wrapped in quote marks or custom string
    """
    quote_types = ['\'', '\"', '\'\'\'', '\"\"\"']
    if isinstance(quote_type, int):
        char = quote_types[quote_type]
    else:
        char = quote_type
    char = str(char)
    return char + str(string) + char


def get_historical_opinions(comp_node, attr, comp_layer, include_local=False):
    """Gets all the historical values for the given node and attr. The local
    opinion is not included in the return. The MRO is looped so all depths of
    parents and instances are considered.
    :param comp_node: NxtCompNode
    :param attr: String of attr name
    :param comp_layer: CompLayer
    :param include_local: if True the local opinion will not be stripped from
    the start of the return list.
    :return: [{META_ATTRS.SOURCE: source, META_ATTRS.VALUE: val}]
    """
    historicals = []
    is_proxy = getattr(comp_node, INTERNAL_ATTRS.PROXY)
    for b in comp_node.__mro__:
        if attr in INTERNAL_ATTRS.ALL:
            if b.__name__ not in (CompNode.__name__, SpecNode.__name__):
                continue
            arc = CompArc.get_arc(comp_node, b, comp_layer)
            arc_attrs = CompArc.INHERITANCE_MAP.get(arc, [])
            if attr not in arc_attrs and arc != CompArc.INSTANCE:
                continue
        val, has = get_opinion(b, attr)
        if has:
            source = getattr(b, attr+META_ATTRS.SOURCE)
            historical = {META_ATTRS.SOURCE: source, META_ATTRS.VALUE: val}
            if historical not in historicals:
                historicals += [historical]
    if is_proxy or include_local:
        return historicals
    if len(historicals) == 1:
        return []
    else:
        historicals = historicals[1:]
    return historicals


def composite_lists(list_1, list_2):
    composite_list = []
    base_lists = [list_1, list_2]
    for local_order in base_lists:
        for idx, item in enumerate(local_order):
            if item not in composite_list:
                offset = 1
                if idx in range(len(composite_list)):
                    prev_idx = idx - 1
                    if prev_idx >= 0 and composite_list[prev_idx] == \
                            local_order[prev_idx]:
                        offset = 0
                    composite_list.insert(idx + offset, item)
                else:
                    composite_list.append(item)
    return composite_list


def nxt_uuid(extra=0, f=False):
    """Creates an ALMOST guaranteed unique id int.
    :param f: If True the float value will be returned else int will
    :param extra: An extra int that helps with the uniqueness problem.
    :return: int"""
    if f:
        return float((time.time()) + extra)
    else:
        uid = (time.time() * 10) + extra
        return int(uid)

