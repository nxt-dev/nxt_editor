"""
Helpers to access/write information stored in USER_DIR

NOTE importing this module has side effects. An attempt will be
made to create the user dir if necessary, and an `assert`
will be made that the user directory is a directory.
"""
# Built-in
import os

import json
import logging
import sys

if sys.version_info[0] == 2:
    import cPickle as pickle
else:
    import pickle

# Internal
from nxt.constants import USER_DIR
from nxt_editor.constants import PREF_DIR
import nxt_editor

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

# Constants
USER_PREFS_PATH = os.path.join(PREF_DIR, 'prefs.json')
EDITOR_CACHE_PATH = os.path.join(PREF_DIR, 'editor_cache')
BREAKPOINT_FILE = os.path.join(PREF_DIR, 'breakpoints')
SKIPPOINT_FILE = os.path.join(PREF_DIR, 'skippoints')
HOTKEYS_PREF = os.path.join(PREF_DIR, 'hotkeys.json')
MAX_RECENT_FILES = 10

broken_files = {}


# Make sure the user dir is setup
def ensure_pref_dir_exists():
    """
    Attempt to make the user dir if it doesn't exist.
    Assert user dir's existence after making.
    """
    if not os.path.isdir(PREF_DIR):
        os.makedirs(PREF_DIR)
    if not os.path.isdir(PREF_DIR):
        raise Exception('Failed to generate user dir {}' + USER_DIR)


ensure_pref_dir_exists()


class USER_PREF():
    """ A namespace for preference key constants
    """
    # Fixme: Move these to EDITOR_CACHE
    LAST_OPEN = 'last_open'
    RECENT_FILES = 'recent_files'
    LOG_FILTERS = 'log_filters'
    ATTR_SORTING = 'attribute_sorting'
    EXEC_FRAMING = 'execution_framing'
    SKIP_INITIAL_BREAK = 'skip_initial_breakpoint'
    HISTORICAL_LABEL_FORMAT = 'historical_label_format'
    NODE_TOOLTIPS = 'node_tooltips'
    GRID_SNAP = 'snap_to_grid'
    RECOMP_PREF = 'recomp_wt_exec'
    ZOOM_MULT = 'zoom_mult'
    LAYER_TABLE = 'layer_table'
    TREE_INDENT = 'layer_tree_indent'
    FIND_REP_NODE_PATTERNS = 'find_replace_nodes_patterns'
    FIND_REP_ATTRS = 'find_replace_attrs'
    FPS = 'fps'
    LOD = 'lod'
    ANIMATION = 'animation'
    SHOW_DBL_CLICK_MSG = 'show_double_click_message'
    SHOW_CE_DATA_STATE = 'show_code_editor_data_state'
    DING = 'ding'
    SHOW_GRID = 'show_grid'


class EDITOR_CACHE():
    """A namespace for keys of editor cached data
    """
    WINODW_STATE = 'main_window_state'
    MAIN_WIN_GEO = 'main_window_geo'
    LAST_CLOSED = 'last_closed'
    NODE_PROPERTY_STATE = 'node_property_state'


class PrefFile(dict):
    def __init__(self, path, handlers=None):
        """
        Prefs uses the dictionary api to facilitate writing to the
        preference file at 'path'. File itself does not need to exist
        however directory must. Base PrefFile class is incomplete and
        must be subclassed with `write` and `read` implemented.
        A :class:`PrefHandler` allows for a specific preference to be
        handled completely differently than others. Handlers for
        specific preference keys can be installed into a prefs object
        using `self.set_handler(pref_key, handler)`.
        """
        self.path = path
        self.handlers = handlers if handlers else {}
        if os.path.isfile(self.path):
            self.read()
        else:
            self.write()
        super(PrefFile, self).__init__()

    def set_handler(self, pref_key, handler):
        """
        Assign the 'handler' to use for 'pref_key'.
        """
        self.handlers[pref_key] = handler

    def remove_handler(self, pref_key):
        """
        Removes any present handlers at `pref_key`
        """
        try:
            self.handlers.pop(pref_key)
        except KeyError:
            pass

    def write(self):
        """
        Writes local prefs to `self.path`
        """
        raise NotImplementedError

    def read(self):
        """
        Reads and conforms to `self.path`
        """
        raise NotImplementedError

    def __setitem__(self, key, value):
        self.read()
        if key in self.handlers:
            value = self.handlers.get(key).set_pref(value)
            if not value:
                value = '<external>'
        super(PrefFile, self).__setitem__(key, value)
        self.write()

    def __getitem__(self, key):
        self.read()
        if key in self.handlers:
            return self.handlers.get(key).get_pref()
        return super(PrefFile, self).__getitem__(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def pop(self, key):
        super(PrefFile, self).pop(key)
        self.write()


class JsonPref(PrefFile):
    if sys.version_info[0] == 2:
        json_decode_err = Exception
    else:
        json_decode_err = json.decoder.JSONDecodeError

    def write(self):
        out = {}
        out.update(self)
        with open(self.path, 'w+') as fp:
            json.dump(out, fp, indent=4, sort_keys=False,
                      separators=(',', ': '))

    def read(self):
        contents = {}
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, 'r') as fp:
                contents = json.load(fp)
        except self.json_decode_err:
            broken_files.setdefault(self.path, 0)
            times_hit = broken_files[self.path]
            if times_hit < 3:
                warning = ''
                if times_hit == 2:
                    warning = "(I'll stop nagging now)"
                logger.error('Invalid json file "{}", please fix by hand or '
                             'delete it. {}'.format(self.path, warning))
            times_hit += 1
            broken_files[self.path] = times_hit
        self.clear()
        self.update(contents)


