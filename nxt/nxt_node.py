# Built-in
from functools import partial
from collections import OrderedDict
import logging
import json
import copy

# Internal
import nxt_path, nxt_io

logger = logging.getLogger(__name__)


class INTERNAL_ATTRS(object):
    """Class uses for easy access to internal attr constants and various
    lists of them used for composition. Only modify if you are sure of the
    ramifications to the comp engine.
    The _prefix constant should be added to every attr name to match our
    convention. When an internal attr is saved the prefix is stripped.
    """
    _prefix = '_'
    CHILD_ORDER = _prefix + 'child_order'
    COMMENT = _prefix + 'comment'
    COMPUTE = _prefix + 'code'
    ENABLED = _prefix + 'enabled'
    EXECUTE_IN = _prefix + 'execute_in'
    INSTANCE_PATH = _prefix + 'instance'
    NODE_PATH = _prefix + 'node_path'
    NAME = _prefix + 'name'
    PARENT_PATH = _prefix + 'parent_path'
    PROXY = _prefix + 'proxy'
    SOURCE_LAYER = _prefix + 'source_layer'
    START_POINT = _prefix + 'start_point'
    CACHED_CODE = _prefix + 'cached_code'
    # List of python attrs that a node will have but we don't want to parse or
    # considering in our composite logic
    BUILTINS = tuple(dir(type('NodeSpec', (object,), {})))
    # A list of node attrs that are used internally in our composite logic but
    # tracked and like user attrs with a `_source__nxt` meta attr
    TRACKED = (COMPUTE, EXECUTE_IN, COMMENT, START_POINT, ENABLED,
               INSTANCE_PATH)
    # Un-tracked internal attrs
    UNTRACKED = (CHILD_ORDER, NAME, SOURCE_LAYER, PROXY, PARENT_PATH,
                 NODE_PATH)
    # Attrs names that must be reserved but are not used in the comp engine
    NO_COMP = (CACHED_CODE,)
    # The full tuple of all internal attr names
    PROTECTED = BUILTINS + TRACKED + UNTRACKED + NO_COMP
    # Tuple for easy looping when saving/loading node data
    ALL = TRACKED + UNTRACKED
    # Defines order of node attrs in the save file
    SAVED = (START_POINT, INSTANCE_PATH, EXECUTE_IN, CHILD_ORDER, ENABLED,
             COMMENT, COMPUTE)
    # TODO: Remove this once full targeted re-comp rolls out
    REQUIRES_RECOMP = tuple([a for a in ALL if a not in (CHILD_ORDER,
                                                         INSTANCE_PATH,
                                                         COMPUTE)])
    ALLOW_NO_OPINION = (ENABLED,)
    # Dict mapping internal attr to a partial object that generates a default
    # for the given attr
    DEFAULTS = {COMPUTE: partial(list, ())}

    @classmethod
    def as_save_key(cls, attr):
        key = attr.partition(INTERNAL_ATTRS._prefix)[-1]
        if attr == cls.NAME:
            key = 'name'
        return key


class META_ATTRS(object):
    _prefix = INTERNAL_ATTRS._prefix
    _suffix = '__nxt'
    COMMENT = _prefix + 'comment' + _suffix
    TYPE = _prefix + 'type' + _suffix
    SOURCE = _prefix + 'source' + _suffix
    VALUE = 'value'
    ALL = (COMMENT, TYPE, SOURCE)

    @classmethod
    def as_save_key(cls, key):
        if key == cls.VALUE:
            return key
        return key.partition(cls._prefix)[-1].partition(cls._suffix)[0]


class Node(object):
    _name = 'node'
    _parent_path = nxt_path.WORLD
    _child_order = []
    _proxy = False
    _enabled = True


