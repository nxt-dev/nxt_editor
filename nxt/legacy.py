# Builtin
import os
from collections import OrderedDict
import json
import logging
import shutil
import pickle

# Internal
import clean_json
from constants import GRAPH_VERSION

#
#  By design you must not import code from nxt, the code here must be a
#  historical record of the code. This file is very not "dry", it is a
#  script with basically zero dependencies.
#
logger = logging.getLogger(__name__)

PRE_RELEASE = (0, 45)


class FileConverter(object):
    def __init__(self, file_data):
        """Determines the version number of the given file. And steps
        through our legacy converters until the version number matches the
        current NXT version. We ignore the major version number and the bug
        fix number.
        :param file_data: Dict of file data from NxtIo
        """
        self.file_data = file_data
        self.version = self.determine_version()
        nxt_version = int(GRAPH_VERSION.VERSION_TUPLE[1])
        if self.version == PRE_RELEASE:
            self.file_data = FILE_VERSIONS[PRE_RELEASE].get_converted(self.file_data)
            self.version = self.determine_version()
        v = self.version
        while True:
            if FILE_VERSIONS.get(v):
                converter = FILE_VERSIONS[v]
                self.file_data = converter.get_converted(self.file_data)
            if v == nxt_version:
                break
            # Step version number by 1
            v += 1

    def determine_version(self):
        """Strips off the bug fix number then returns the major version
        number and the feature number.
        :return: Version number #.##
        """
        file_version = self.file_data.get('version', '0.45.0')
        major_version, minor_version = [int(n) for n in
                                        file_version.split('.')[0:2]]
        if major_version == 0 and minor_version >= 39:
            # v0.39.0 was the last converter for pre-release v0.xx
            return PRE_RELEASE
        elif major_version == 0 and minor_version < 39:
            raise IOError('File version v{} is too old  for conversion. '
                          'Please open in nxt v0.45 and save again in order '
                          'to open it in '
                          '{}'.format(file_version,
                                      GRAPH_VERSION.VERSION_STR))
        return minor_version

    @classmethod
    def get_converted_data(cls, file_data):
        """Sets up converter object and returns the converted data. Note the
        input data and output data may be the same if no conversion is
        deemed necessary.
        :param file_data: Dict of file data from NxtIo
        :return: Updated file data dict
        """
        save_converter = cls(OrderedDict(file_data))
        return save_converter.file_data


class LegacyFileConverter(object):
    def __init__(self, file_data, from_version, to_version):
        """Base class used by all converters
        :param file_data: Dict of file data from NxtIo
        :param from_version: String of input version, used for debugging
        :param to_version: String of output version, used for debugging."""
        self.file_data = file_data
        self.converted = False
        self.from_version = from_version
        self.to_version = to_version

    def convert(self):
        """Meant to be overloaded with conversion logic."""
        logger.info("Converting graph {} --> {}".format(self.from_version,
                                                        self.to_version))

    @classmethod
    def get_converted(cls, file_data):
        """Kicks off the conversion of the data and returns the converted data.
        :param file_data: Dict of file data from NxtIo
        :return: Updated file data dict
        """
        converter = cls(file_data)
        converter.convert()
        return converter.file_data


