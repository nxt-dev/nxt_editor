"""Common nxt pathing operations. Both for files and nodes.
"""
# Built-in
import os
import re
import sys
import logging

logger = logging.getLogger(__name__)


def full_file_expand(path, start=None):
    """A combination of commonly used os.path functions called to completely
    expand given `path`. If `start` is given, os.cwd is temporarily changed
    in order to influence the start of relative path expansion.
    Return value will always use forward slashes as seperator.

    :param path: path to expand
    :type path: str
    :param start: base directory to expand from, defaults to os cwd
    :type start: str, optional
    :return: given path expanded. Relative paths, environment
    variables, and user character "~" are expanded.
    :rtype: [type]
    """
    orig_cwd = os.getcwd()
    if start:
        os.chdir(start)

    full_path = unify_env_vars(path)
    full_path = os.path.expandvars(full_path)
    full_path = os.path.expanduser(full_path)
    full_path = os.path.realpath(full_path)
    os.chdir(orig_cwd)
    full_path = full_path.replace(os.path.sep, '/')  # Thanks windows.
    return full_path


# Regex patterns for finding all env vars.
# NOTE match uses platform specific identifier, returns name only in group1.
PLATFORM_VAR_PATTERN_MAP = {
    'linux': re.compile(r"\$([a-zA-Z_]*)"),
    'win32': re.compile(r"%([a-zA-Z_]*)%")
}
PLATFORM_VAR_PATTERN_MAP['linux2'] = PLATFORM_VAR_PATTERN_MAP['linux']
PLATFORM_VAR_PATTERN_MAP['darwin'] = PLATFORM_VAR_PATTERN_MAP['linux']

# Strings ready to format with env var name. Result is ready for os expansion.
PLATFORM_VAR_FORMAT_MAP = {
    'linux': "${}",
    'win32': "%{}%"
}
PLATFORM_VAR_FORMAT_MAP['linux2'] = PLATFORM_VAR_FORMAT_MAP['linux']
PLATFORM_VAR_FORMAT_MAP['darwin'] = PLATFORM_VAR_FORMAT_MAP['linux']

# Strings ready to format with env var name into regex pattern for var.
PLATFORM_FIND_VAR_FORMAT_MAP = {
    'linux': r"\${}(?![a-zA-Z_])",
    'win32': r"%{}%"
}
PLATFORM_FIND_VAR_FORMAT_MAP['linux2'] = PLATFORM_FIND_VAR_FORMAT_MAP['linux']
PLATFORM_FIND_VAR_FORMAT_MAP['darwin'] = PLATFORM_FIND_VAR_FORMAT_MAP['linux']


def unify_env_vars(path, target_platform=sys.platform):
    """Replace foreign platform environment variables with platform native ones
    Environment variable patterns must be defined in PLATFORM_VAR_PATTERN_MAP
    and PLATFORM_VAR_PATTERN_MAP to be able to find and replace.

    In short, if you're on windows, convert linux style environment vars to
    windows style. If you're on linux, the reverse.

    Supports mixed type environment variables.

    :param path: string to replace variables in
    :type value: str
    :param target_platform: platform to unify as, defaults to sys.platform
    :type target_platform: str, optional
    :return: given path as unified as possible
    :rtype: str
    """
    target_search_pattern = PLATFORM_VAR_PATTERN_MAP[target_platform]
    replaced_patterns = []  # patterns we've alreay replaced.
    # replace platform vars from other platforms with vars from target platform
    result = path
    for platform, pattern in PLATFORM_VAR_PATTERN_MAP.items():
        # Do not replace vars from our target platform
        if pattern == target_search_pattern:
            continue
        # Do not replace a pattern more than once.
        if pattern in replaced_patterns:
            continue
        replaced_patterns += [pattern]
        found_vars = re.findall(pattern, path)
        for var in found_vars:
            bad_var = PLATFORM_VAR_FORMAT_MAP[platform].format(var)
            new_var = PLATFORM_VAR_FORMAT_MAP[target_platform].format(var)
            result = result.replace(bad_var, new_var)
    return result


# NODE SECTION
NODE_SEP = '/'
ATTR_SEP = '.'
WORLD = NODE_SEP


def expand_relative_node_path(rel_path, start_node_path):
    """Expands given node `rel_path` using `start_node_path` as root of
    relative path. This function does not validate the path, it is only a
    string machine.
    :param rel_path: relative path to expand.
    :type rel_path: str
    :param start_node_path: node to treat as root of relative path.
    :type start_node_path: str
    :return: expanded node path
    :rtype: str
    """
    if not rel_path:
        return None
    if rel_path == WORLD:
        return rel_path
    current_path = start_node_path
    if rel_path.startswith(NODE_SEP):
        current_path = ''
    split_path = rel_path.split(NODE_SEP)
    for directive in split_path:
        if directive == '..':
            current_path, _, _ = current_path.rpartition(NODE_SEP)
            continue
        if directive == '.':
            continue
        if directive == '':
            continue
        # If we get this far, it must be the name of something.
        current_path += NODE_SEP
        current_path += directive
    return current_path


