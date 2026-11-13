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
import shutil
import sys
import time

if sys.version_info[0] == 2:
    import cPickle as pickle
else:
    import pickle

# Internal
from nxt.constants import USER_DIR
from nxt_editor.constants import PREF_DIR, PREF_DIR_INT, PREF_DIR_NAME
import nxt_editor

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

# Constants
USER_PREFS_PATH = os.path.join(PREF_DIR, 'prefs.json')
EDITOR_CACHE_PATH = os.path.join(PREF_DIR, 'editor_cache')
BREAKPOINT_FILE = os.path.join(PREF_DIR, 'breakpoints')
SKIPPOINT_FILE = os.path.join(PREF_DIR, 'skippoints')
HOTKEYS_PREF = os.path.join(PREF_DIR, 'hotkeys.json')
MAX_RECENT_FILES = 10
JSON_PREFS = [USER_PREFS_PATH, BREAKPOINT_FILE, SKIPPOINT_FILE, HOTKEYS_PREF]
broken_files = {}
# Errors a half written or damaged pickle can raise while loading.
PICKLE_LOAD_ERRORS = (pickle.UnpicklingError, EOFError, ValueError,
                      TypeError, AttributeError, ImportError, IndexError,
                      KeyError)


def write_whole_file(path, mode, dump):
    """Write a file so that a reader only ever sees all of it.

    Writing straight to `path` empties it first, so another editor (Maya
    and standalone share these files) reading at that moment, or a write
    that fails part way, would find an empty or broken file. `dump` writes
    to a temporary file next to it, which then replaces `path` in one go.

    :param path: the file to write
    :param mode: the mode to open the file in, such as 'w' or 'wb'
    :param dump: called with the open file to write the contents
    :return: True if `path` was replaced
    """
    tmp = '{}.{}.tmp'.format(path, os.getpid())
    try:
        with open(tmp, mode) as fp:
            dump(fp)
            fp.flush()
            os.fsync(fp.fileno())
        # Windows will not replace a file someone else is reading this very
        # moment, so give them a moment to finish.
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                return True
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)
    except Exception as err:
        logger.warning('Could not write "{}": {}'.format(path, err))
        try:
            os.remove(tmp)
        except OSError:
            pass
    return False


def warn_broken(path, message):
    broken_files.setdefault(path, 0)
    times_hit = broken_files[path]
    if times_hit < 3:
        warning = ''
        if times_hit == 2:
            warning = "(I'll stop nagging now)"
        logger.error('{} {}'.format(message, warning).strip())
    broken_files[path] = times_hit + 1


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


def get_upgradable_prefs():
    """
    Identify preference files that can be safely upgraded
    between major editor versions. Only existing preference files
    from the nearest older version are copied; missing files are skipped
    without warnings. Returns a list of prefs that can upgrade and the
    versio number they're coming from.
    :returns: (list, int)
    """
    upgradable_prefs = []
    upgrade_prefs_from_version = -1
    for pref_file in JSON_PREFS:
        if os.path.isfile(pref_file):
            break
    else:  # Didn't find any json prefs in current version prefs
        dir_num = PREF_DIR_INT - 1
        while dir_num > -1:
            old_pref_dir = os.path.join(USER_DIR, PREF_DIR_NAME, str(dir_num))
            for pref_file in JSON_PREFS:
                file_name = os.path.basename(pref_file)
                old_pref_file = os.path.join(old_pref_dir, file_name)
                if os.path.isfile(old_pref_file):
                    # In the future if we change the structure of the json
                    # prefs we'll need a way to convert them or skip
                    upgradable_prefs.append(old_pref_file)
            if upgradable_prefs:
                upgrade_prefs_from_version = dir_num
                break
            dir_num -= 1
    return upgradable_prefs, upgrade_prefs_from_version


def upgrade_prefs(prefs_to_upgrade):
    """
    Copies old 'upgradeable' prefs to current pref dir, will eat and
    exception raised by shutil.copy. In the future this function may do more
    than simply copy.
    :param prefs_to_upgrade: List of pref filepaths to upgrade
    """
    for pref_file in prefs_to_upgrade:
        try:
            shutil.copy(pref_file, PREF_DIR)
        except Exception as e:
            logger.error(e)
            logger.error(f'Failed to copy old pref file: {pref_file}')