class V1(LegacyFileConverter):
    def __init__(self, file_data):
        """Converts from v0.38.x to 'v1.0.0'
        :param file_data: Dict of save data.
        """
        super(V1, self).__init__(file_data, 'v0.45.x', 'v1.0.0')

    def convert(self):
        super(V1, self).convert()
        keys = self.file_data.keys()
        if 'children' in keys:
            children = self.file_data.pop('children')
        else:
            children = []
        for node_data in children:
            parent_path = '/'
            self.unpack_node_data(node_data, parent_path)
        self.file_data['version'] = '1.0.0'
        if 'data' in keys:
            self.file_data['meta_data'] = self.file_data.pop('data')
        self.arrange_node_data()
        self.drop_nodes()
        self.deep_order_data(self.file_data)

    def unpack_node_data(self, node_data, parent_path):
        flat_data = OrderedDict()
        widget = node_data['data'].get('widget_type')
        if self.has_opinion(widget):
            flat_data['widget_type'] = widget
        exec_in = node_data.get('execute_in')
        if self.has_opinion(exec_in):
            flat_data['execute_in'] = exec_in
        inst = node_data['data'].get('instance')
        if self.has_opinion(inst):
            flat_data['instance'] = inst
        enabled = node_data['data'].get('enabled')
        if enabled is not None:
            flat_data['enabled'] = enabled
        comp = node_data['data'].get('compute')
        if self.has_opinion(comp):
            flat_data['code'] = comp
        comm = node_data.get('comment')
        if self.has_opinion(comm):
            flat_data['comment'] = comm
        attrs = node_data['data'].get('attributes')
        if self.has_opinion(attrs):
            flat_data['attrs'] = attrs
        child_order = node_data.get('execute_order')
        if self.has_opinion(child_order):
            flat_data['child_order'] = child_order
        path = parent_path + node_data['name']
        if path in self.file_data['data'].get('start_nodes', []):
            flat_data['start_point'] = True
        # Make sure we have a node's dict
        self.file_data.setdefault('nodes', OrderedDict())
        self.file_data['nodes'][path] = flat_data
        for child_data in node_data.get("children", []):
            self.unpack_node_data(child_data, path+'/')

    def arrange_node_data(self):
        try:
            unsorted_paths = self.file_data['nodes'].keys()
        except KeyError:
            return
        paths_by_depth = {}
        max_depth = 0
        for path in unsorted_paths:
            depth = path.count('/')
            paths_by_depth.setdefault(depth, [])
            paths_by_depth[depth].append(path)
            if depth > max_depth:
                max_depth = depth
        for depth in paths_by_depth.keys():
            paths_by_depth[depth].sort()

        sorted_paths = []

        def handle_path_at_depth(cur_path, cur_depth):
            for d in xrange(cur_depth + 1, max_depth + 1):
                for lower_path in paths_by_depth.get(d, []):
                    if self.is_ancestor(lower_path, cur_path):
                        if lower_path not in sorted_paths:
                            sorted_paths.append(lower_path)
                            handle_path_at_depth(lower_path, d)

        for depth in xrange(1, max_depth + 1):
            for path in paths_by_depth.get(depth, []):
                if path not in sorted_paths:
                    sorted_paths.append(path)
                    handle_path_at_depth(path, depth)

        # sorted_paths = sorted(unsorted_paths)
        new_nodes = OrderedDict()
        for path in sorted_paths:
            new_nodes[path] = self.file_data['nodes'][path]
        self.file_data['nodes'] = new_nodes

    def deep_order_data(self, node_dict):
        """Recursively orders the ordered dicts"""
        # order keys
        keys_order = ['version', 'alias', 'name', 'comment', 'color', 'mute',
                      'solo', 'references', 'path', 'instance',
                      'enabled', 'widget_type', 'meta_data', 'execute_in',
                      'execute_order', 'nodes', 'attributes', 'code',
                      'real_path']
        for key in keys_order:
            if key in node_dict.keys():
                node_dict[key] = node_dict.pop(key)
        # iterate over deeper values
        for value in node_dict.values():
            if isinstance(value, dict):
                self.deep_order_data(value)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        self.deep_order_data(item)

    def drop_nodes(self):
        remove = []
        for path, node in self.file_data.get('nodes', {}).items():
            name = self.get_name_from_path(path)
            parent_path = self.get_parent_path(path)
            parent = self.file_data['nodes'].get(parent_path)
            if parent and name not in parent.get('child_order', []):
                remove += [path]
        for path in remove:
            logger.info('Dropping: ' + path)
            self.file_data['nodes'].pop(path)

    @staticmethod
    def has_opinion(attr_value):
        return attr_value not in (None, [], {})

    def is_ancestor(self, path, ancestor_path):
        path = self._add_path_terminator(path)
        ancestor_path = self._add_path_terminator(ancestor_path)
        return path.startswith(ancestor_path)

    @staticmethod
    def _add_path_terminator(path):
        if not path.endswith('/'):
            path += '/'
        return path

    @staticmethod
    def get_parent_path(path):
        parent_path = '/'.join(path.split('/')[:-1])
        return parent_path

    @staticmethod
    def get_name_from_path(path):
        name = path.split('/')[-1]
        return name


