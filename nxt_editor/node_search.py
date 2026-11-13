"""Finding nodes by name, the way the filters in mix do.

A search is one or more terms separated by commas, and a node matches if
any of them does. A term matches anywhere in a node's name, ignoring case,
with ``*`` standing for anything. A term with a ``/`` in it matches the
node's whole path instead, to find a node under a particular parent.
Nothing else is special: dots, brackets and the like are matched as they
are typed.

    arm           every node with "arm" in its name
    arm*ctrl      "arm", then anything, then "ctrl"
    arm, leg      either
    rig/*ctrl     a node whose path has "rig/", then anything, then "ctrl"
"""
# Builtin
import re

# Internal
from nxt import nxt_path


def _term_regex(term):
    return '.*'.join(re.escape(part) for part in term.split('*'))


class NodeSearch(object):
    """What was typed in a node search, ready to match node paths."""

    def __init__(self, text):
        terms = [term.strip() for term in (text or '').split(',')]
        terms = [term for term in terms if term.strip('*')]
        name_terms = [_term_regex(t) for t in terms if nxt_path.NODE_SEP
                      not in t]
        path_terms = [_term_regex(t) for t in terms if nxt_path.NODE_SEP in t]
        self.name_regex = (re.compile('|'.join(name_terms), re.IGNORECASE)
                           if name_terms else None)
        self.path_regex = (re.compile('|'.join(path_terms), re.IGNORECASE)
                           if path_terms else None)

    def __bool__(self):
        return bool(self.name_regex or self.path_regex)

    __nonzero__ = __bool__

    def matches(self, node_path):
        """Whether the node at node_path is one searched for.

        :rtype: bool
        """
        if self.name_regex is not None:
            name = nxt_path.node_name_from_node_path(node_path)
            if self.name_regex.search(name):
                return True
        if self.path_regex is not None:
            if self.path_regex.search(node_path):
                return True
        return False

    def filter(self, node_paths):
        """The node paths searched for, in the order given.

        :rtype: list
        """
        return [path for path in node_paths if self.matches(path)]


def search_for(text):
    """A NodeSearch for what was typed, or None when it searches for
    nothing.

    :rtype: NodeSearch or None
    """
    search = NodeSearch(text)
    return search if search else None