def create_spec_node(node_data, layer, parent_path=nxt_path.WORLD,
                     is_proxy=False):
    attrs = {}
    node_name = node_data[INTERNAL_ATTRS.as_save_key(INTERNAL_ATTRS.NAME)]
    path = nxt_path.join_node_paths(parent_path, node_name)
    # Parse for attrs
    user_attrs = node_data.get(nxt_io.SAVE_KEY.ATTRS, {})
    for attr_name, data in user_attrs.items():
        attrs[attr_name] = None
        attrs[attr_name + META_ATTRS.SOURCE] = (layer.real_path, path)
        for sub_attr, value in data.items():
            if sub_attr == META_ATTRS.VALUE:
                attrs[attr_name] = value
                continue
            meta_attr = META_ATTRS._prefix + sub_attr + META_ATTRS._suffix
            if meta_attr not in META_ATTRS.ALL:
                logger.warning('Invalid meta attr "{}"'.format(meta_attr))
                logger.warning('Expected {}'.format(META_ATTRS.ALL))
                continue
            full_attr_name = (attr_name + meta_attr)
            attrs[full_attr_name] = value
    for attr in INTERNAL_ATTRS.ALL:
        key = INTERNAL_ATTRS.as_save_key(attr)
        val = node_data.get(key)
        if (not has_opinion(val) and attr not in
                INTERNAL_ATTRS.ALLOW_NO_OPINION):
            val = INTERNAL_ATTRS.DEFAULTS.get(attr)
            if val is not None:
                val = val()
        attrs[attr] = val
    # Remove duplicates in child order
    child_order = []
    for c in node_data.get('child_order', []):
        if c not in child_order:
            child_order += [c]
    attrs.update({INTERNAL_ATTRS.NAME: node_name,
                  INTERNAL_ATTRS.PROXY: is_proxy,
                  INTERNAL_ATTRS.CHILD_ORDER: child_order,
                  INTERNAL_ATTRS.SOURCE_LAYER: layer.real_path
                  })
    pp_key = INTERNAL_ATTRS.as_save_key(INTERNAL_ATTRS.PARENT_PATH)
    pp_attr = INTERNAL_ATTRS.PARENT_PATH
    if is_proxy:
        attrs[pp_attr] = node_data.get(pp_key) or parent_path
    else:
        attrs[pp_attr] = parent_path

    node_spec = SpecNode.new(attrs=attrs)
    parent_object = layer.lookup(parent_path)
    layer.clear_node_child_cache(path)
    layer.clear_node_child_cache(parent_path)
    if parent_object:
        proxies = (getattr(node_spec, INTERNAL_ATTRS.PROXY) or
                    getattr(parent_object, INTERNAL_ATTRS.PROXY))
        child_order = getattr(parent_object, INTERNAL_ATTRS.CHILD_ORDER)
        if node_name not in child_order and not proxies:
            new_co = list_merger(child_order, [node_name])
            setattr(parent_object, INTERNAL_ATTRS.CHILD_ORDER, new_co)
    for attr in INTERNAL_ATTRS.TRACKED:
        setattr(node_spec, attr + META_ATTRS.SOURCE,
                (layer.real_path, path))
    return node_spec


class SpecNode(object):
    @classmethod
    def new(cls, attrs=None):
        if attrs is None:
            attrs = {}
        return type(cls.__name__, (Node,), attrs)


class CompNode(object):

    @classmethod
    def new(cls, spec_node, attrs=None):
        bases = (spec_node,)
        if attrs is None:
            attrs = {}
        return type(cls.__name__, bases, attrs)


def get_node_attr(node_object, attr, default=None):
    return getattr(node_object, attr, default)


def get_opinion(node, attr):
    """Check if the node attr has an opinion.
    Returns a tuple: (attr_value, bool_has_opinion)
    :param node: NxtNode
    :param attr: String of attr name
    :return: (attr_value, bool_has_opinion)
    """
    attr_value = get_node_attr(node, attr)
    op_exists = has_opinion(attr_value)
    return attr_value, op_exists


def get_node_enabled(node):
    """Get the enabled state of the given node. If the enabled state is not
    set it (None) the default return is True.
    :param node: Node object
    :return: Bool of enabled state
    """
    return getattr(node, INTERNAL_ATTRS.ENABLED, None)


def has_opinion(attr_value):
    return attr_value not in (None, [])


def has_stronger_opinion(comp_node, attr, target_layer):
    """Check if the given attr on the given node has a stronger opinion than
    the opinion on the target layer (if any). We check the source layers of
    each base class. We are looping strong to weak so if there was no
    opinion before hitting the target layer there isn't a stronger opinion.
    :param comp_node: NxtCompNode
    :param attr: String of attr name
    :param target_layer: NxtSpecLayer
    :return: bool (True if comp node has opinion that would overload the
    target layer's opinion)
    """
    result = False
    comp_opinion, _ = get_opinion(comp_node, attr)
    val = None
    for b in comp_node.__bases__:
        source_layer = getattr(b, INTERNAL_ATTRS.SOURCE_LAYER)
        val, has = get_opinion(b, attr)
        if source_layer == target_layer:
            break
        result = has
        if has:
            break
    if comp_opinion == val:
        return False
    return result