class V109(LegacyFileConverter):
    def __init__(self, file_data):
        """Converts from v1.x.x to 'v1.10.0'
        :param file_data: Dict of save data.
        """
        super(V109, self).__init__(file_data, 'v0.9.x', 'v1.10.0')

    def convert(self):
        super(V109, self).convert()
        self.update_refs()
        self.update_meta_data()
        self.arrange_node_data()
        self.deep_order_data(self.file_data)

    def update_refs(self):
        ref_dicts = self.file_data.get('references')
        if not ref_dicts:
            return
        refs = []
        self.file_data.pop('references')
        meta_data = self.file_data.get('meta_data', {})
        comp_overrides = self.file_data.get('comp_overrides', {})
        aliases = meta_data.get('aliases', {})
        colors = meta_data.get('colors', {})
        for ref in ref_dicts:
            path = ref.get('path')
            if not path:
                continue
            r_dat = comp_overrides.get(path, {})
            mute = ref.get('mute', None)
            solo = ref.get('solo', None)
            alias = ref.get('alias', None)
            color = ref.get('color', None)
            if mute is not None:
                r_dat['mute'] = mute
            if solo is not None:
                r_dat['solo'] = solo
            if alias is not None:
                aliases[path] = alias
            if color is not None:
                colors[path] = color
            refs.append(path)
            if r_dat:
                comp_overrides[path] = r_dat
        if refs:
            self.file_data['references'] = refs
        else:
            return
        if comp_overrides:
            self.file_data['comp_overrides'] = comp_overrides
        if aliases:
            meta_data['aliases'] = aliases
        if colors:
            meta_data['colors'] = colors
        if meta_data:
            self.file_data['meta_data'] = meta_data

    def update_meta_data(self):
        meta_data = self.file_data.get('meta_data')
        if not meta_data:
            return
        if meta_data.get('position_data'):
            positions = meta_data.pop('position_data')
            meta_data['positions'] = positions
        if meta_data.get('collapse_data'):
            collapse = meta_data.pop('collapse_data')
            meta_data['collapse'] = collapse

    def arrange_node_data(self):
        try:
            unsorted_paths = self.file_data['nodes'].keys()
        except KeyError:
            return
        paths_by_depth = {}
        max_depth = 0
        for path in unsorted_paths:
            depth = path.count('/')
            paths_by_depth.setdefault(depth, [])
            paths_by_depth[depth].append(path)
            if depth > max_depth:
                max_depth = depth
        for depth in paths_by_depth.keys():
            paths_by_depth[depth].sort()

        sorted_paths = []

        def handle_path_at_depth(cur_path, cur_depth):
            for d in xrange(cur_depth + 1, max_depth + 1):
                for lower_path in paths_by_depth.get(d, []):
                    if self.is_ancestor(lower_path, cur_path):
                        if lower_path not in sorted_paths:
                            sorted_paths.append(lower_path)
                            handle_path_at_depth(lower_path, d)

        for depth in xrange(1, max_depth + 1):
            for path in paths_by_depth.get(depth, []):
                if path not in sorted_paths:
                    sorted_paths.append(path)
                    handle_path_at_depth(path, depth)

        # sorted_paths = sorted(unsorted_paths)
        new_nodes = OrderedDict()
        for path in sorted_paths:
            new_nodes[path] = self.file_data['nodes'][path]
        self.file_data['nodes'] = new_nodes

    def deep_order_data(self, node_dict):
        """Recursively orders the ordered dicts"""
        # order keys
        keys_order = ['version', 'alias', 'name', 'comment', 'color', 'mute',
                      'solo', 'references', 'comp_overrides', 'path',
                      'instance', 'enabled', 'widget_type', 'meta_data',
                      'aliases', 'colors', 'collapse', 'positions',
                      'execute_in', 'execute_order', 'nodes', 'attributes',
                      'code', 'real_path']
        for key in keys_order:
            if key in node_dict.keys():
                node_dict[key] = node_dict.pop(key)
        # iterate over deeper values
        for value in node_dict.values():
            if isinstance(value, dict):
                self.deep_order_data(value)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        self.deep_order_data(item)

    def is_ancestor(self, path, ancestor_path):
        path = self._add_path_terminator(path)
        ancestor_path = self._add_path_terminator(ancestor_path)
        return path.startswith(ancestor_path)

    @staticmethod
    def _add_path_terminator(path):
        if not path.endswith('/'):
            path += '/'
        return path


