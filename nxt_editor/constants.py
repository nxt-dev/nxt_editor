# Builtin
import os
import json

# Internal
from nxt.constants import USER_DIR

EDITOR_DIR = os.path.dirname(__file__)
version_file = os.path.join(EDITOR_DIR, 'version.json')


class EDITOR_VERSION(object):
    with open(version_file, 'r') as f:
        version_data = json.load(f)
    api_v_data = version_data['EDITOR']
    MAJOR = api_v_data['MAJOR']
    MINOR = api_v_data['MINOR']
    PATCH = api_v_data['PATCH']
    VERSION_TUPLE = (MAJOR, MINOR, PATCH)
    VERSION_STR = '.'.join(str(v) for v in VERSION_TUPLE)
    VERSION = VERSION_STR


class FONTS(object):
    DEFAULT_FAMILY = 'Roboto Mono'
    DEFAULT_SIZE = 10


PREF_DIR_INT = EDITOR_VERSION.MAJOR
PREF_DIR_NAME = 'prefs'
_pref_dir_num = str(PREF_DIR_INT)
PREF_DIR = os.path.join(USER_DIR, PREF_DIR_NAME, _pref_dir_num)

NXT_WEBSITE = 'https://nxt-dev.github.io/'