def path_attr_partition(str_path):
    """Returns a tuple of the node path and attribute name from the given path.

    >>> nxt_path.node_path_partition('somewhere/else.attr')
    ('somewhere/else', 'attr')
    >>> nxt_path.node_path_partition('...attr')
    ('..', 'attr')
    >>> nxt_path.node_path_partition('..attr')
    ('.', 'attr')
    :param str_path: node or attribute path
    :type str_path: str
    :return: tuple of node path and attr name ('node/path', 'attr_name')
    :rtype: tuple
    """
    if not is_attr_path(str_path):
        # This is a node path.
        return str_path, None
    if str_path[-1] is ATTR_SEP:
        # This is a node path.
        return str_path, None
    node_path, _, attr_name = str_path.rpartition(ATTR_SEP)
    return node_path, attr_name


def str_path_to_node_namespace(str_path):
    """Given an absolute node or attr `str_path`, split it into the
    list-"namespace" format used by stage.
    NOTE that if given an attribute path, that attribute name will not be
    present in the returned path.
    """
    node_path, _ = path_attr_partition(str_path)
    if node_path.startswith(NODE_SEP):
        return node_path.split(NODE_SEP)[1:]
    return node_path.split(NODE_SEP)


def node_namespace_to_str_path(namespace):
    """Given a node namespace, return it rejoined into a full string path.
    """
    return NODE_SEP + NODE_SEP.join(namespace)


def node_path_from_attr_path(attr_path):
    node_path, _ = path_attr_partition(attr_path)
    return node_path


def attr_name_from_attr_path(attr_path):
    _, attr_name = path_attr_partition(attr_path)
    return attr_name


def node_name_from_node_path(node_path):
    if node_path == WORLD:
        return WORLD
    _, _, node_name = node_path.rpartition(NODE_SEP)
    return node_name


def get_parent_path(node_path):
    """Returns the parent path implied by given `node_path`
    """
    if node_path == WORLD:
        return ''
    parent_path, _, _ = node_path.rpartition(NODE_SEP)
    if not parent_path:
        parent_path = NODE_SEP
    return parent_path


def get_root_path(node_path):
    """Returns the implied "root" node of the given path.
    A root is a node with no parent.
    """
    root_name, _, _ = node_path[1:].partition(NODE_SEP)
    return NODE_SEP + root_name


def is_attr_path(path):
    """Whether the given `path` appears to be a path to an attribute.
    """
    return ATTR_SEP in path


def make_attr_path(node_path, attr_name):
    return node_path + ATTR_SEP + attr_name


def join_node_paths(node_path1, node_path2):
    if not isinstance(node_path2, (tuple, list)):
        node_path2 = (node_path2,)
    extras = (node_path1,) + node_path2
    joined = NODE_SEP.join(extras).replace(NODE_SEP+NODE_SEP, NODE_SEP)
    return joined


def replace_ancestor(path, old_ancestor, new_ancestor):
    path = _add_path_terminator(path)
    old_ancestor = _add_path_terminator(old_ancestor)
    new_ancestor = _add_path_terminator(new_ancestor)
    new_path = new_ancestor + path
    old_ancestor_is_world = old_ancestor == WORLD
    if not old_ancestor_is_world:
        new_path = path.replace(old_ancestor, new_ancestor, 1)
    new_path = new_path[:-1]
    return new_path.replace(NODE_SEP+NODE_SEP, NODE_SEP)


def is_ancestor(path_to_check, ancestor_path):
    """Returns if given ancestor_path is an ancestor path to path_to_check

    :param path_to_check: potential descendant path
    :type path_to_check: str
    :param ancestor_path: potential ancestor path
    :type ancestor_path: str
    :return: Whether ancestor_path is ancestor of path_to_check
    :rtype: bool
    """
    if path_to_check == ancestor_path:
        return False
    elif ancestor_path == WORLD:
        return True
    head, sep, tail = path_to_check.partition(ancestor_path)
    return not head and tail[0] == NODE_SEP


def all_ancestor_paths(path):
    """Returns the ancestor paths implied by given path

    :param path: node path
    :type path: str
    :return: list of implied ancestor paths
    :rtype: list
    """
    ancestors = []
    if path == WORLD:
        return ancestors
    parent_path = get_parent_path(path)
    while parent_path is not WORLD:
        ancestors += [parent_path]
        parent_path = get_parent_path(parent_path)
    return ancestors


def _add_path_terminator(path):
    path += NODE_SEP
    return path


def get_path_depth(path):
    """Get depth of given path. Depth is number of nodes deep from world.
    World is depth 0.

    :param path: path to check depth of.
    :type path: str
    :return: depth of given path.
    :rtype: int
    """
    if path == WORLD:
        return 0
    return path.count(NODE_SEP)


def trim_to_depth(path, trim_depth):
    """Trim a path to given depth. Removes nodes from the end of the path to
    trim to an ancestor path of given path. If trim depth is 0, world path
    is returned. If trim depth is greater than or equal to the depth of given
    path, path is returned unchanged.

    :param path: path to trim
    :type path: str
    :param trim_depth: depth to trim to
    :type trim_depth: int
    :return: path, trimmed to trim depth if possible
    :rtype: str
    """
    if trim_depth == 0:
        return WORLD
    given_path_depth = get_path_depth(path)
    if given_path_depth <= trim_depth:
        return path
    remove_count = given_path_depth - trim_depth
    return path.rsplit(NODE_SEP, remove_count)[0]