class V114(LegacyFileConverter):
    def __init__(self, file_data):
        """Converts from v1.x.x to 'v1.15.0'
        :param file_data: Dict of save data.
        """
        super(V114, self).__init__(file_data, 'v0.14.x', 'v1.15.0')

    def convert(self):
        super(V114, self).convert()
        self.file_data['version'] = '1.15'
        if self.file_data.get('mute') is False:
            self.file_data.pop('mute')
        if self.file_data.get('solo') is False:
            self.file_data.pop('solo')
        if self.file_data.get('references') is []:
            self.file_data.pop('references')
        self.arrange_node_data()
        self.deep_order_data(self.file_data)

    def arrange_node_data(self):
        try:
            unsorted_paths = self.file_data['nodes'].keys()
        except KeyError:
            return
        paths_by_depth = {}
        max_depth = 0
        for path in unsorted_paths:
            depth = path.count('/')
            paths_by_depth.setdefault(depth, [])
            paths_by_depth[depth].append(path)
            if depth > max_depth:
                max_depth = depth
        for depth in paths_by_depth.keys():
            paths_by_depth[depth].sort()

        sorted_paths = []

        def handle_path_at_depth(cur_path, cur_depth):
            for d in xrange(cur_depth + 1, max_depth + 1):
                for lower_path in paths_by_depth.get(d, []):
                    if self.is_ancestor(lower_path, cur_path):
                        if lower_path not in sorted_paths:
                            sorted_paths.append(lower_path)
                            handle_path_at_depth(lower_path, d)

        for depth in xrange(1, max_depth + 1):
            for path in paths_by_depth.get(depth, []):
                if path not in sorted_paths:
                    sorted_paths.append(path)
                    handle_path_at_depth(path, depth)

        # sorted_paths = sorted(unsorted_paths)
        new_nodes = OrderedDict()
        for path in sorted_paths:
            new_nodes[path] = self.file_data['nodes'][path]
        self.file_data['nodes'] = new_nodes

    def deep_order_data(self, node_dict):
        """Recursively orders the ordered dicts"""
        # order keys
        keys_order = ['version', 'alias', 'name', 'comment', 'color', 'mute',
                      'solo', 'references', 'comp_overrides', 'path',
                      'instance', 'enabled', 'widget_type', 'meta_data',
                      'aliases', 'colors', 'collapse', 'positions',
                      'execute_in', 'execute_order', 'nodes', 'attributes',
                      'code', 'real_path']
        for key in keys_order:
            if key in node_dict.keys():
                node_dict[key] = node_dict.pop(key)
        # iterate over deeper values
        for value in node_dict.values():
            if isinstance(value, dict):
                self.deep_order_data(value)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        self.deep_order_data(item)

    def is_ancestor(self, path, ancestor_path):
        path = self._add_path_terminator(path)
        ancestor_path = self._add_path_terminator(ancestor_path)
        return path.startswith(ancestor_path)

    @staticmethod
    def _add_path_terminator(path):
        if not path.endswith('/'):
            path += '/'
        return path