class PicklePref(PrefFile):
    def write(self):
        out = {}
        out.update(self)
        with open(self.path, 'wb+') as fp:
            pickle.dump(out, fp, protocol=2)

    def read(self):
        contents = {}
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, 'r+b') as fp:
                if sys.version_info[0] == 2:
                    contents = pickle.load(fp)
                else:
                    contents = pickle.load(fp, encoding='bytes')
        except pickle.UnpicklingError:
            broken_files.setdefault(self.path, 0)
            times_hit = broken_files[self.path]
            if times_hit < 3:
                warning = ''
                if times_hit == 2:
                    warning = "(I'll stop nagging now)"
                logger.error('Failed to load pickle pref "{}", probably '
                             'changed interpreter versions. {}'
                             ''.format(os.path.basename(self.path), warning))
            times_hit += 1
            broken_files[self.path] = times_hit
        self.clear()
        self.update(contents)


class PrefHandler(object):
    """
    A complete pref handler implements 2 functions: `set_pref` and `get_pref`.
    The pref handler is responsible for all serialization and retrieval of
    this data for the :class:`Prefs` object for which it is handling.
    """
    @staticmethod
    def get_pref():
        raise NotImplementedError('To get a preference from a PrefHandler, '
                                  '`get_pref` must be implemented.')

    @staticmethod
    def set_pref():
        """
        The return value of `set_pref` is used as the stand-in for the
        preference key being handled.
        """
        raise NotImplementedError('To set a pref via a pref handler, '
                                  '`set_pref` must be implemented.')


class LastOpenedHandler(PrefHandler):
    """
    Gets and sets the last opened file.
    """
    @staticmethod
    def get_pref():
        return editor_cache.get(USER_PREF.RECENT_FILES, [])[0]

    @staticmethod
    def set_pref(val):
        recents = editor_cache.get(USER_PREF.RECENT_FILES, [])
        if val in recents:
            recents.remove(val)
        recents.insert(0, val)
        if len(recents) > MAX_RECENT_FILES:
            recents = recents[:MAX_RECENT_FILES]
        editor_cache[USER_PREF.RECENT_FILES] = recents
        return EDITOR_CACHE_PATH


class BreakpointsHandler(PrefHandler):

    @staticmethod
    def get_pref():
        breakpoints = {}
        try:
            with open(BREAKPOINT_FILE, 'r') as f:
                breakpoints = pickle.load(f)
        except (OSError, IOError):
            pass
        return breakpoints

    @staticmethod
    def set_pref(val):
        with open(BREAKPOINT_FILE, 'w+') as f:
            pickle.dump(val, f)


class MultiFilePref(object):
    def __init__(self, pref_files):
        self.pref_files = pref_files

    def __setitem__(self, key, value):
        self.pref_files[0][key] = value

    def __getitem__(self, key):
        for pref_file in self.pref_files:
            pref_file.read()
            if key in pref_file:
                return pref_file[key]
        raise KeyError

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def pop(self, key):
        self.pref_files[0].pop(key)

    def keys(self):
        out_keys = set()
        for pref_file in self.pref_files:
            pref_file.read()
            out_keys.union(list(pref_file.keys()))
        return out_keys


user_prefs = JsonPref(USER_PREFS_PATH)
hotkeys = JsonPref(HOTKEYS_PREF)
breakpoints = JsonPref(BREAKPOINT_FILE)
skippoints = JsonPref(SKIPPOINT_FILE)
editor_cache = PicklePref(EDITOR_CACHE_PATH)
editor_cache.set_handler(USER_PREF.LAST_OPEN, LastOpenedHandler)
# TODO as a session starts(or ends?), let's create a symlink to
#  its file output called last_session.log