ensure_pref_dir_exists()
# Must check these before we setup the defaults at the bottom of this file
UPGRADABLE_PREFS, UPGRADE_PREFS_FROM_VERSION = get_upgradable_prefs()


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
    CE_AUTOCOMPLETE = 'code_editor_autocomplete'
    # What the code editor offers completions from, each on its own
    CE_COMPLETE_PYTHON = 'code_editor_complete_python'
    CE_COMPLETE_MODULES = 'code_editor_complete_modules'
    CE_COMPLETE_NODE = 'code_editor_complete_node'
    CE_COMPLETE_DOCUMENT = 'code_editor_complete_document'
    CE_COMPLETE_HOST = 'code_editor_complete_host'
    CE_COMPLETE_JEDI = 'code_editor_complete_jedi'
    DING = 'ding'
    SHOW_GRID = 'show_grid'
    SHOW_IMPLICIT = 'show_implicit_connections'
    SHOW_MINI_MAP = 'show_mini_map'
    FONT_SIZE = 'font_size'
    # Whether the graph is shown. On unless turned off in the Window menu.
    SHOW_STAGE_VIEW = 'show_stage_view'
    # How lines between nodes are drawn in a graph that does not save its
    # own choice: 'straight' or 'curved'. See nxt_editor.wires.
    CONNECTION_STYLE = 'connection_style'
    # The AI assistant, off until a user turns it on. Keys and sign ins
    # are not kept here, see nxt_editor.ai.secret_store.
    AI_ENABLED = 'ai_assistant_enabled'
    AI_PROVIDER = 'ai_assistant_provider'
    AI_MODELS = 'ai_assistant_models'
    AI_AUTH = 'ai_assistant_auth'
    AI_INCLUDE_SELECTION = 'ai_assistant_include_selection'
    AI_ALLOW_EDITS = 'ai_assistant_allow_edits'
    AI_ALLOW_RUNS = 'ai_assistant_allow_runs'
    AI_MEMORY = 'ai_assistant_memory'
    AI_FOLDERS = 'ai_assistant_folders'
    AI_OPENAI_HOST_ID = 'ai_assistant_openai_host_id'
    AI_OPENAI_CLIENT_ID = 'ai_assistant_openai_client_id'
    AI_LOCAL_URL = 'ai_assistant_local_url'
    AI_CLAUDE_CODE_PATH = 'ai_assistant_claude_code_path'


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
        self._stamp = None
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

    def file_stamp(self):
        """
        Identity of `self.path` right now, or None if it isn't there.

        Prefs are re-read on every dictionary access, so a single editor
        redraw can parse the same small file a thousand times. Subclass
        `read` implementations compare this against `self._stamp` and skip
        the parse when the file has not moved. Our own `write` changes the
        file, so the next read picks it up like any other edit.
        """
        try:
            stat = os.stat(self.path)
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

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
        write_whole_file(self.path, 'w',
                         lambda fp: json.dump(out, fp, indent=4,
                                              sort_keys=False,
                                              separators=(',', ': ')))
        self._stamp = None

    def read(self):
        stamp = self.file_stamp()
        if stamp is None:
            return
        if stamp == self._stamp:
            return
        try:
            with open(self.path, 'r') as fp:
                contents = json.load(fp)
        except (self.json_decode_err, OSError):
            # Keep what we have, the next write puts the file right.
            warn_broken(self.path, 'Invalid json file "{}", please fix by '
                                   'hand or delete it.'.format(self.path))
            self._stamp = stamp
            return
        self.clear()
        self.update(contents)
        self._stamp = stamp


class PicklePref(PrefFile):
    def write(self):
        out = {}
        out.update(self)
        write_whole_file(self.path, 'wb',
                         lambda fp: pickle.dump(out, fp, protocol=2))
        self._stamp = None

    def read(self):
        stamp = self.file_stamp()
        if stamp is None:
            return
        if stamp == self._stamp:
            return
        try:
            with open(self.path, 'rb') as fp:
                contents = pickle.load(fp, encoding='bytes')
        except ModuleNotFoundError as e:
            if 'PySide2' in e.msg:
                shutil.move(self.path, self.path + '.backup')
            contents = {}
        except (OSError,) + PICKLE_LOAD_ERRORS:
            # An empty or broken cache, from a write that never finished.
            # Keep what we have, the next write puts the file right.
            warn_broken(self.path, 'Failed to load pickle pref "{}", it may '
                                   'be damaged or from another interpreter.'
                                   ''.format(os.path.basename(self.path)))
            self._stamp = stamp
            return
        if not isinstance(contents, dict):
            contents = {}
        self.clear()
        self.update(contents)
        self._stamp = stamp


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


def last_opened_dir():
    """The folder a graph was last opened from, for file dialogs to start
    in when there is no saved graph to start beside.

    :return: that folder, or the working directory when there is none
    :rtype: str
    """
    try:
        last = editor_cache.get(USER_PREF.RECENT_FILES, [])[0]
    except (IndexError, TypeError, KeyError):
        last = None
    if last:
        folder = os.path.dirname(last)
        if os.path.isdir(folder):
            return folder
    return os.getcwd()


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
