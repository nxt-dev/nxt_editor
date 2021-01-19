# Builtin
import os
import json

# Internal
from nxt.constants import USER_DIR

version_file = os.path.join(os.path.dirname(__file__), 'version.json')


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


_pref_dir_name = str(EDITOR_VERSION.MAJOR)
PREF_DIR = os.path.join(USER_DIR, 'prefs', _pref_dir_name)

NXT_WEBSITE = 'https://nxt-dev.github.io/'
