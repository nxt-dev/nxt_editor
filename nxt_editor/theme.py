"""The editor's look: its colors, fonts and stylesheet, in one place.

The editor has to look the same standalone and in every host. A host
brings its own style, palette, application stylesheet, fonts and screen
scaling, so nothing here leans on them:

- Colors are ours, and every stylesheet the editor sets is built from
  them. The stylesheet goes on the editor's own windows, never on a
  host's application.
- Fonts are the Roboto faces shipped in resources, registered when the
  first one is asked for, and sized in pixels. A point size turns into a
  different number of pixels on macOS than on Windows, and in a host
  that changes its scaling, where pixels do not.
"""
# Builtin
import re

# External
from Qt import QtGui

# Internal
from nxt_editor.constants import FONTS, points_to_px  # noqa: F401

# -- surfaces, darkest first -----------------------------------------------
GRAPH = '#1d1d1d'        # behind the nodes
BASE = '#242424'         # panels and windows
RAISED = '#2c2c2c'       # title bars, inputs, buttons
HOVER = '#353535'        # anything under the mouse
PRESSED = '#3e3e3e'
BORDER = '#333333'
BORDER_STRONG = '#474747'

# -- text --------------------------------------------------------------------
TEXT = '#e6e6e6'
TEXT_DIM = '#a6a6a6'
TEXT_FAINT = '#6e6e6e'

# -- accent, for focus, selection and anything active. Greys, not a hue, so
# the only color on screen is the layers' own -------------------------------
ACCENT = '#909090'
ACCENT_STRONG = '#525252'
ACCENT_DIM = '#3c3c3c'

# -- the graph ---------------------------------------------------------------
NODE_BODY = '#2a2a2a'        # a node's attribute rows
NODE_TEXT = '#f2f2f2'
SELECTED = '#ffb547'         # the outline of a selected node
HOVERED = '#ffffff'
GRID_MINOR = (255, 255, 255, 9)
GRID_MAJOR = (255, 255, 255, 20)

RADIUS = 6               # panels, buttons and inputs
NODE_RADIUS = 6

# -- type sizes, in pixels -----------------------------------------------------
TEXT_PX = 13
SMALL_PX = 11
NODE_TITLE_PX = 16
NODE_ATTR_PX = 13

# Every face that ships, so a weight or slant is the real one wherever the
# editor runs instead of whatever the host would make up.
FACES = ('Regular', 'Italic', 'Medium', 'MediumItalic', 'Bold',
         'BoldItalic', 'Light', 'LightItalic')

_registered = []


def register_fonts():
    """Add the shipped Roboto faces to Qt's font database, once."""
    if _registered:
        return
    FONTS.initialize()
    if not FONTS._initialized:
        # No application yet, so there is nothing to add them to.
        return
    for family in ('Roboto', 'RobotoMono'):
        for face in FACES:
            path = ':/fonts/fonts/{0}/{0}-{1}.ttf'.format(family, face)
            QtGui.QFontDatabase.addApplicationFont(path)
    _registered.append(True)


def font(px=TEXT_PX, weight=None, italic=False, mono=False):
    """One of the editor's fonts, sized in pixels.

    :param px: height in pixels
    :param weight: a QFont.Weight, regular when None
    :param italic: slanted
    :param mono: the code font rather than the interface one
    :rtype: QtGui.QFont
    """
    register_fonts()
    result = QtGui.QFont(FONTS.MONOSPACE if mono else FONTS.DEFAULT_FAMILY)
    result.setPixelSize(int(px))
    if weight is not None:
        result.setWeight(weight)
    result.setItalic(italic)
    # Hinting changes glyph widths with the platform, which moves where
    # a title gets cut off. Leaving it to the outlines keeps text the same
    # width everywhere.
    result.setHintingPreference(QtGui.QFont.PreferNoHinting)
    return result


def color(value, alpha=None):
    """A QColor from one of the colors here.

    :param value: a hex string, or an (r, g, b, a) tuple
    :param alpha: 0 to 1, replacing the color's own
    :rtype: QtGui.QColor
    """
    if isinstance(value, tuple):
        result = QtGui.QColor(*value)
    else:
        result = QtGui.QColor(value)
    if alpha is not None:
        result.setAlphaF(alpha)
    return result


def mix(a, b, amount):
    """a, moved towards b by amount (0 to 1).

    :rtype: QtGui.QColor
    """
    a, b = QtGui.QColor(a), QtGui.QColor(b)
    keep = 1.0 - amount
    return QtGui.QColor(int(a.red() * keep + b.red() * amount),
                        int(a.green() * keep + b.green() * amount),
                        int(a.blue() * keep + b.blue() * amount),
                        int(a.alpha() * keep + b.alpha() * amount))


