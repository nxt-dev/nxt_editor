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
import math
import re

# External
from Qt import QtCore, QtGui

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
DARK_TEXT = '#141414'          # text on a bright layer color
BRIGHT = 0.3                 # the luminance past which text goes dark
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


def luminance(value):
    """How bright a color looks, 0 for black to 1 for white (WCAG)."""
    value = QtGui.QColor(value)

    def channel(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return (0.2126 * channel(value.red()) +
            0.7152 * channel(value.green()) +
            0.0722 * channel(value.blue()))


def contrast(a, b):
    """The contrast ratio between two colors, 1 to 21 (WCAG)."""
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


# The layer palette's hues are spread evenly in OKLCH, a color space where
# equal steps look equal, at one lightness and chroma, before each is made
# dark enough for white text, see colors.LAYER_COLORS.
PALETTE_LIGHTNESS = 0.65
PALETTE_CHROMA = 0.15


def _linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gamma(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def to_oklch(value):
    """A color's OKLCH: lightness 0 to 1, chroma, and hue in degrees.

    :rtype: (float, float, float)
    """
    value = QtGui.QColor(value)
    r, g, b = (_linear(c) for c in (value.redF(), value.greenF(),
                                    value.blueF()))
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3.0)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3.0)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3.0)
    lightness = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b_ = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    chroma = math.hypot(a, b_)
    hue = math.degrees(math.atan2(b_, a)) % 360.0
    return lightness, chroma, hue


def _oklch_rgb(lightness, chroma, hue):
    """Linear-free sRGB channels for an OKLCH color, unclipped."""
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    l_ = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    b2 = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_
    return r, g, b2


def from_oklch(lightness, chroma, hue):
    """The sRGB color for an OKLCH one. A chroma the screen can not show at
    that lightness and hue is brought down until it can.

    :rtype: QtGui.QColor
    """
    def fits(c):
        return all(-1e-6 <= v <= 1 + 1e-6 for v in _oklch_rgb(lightness, c,
                                                              hue))
    if not fits(chroma):
        low, high = 0.0, chroma
        for _ in range(24):
            middle = (low + high) / 2.0
            if fits(middle):
                low = middle
            else:
                high = middle
        chroma = low
    channels = [_gamma(min(max(v, 0.0), 1.0))
                for v in _oklch_rgb(lightness, chroma, hue)]
    return QtGui.QColor.fromRgbF(*channels)


# The least contrast a layer's color keeps with the white text on it.
# WCAG's for regular sized text, so the Outliner's names read too.
WHITE_TEXT_CONTRAST = 4.5


def white_text_safe(value):
    """value, as dark as it has to be for white text to read on it.

    A color white text already reads on is kept. A brighter one keeps its
    hue and saturation and is darkened only as far as it takes, so a
    yellow becomes a deep gold rather than a brown.

    :param value: a color, or anything QColor takes
    :rtype: QtGui.QColor
    """
    value = QtGui.QColor(value)
    if contrast(value, NODE_TEXT) >= WHITE_TEXT_CONTRAST:
        return value
    hue, saturation, lightness, alpha = value.getHslF()
    hue = max(hue, 0.0)  # greys have no hue
    low, high = 0.0, lightness
    for _ in range(20):
        middle = (low + high) / 2.0
        test = QtGui.QColor.fromHslF(hue, saturation, middle, alpha)
        if contrast(test, NODE_TEXT) >= WHITE_TEXT_CONTRAST:
            low = middle
        else:
            high = middle
    return QtGui.QColor.fromHslF(hue, saturation, low, alpha)


def readable_text(background):
    """Light or dark text, whichever reads better on a background.

    Layer colors run from deep reds to bright yellows, and white text
    on the bright ones is hard to read. Strict contrast ratios would turn
    mid tones such as orange or teal dark too, where light text still
    reads well and matches the rest, so text only goes dark once a color
    is clearly bright.

    :rtype: QtGui.QColor
    """
    if luminance(background) > BRIGHT:
        return color(DARK_TEXT)
    return color(NODE_TEXT)


# Diagonal stripes across an instanced node, so it can be told from one
# that is not at a glance. Darker than the node, so its white text reads.
STRIPE_WIDTH = 3.0
STRIPE_GAP = 6.0
STRIPE_DARKER = 140


def paint_stripes(painter, rect, base):
    """Diagonal stripes, a darker shade of base, across rect.

    :param painter: QPainter, clipped as wanted by the caller
    :param rect: QRectF to stripe
    :param base: the color under them
    """
    rect = QtCore.QRectF(rect)
    stripe = QtGui.QColor(base).darker(STRIPE_DARKER)
    stripe.setAlpha(QtGui.QColor(base).alpha())
    painter.save()
    painter.setClipRect(rect, QtCore.Qt.IntersectClip)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(stripe, STRIPE_WIDTH)
    pen.setCapStyle(QtCore.Qt.FlatCap)
    painter.setPen(pen)
    step = STRIPE_WIDTH + STRIPE_GAP
    height = rect.height()
    x = rect.left() - height
    while x < rect.right() + step:
        painter.drawLine(QtCore.QPointF(x, rect.bottom()),
                         QtCore.QPointF(x + height, rect.top()))
        x += step
    painter.restore()


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
