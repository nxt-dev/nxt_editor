# Built-in
import os
import json

version_file = os.path.join(os.path.dirname(__file__), 'version.json')


class API_VERSION(object):
    with open(version_file, 'r') as f:
        version_data = json.load(f)
    api_v_data = version_data['API']
    MAJOR = api_v_data['MAJOR']
    MINOR = api_v_data['MINOR']
    PATCH = api_v_data['PATCH']
    VERSION_TUPLE = (MAJOR, MINOR, PATCH)
    VERSION_STR = '.'.join(str(v) for v in VERSION_TUPLE)
    VERSION = VERSION_STR


class GRAPH_VERSION(object):
    with open(version_file, 'r') as f:
        version_data = json.load(f)
    api_v_data = version_data['GRAPH']
    MAJOR = api_v_data['MAJOR']
    MINOR = api_v_data['MINOR']
    VERSION_TUPLE = (MAJOR, MINOR)
    VERSION_STR = '.'.join(str(v) for v in VERSION_TUPLE)
    VERSION = VERSION_STR


# User and Site Dirs
USER_DIR_ENV_VAR = 'NXT_USER_DIR'
SITE_DIR_ENV_VAR = 'NXT_SITE_DIR'

if USER_DIR_ENV_VAR in os.environ:
    USER_DIR = os.environ.get(USER_DIR_ENV_VAR)
else:
    USER_DIR = os.path.expanduser(os.path.join('~', 'nxt'))

SITE_DIR = USER_DIR
if SITE_DIR_ENV_VAR in os.environ:
    SITE_DIR = os.environ.get(SITE_DIR_ENV_VAR)
# Configs
CONFIG_VERSION = str(API_VERSION.MAJOR)
USER_CONFIG_DIR = os.path.join(USER_DIR, 'config', CONFIG_VERSION)
SITE_CONFIG_DIR = os.path.join(SITE_DIR, 'config', CONFIG_VERSION)
# Plugins
PLUGIN_DIR_NAME = 'plugins'
BUILTIN_PLUGIN_DIR = os.path.join(os.path.dirname(__file__), PLUGIN_DIR_NAME)
USER_PLUGIN_DIR = os.path.join(USER_CONFIG_DIR, PLUGIN_DIR_NAME)
SITE_PLUGIN_DIR = os.path.join(SITE_CONFIG_DIR, PLUGIN_DIR_NAME)
PLUGIN_DIRS = [USER_PLUGIN_DIR, SITE_PLUGIN_DIR, BUILTIN_PLUGIN_DIR]


class DATA_STATE:
    RAW = 'raw'
    RESOLVED = 'resolved'
    CACHED = 'cached'


class NODE_ERRORS:
    INSTANCE = 'Broken instance'
    EXEC = 'Broken exec in'
    ORPHANS = 'Orphan children'


class FILE_FORMAT(object):
    ASCII = '.nxt'
    BINARY = '.nxtb'
    _ALL = (ASCII, BINARY)


UNTITLED = 'untitled'
IGNORE = '<!ignore!>'
GRID_SIZE = 20  # Must be int