class V115(LegacyFileConverter):
    def __init__(self, file_data):
        """Converts from 1.15 to 1.16
        :param file_data: Dict of save data.
        """
        super(V115, self).__init__(file_data, '0.15', '1.16')

    def convert(self):
        super(V115, self).convert()
        self.file_data['version'] = '1.16'
        self.file_data = self.order_save_data(self.file_data)

    def order_save_data(self, file_dict):
        keys_order = ('version', 'alias', 'color', 'mute', 'solo',
                      'references', 'comp_overrides', 'meta_data', 'nodes',
                      'real_path')
        result = OrderedDict()
        data_keys = file_dict.keys()
        for key in keys_order:
            if key not in data_keys:
                continue
            data_keys.remove(key)
            if key == 'nodes':
                result['nodes'] = self.order_nodes_dict(file_dict['nodes'])
            elif key == 'meta_data':
                meta_data = file_dict['meta_data']
                result['meta_data'] = self.order_meta_data(meta_data)
            elif key == 'comp_overrides':
                overs = file_dict['comp_overrides']
                ordered_overs = OrderedDict(sorted(overs.items(),
                                                   key=lambda x: x[0]))
                result['comp_overrides'] = ordered_overs
            else:
                result[key] = file_dict[key]
        # leftovers
        for key in data_keys:
            result[key] = file_dict[key]
        return result

    def order_nodes_dict(self, nodes_dict):
        unsorted = nodes_dict.keys()
        out_nodes = OrderedDict()
        sorted_paths = sorted(unsorted)
        for path in sorted_paths:
            out_nodes[path] = self.order_node_data(nodes_dict[path])
        return out_nodes

    def order_node_data(self, node_data):
        out_node = OrderedDict()
        keys_order = ('start_point', 'instance', 'execute_in', 'child_order',
                      'enabled', 'comment', 'attrs', 'code')
        for key in keys_order:
            if key not in node_data:
                continue
            if key == 'attrs':
                old_attrs = node_data['attrs']
                attrs_order = sorted(old_attrs.keys())
                result_attrs = OrderedDict()
                for attr_name in attrs_order:
                    old_sub_attrs = old_attrs[attr_name]
                    sub_attrs = OrderedDict(sorted(old_sub_attrs.items(),
                                                   key=lambda x: x[0]))
                    result_attrs[attr_name] = sub_attrs
                out_node['attrs'] = result_attrs
            else:
                out_node[key] = node_data[key]
        return out_node

    def order_meta_data(self, meta_data):
        keys_order = ('aliases', 'colors', 'positions', 'collapse')
        result = OrderedDict()
        data_keys = meta_data.keys()
        for key in keys_order:
            if key not in data_keys:
                continue
            data_keys.remove(key)
            result[key] = OrderedDict(sorted(meta_data[key].items(),
                                             key=lambda x: x[0]))
        # leftovers
        for key in data_keys:
            result[key] = meta_data[key]
        return result


FILE_VERSIONS = {
    PRE_RELEASE: V1,
    9: V109,
    14: V114,
    15: V115
}


def cli_file_convert(file_path, replace=False):
    """Simple logic for converting files from the CLI"""
    file_path = os.path.realpath(os.path.expanduser(file_path))
    logger.info("Trying to convert: " + file_path)
    with open(file_path, 'r') as f:
        json_data = json.load(f, object_hook=clean_json._byteify)
        old_file_data = clean_json.load(json_data)
    file_data = FileConverter.get_converted_data(old_file_data)
    out_file_name = os.path.basename(file_path)
    out_file_name, _, ext = out_file_name.rpartition('.')
    if replace:
        ending = "."
    else:
        ending = "_CONVERTED."
    out_file_name = out_file_name + ending + ext
    out_file_dir = os.path.dirname(file_path)
    out_file_path = os.path.join(out_file_dir, out_file_name)
    with open(out_file_path, 'w') as out_file:
        json.dump(file_data, out_file, indent=4, sort_keys=False)
        logger.info('Successfully saved "' + out_file_path + '"')