# The colors the original dark stylesheet, and the styles written
# against it, were built from, and which of the theme's colors each one is
# now. The old sheet used one grey for both raised backgrounds and borders,
# so what a color becomes depends on what it is coloring.
LEGACY = {
    # old color: (as a background, as a border, as text)
    '#1e1e1e': ('GRAPH', 'BORDER', 'TEXT'),
    '#232323': ('BASE', 'GRAPH', 'BASE'),
    '#232629': ('BASE', 'GRAPH', 'BASE'),
    '#262626': ('RAISED', 'BORDER', 'TEXT'),
    '#2b2b2b': ('RAISED', 'BORDER', 'TEXT'),
    '#303030': ('RAISED', 'BORDER', 'TEXT'),
    '#31363b': ('RAISED', 'BORDER', 'TEXT'),
    '#323232': ('RAISED', 'BORDER', 'TEXT'),
    '#333333': ('RAISED', 'BORDER', 'TEXT'),
    '#3a3a3a': ('HOVER', 'BORDER', 'TEXT'),
    '#3e3e3e': ('RAISED', 'BORDER', 'TEXT'),
    '#4c4c4c': ('HOVER', 'BORDER_STRONG', 'TEXT_FAINT'),
    '#4d545b': ('HOVER', 'BORDER_STRONG', 'TEXT_FAINT'),
    '#5a5a5a': ('PRESSED', 'BORDER_STRONG', 'TEXT_FAINT'),
    '#5c5c5c': ('PRESSED', 'BORDER_STRONG', 'TEXT_FAINT'),
    '#606060': ('PRESSED', 'BORDER_STRONG', 'TEXT_FAINT'),
    '#787878': ('PRESSED', 'TEXT_FAINT', 'TEXT_FAINT'),
    '#9a9a9a': ('TEXT_DIM', 'TEXT_DIM', 'TEXT_DIM'),
    '#a9a9a9': ('TEXT_DIM', 'TEXT_DIM', 'TEXT_DIM'),
    '#aaaaaa': ('TEXT_DIM', 'TEXT_DIM', 'TEXT_DIM'),
    '#d4d4d4': ('TEXT', 'TEXT', 'TEXT'),
    '#e0e0e0': ('TEXT', 'TEXT', 'TEXT'),
    '#eff0f1': ('TEXT', 'TEXT', 'TEXT'),
    '#f0f0f0': ('TEXT', 'TEXT', 'TEXT'),
    '#148cd2': ('ACCENT', 'ACCENT', 'ACCENT'),
    '#179ae0': ('ACCENT', 'ACCENT', 'ACCENT'),
    '#1464a0': ('ACCENT_STRONG', 'ACCENT_STRONG', 'ACCENT'),
    '#3375a3': ('ACCENT_STRONG', 'ACCENT_STRONG', 'ACCENT'),
    '#14506e': ('ACCENT_DIM', 'ACCENT_DIM', 'ACCENT'),
    '#18465d': ('ACCENT_DIM', 'ACCENT_DIM', 'ACCENT'),
}
_HEX = re.compile(r'#[0-9a-fA-F]{6}(?![0-9a-fA-F])')
_PROPERTY = re.compile(r'([a-zA-Z-]+)\s*:[^;:{}]*$')


def legacy_token(hex_color, before=''):
    """The theme color's name for one of the old colors, or None.

    :param hex_color: the old color, such as '#3E3E3E'
    :param before: the stylesheet text leading up to it, which says
        whether it is a background, a border or text
    """
    choices = LEGACY.get(hex_color.lower())
    if not choices:
        return None
    match = _PROPERTY.search(before)
    name = match.group(1).lower() if match else ''
    if 'border' in name or name == 'outline' or name == 'gridline-color':
        return choices[1]
    if name == 'color' or name.endswith('-color') and 'background' not in name:
        return choices[2]
    return choices[0]


def restyle(sheet):
    """A stylesheet written for the old colors, in the theme's."""
    def swap(match):
        token = legacy_token(match.group(0), sheet[:match.start()])
        return globals()[token] if token else match.group(0)
    return _HEX.sub(swap, sheet)


def tokens():
    """The names a stylesheet can use as {NAME}, and their values."""
    return {name: value for name, value in globals().items()
            if name.isupper() and isinstance(value, (str, int))}


def fill(sheet):
    """A stylesheet with each {NAME} replaced by that value from here.

    Braces are a stylesheet's own syntax too, so only a name made of
    capitals and underscores, alone in its braces, is replaced.
    """
    values = tokens()
    register_fonts()
    values['FONT_FAMILY'] = FONTS.DEFAULT_FAMILY
    return re.sub(r'\{([A-Z_]+)\}',
                  lambda m: str(values.get(m.group(1), m.group(0))), sheet)
