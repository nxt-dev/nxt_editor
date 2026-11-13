# Builtin
import os
import json
# External
from Qt import QtGui, QtWidgets
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


class _FontManager:
    def __init__(self):
        self._initialized = False
        self._font_db = QtGui.QFontDatabase()
        self.DEFAULT_SIZE = 10
        self._default_family = "Sans Serif"
        self._code_family = "Monospace"

    def initialize(self):
        if self._initialized:
            return
        if not QtWidgets.QApplication.instance():
            return
        roboto_id = self._font_db.addApplicationFont(":/fonts/fonts/Roboto/Roboto-Regular.ttf")
        mono_id = self._font_db.addApplicationFont(":/fonts/fonts/RobotoMono/RobotoMono-Regular.ttf")

        if roboto_id != -1:
            self._default_family = self._font_db.applicationFontFamilies(roboto_id)[0]
        if mono_id != -1:
            self._code_family = self._font_db.applicationFontFamilies(mono_id)[0]

        self._initialized = True

    @property
    def DEFAULT_FAMILY(self):
        self.initialize()
        return self._default_family

    @property
    def MONOSPACE(self):
        self.initialize()
        return self._code_family

    def default_font(self, size=None):
        return self._sized(self.DEFAULT_FAMILY, size)

    def monospace_font(self, size=None):
        return self._sized(self.MONOSPACE, size)

    def _sized(self, family, size=None):
        """A font sized in points, made in pixels.

        A point is a different number of pixels on macOS than on Windows,
        and in a host that scales its interface, so the same point size
        did not look the same everywhere. Pixels do.
        """
        font = QtGui.QFont(family)
        font.setPixelSize(points_to_px(size or self.DEFAULT_SIZE))
        return font


def points_to_px(points):
    """Pixels for a size in points, at the 96 dots per inch most screens
    are laid out at."""
    return max(1, int(round(points * 96.0 / 72.0)))


FONTS = _FontManager()
PREF_DIR_INT = EDITOR_VERSION.MAJOR
PREF_DIR_NAME = 'prefs'
_pref_dir_num = str(PREF_DIR_INT)
PREF_DIR = os.path.join(USER_DIR, PREF_DIR_NAME, _pref_dir_num)

NXT_WEBSITE = 'https://nxt-dev.github.io/'