def get_node_as_dict(spec_node):
    """Get a spec node as an ordered dictionary. The return data is
    strcutred as it would be in a saved graph file.
    :param spec_node: SpecNode object
    :return: OrderedDict
    """
    user_attrs = OrderedDict()
    spec_dict = OrderedDict()
    # user attrs
    for key in spec_node.__dict__.keys():
        if key in INTERNAL_ATTRS.PROTECTED or key.endswith(META_ATTRS.ALL):
            continue
        # Sub-attrs
        comment = get_node_attr(spec_node, key + META_ATTRS.COMMENT)
        typ = get_node_attr(spec_node, key + META_ATTRS.TYPE)
        value = get_node_attr(spec_node, key)
        sub_attrs = OrderedDict()
        if comment:
            sub_attrs[META_ATTRS.as_save_key(META_ATTRS.COMMENT)] = comment
        if typ:
            sub_attrs[META_ATTRS.as_save_key(META_ATTRS.TYPE)] = typ
        if value:
            try:  # Marshal data
                json.dumps(value)
                val_copy = copy.deepcopy(value)
                sub_attrs[META_ATTRS.as_save_key(META_ATTRS.VALUE)] = val_copy
            except TypeError:  # value is not JSON serializable
                pass
        sorted_sub_attrs = OrderedDict(sorted(sub_attrs.items(),
                                              key=lambda x: x[0]))
        user_attrs[key] = sorted_sub_attrs
    if user_attrs:
        sorted_attrs = OrderedDict(sorted(user_attrs.items(),
                                          key=lambda x: x[0]))
        spec_dict[nxt_io.SAVE_KEY.ATTRS] = sorted_attrs
    # Saving of internall attrs
    for attr in INTERNAL_ATTRS.SAVED:
        value, has_opinion = get_opinion(spec_node, attr)
        if not has_opinion:
            continue
        save_attr_name = INTERNAL_ATTRS.as_save_key(attr)
        spec_dict[save_attr_name] = copy.deepcopy(value)
    return _order_node_dict(spec_dict)


def _order_node_dict(node_dict):
    """Given a node in dictionary format, order the node dictionary based on
    INTERNAL_ATTRS.SAVED order. Any keys in given dictionary not found will
    be at the end.
    :param node_dict: node in dict format
    :type node_dict: dict
    """
    result = OrderedDict()
    user_attrs = node_dict.get(nxt_io.SAVE_KEY.ATTRS)
    remaining_keys = node_dict.keys()
    for internal_attr in INTERNAL_ATTRS.SAVED:
        if internal_attr == INTERNAL_ATTRS.COMPUTE and user_attrs:
            result[nxt_io.SAVE_KEY.ATTRS] = user_attrs
        save_key = INTERNAL_ATTRS.as_save_key(internal_attr)
        if save_key not in node_dict:
            continue
        remaining_keys.remove(save_key)
        result[save_key] = node_dict[save_key]
    for key in remaining_keys:
        result[key] = node_dict[key]
    return result


def get_node_path(node):
    """Only to be used for inferred nodes who do not belong to a layer.
    :param node: Node object
    :return: string of node path
    """
    return nxt_path.join_node_paths(getattr(node, INTERNAL_ATTRS.PARENT_PATH),
                                    getattr(node, INTERNAL_ATTRS.NAME))


def list_merger(base_list, overlay_list):
    """It is important to note we expect both arg lists to be non-repeating.
    Merges lists such that the `base_list` is preserved and
    the `overlay_list` is overlaid onto it.
    Example:
    source = ['Node', 'Node1']
    target = ['Node', 'Jack']
    returns = ['Node', 'Jack', 'Node1']
    :param base_list: Source list of object we want to overlay.
    :param overlay_list: Target list of object we want overlay onto.
    :return: Non-repeating list of object.
    """
    merged_list = base_list[:]
    result_len = len(merged_list)
    if base_list == overlay_list:
        return merged_list
    src_set = set(base_list)
    tgt_set = set(overlay_list)
    tgt_order = overlay_list[:]
    src_order = base_list[:]
    if not tgt_set.intersection(src_set):
        only_source = [n for n in src_order if n not in tgt_order]
    else:
        only_source = []

    if tgt_set.issubset(src_set):
        return merged_list
    idx = 0
    for item in tgt_order:
        if item not in src_order:
            offset = 0
            try:
                _ = src_order[idx]
                valid = True
            except IndexError:
                valid = False
            if valid:
                prev_idx = max(0, idx - 1)
                match = src_order[prev_idx] == tgt_order[prev_idx]
                if prev_idx >= 0 and match:
                    offset = 0
                elif match:
                    offset = prev_idx
                else:
                    next_idx = idx + 1
                    try:
                        match = src_order[next_idx] == tgt_order[next_idx]
                        if match:
                            offset = next_idx
                    except IndexError:
                        pass
                insert = idx + offset
                if insert >= 0 or result_len < 3:
                    merged_list.insert(insert, item)
                else:
                    merged_list.append(item)
            else:
                merged_list.insert(idx, item)
            result_len += 1
        idx += 1
    for item in reversed(only_source):
        merged_list.remove(item)
        merged_list.insert(0, item)
    return merged_list
