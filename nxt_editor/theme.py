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
import os
import re
import sys

# External
from Qt import QtCore, QtGui, QtWidgets

# Internal
from nxt_editor.constants import FONTS, points_to_px  # noqa: F401

# -- surfaces, darkest first -----------------------------------------------
GRAPH = '#1d1d1d'        # behind the nodes
BASE = '#242424'         # panels and windows
RAISED = '#2c2c2c'       # title bars, inputs, buttons
INPUT = '#1d1d1d'        # inside a text field, list of choices or editor
BUTTON = '#2c2c2c'       # a push button
MENU = '#2c2c2c'         # menus, tooltips and the list a choice opens
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
LINK = '#6fb3ff'          # links in text
ERROR = '#e07070'         # text saying something went wrong

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
    for family in ('Roboto', 'RobotoMono', 'Inter'):
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
    app = QtWidgets.QApplication.instance()
    if LOOK == LOOK_HOST and HOST_DRAWS and app is not None and not mono:
        # The host's font, and at the host's size where the editor would
        # use its own standard size: the host's style measures titles and
        # tabs with it, and text of another size no longer fits them.
        result = QtGui.QFont(app.font())
        if int(px) != TEXT_PX:
            result.setPixelSize(int(px))
        if weight is not None:
            result.setWeight(weight)
        result.setItalic(italic)
        return result
    result = QtGui.QFont(FONTS.MONOSPACE if mono else font_family())
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
    lines = []
    while x < rect.right() + step:
        lines += [QtCore.QLineF(x, rect.bottom(), x + height, rect.top())]
        x += step
    # In one call: a graph full of instances has thousands of these.
    painter.drawLines(lines)
    painter.restore()


# A tag: a word in a small rounded box beside a name, such as Global or
# Default. Lit, it is filled; unlit, only outlined, for one that could be
# but is not, such as a modifier key not held.
TAG_PAD = 6
TAG_HEIGHT = 18
TAG_RADIUS = 4


def tag_width(text, font, pad=TAG_PAD):
    return QtGui.QFontMetrics(font).horizontalAdvance(text) + pad * 2


def paint_tag(painter, rect, text, font, lit=True, radius=TAG_RADIUS):
    """A tag, with text centered in rect.

    :param rect: QRectF, as wide as tag_width gives
    """
    rect = QtCore.QRectF(rect)
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    if lit:
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(color(ACCENT_DIM))
    else:
        painter.setPen(QtGui.QPen(color(BORDER_STRONG), 1))
        painter.setBrush(QtCore.Qt.NoBrush)
        rect = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    painter.drawRoundedRect(rect, radius, radius)
    painter.setFont(font)
    painter.setPen(color(TEXT if lit else TEXT_FAINT))
    painter.drawText(rect, QtCore.Qt.AlignCenter, text)
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
    if LOOK == LOOK_CLASSIC:
        # The classic look is those colors.
        return sheet

    def swap(match):
        token = legacy_token(match.group(0), sheet[:match.start()])
        return globals()[token] if token else match.group(0)
    return _HEX.sub(swap, sheet)


def tokens():
    """The names a stylesheet can use as {NAME}, and their values."""
    # A copy: the module's names can change while this reads them, which
    # stops the read with "dictionary changed size during iteration".
    return {name: value for name, value in list(globals().items())
            if name.isupper() and isinstance(value, (str, int))}


def fill(sheet):
    """A stylesheet with each {NAME} replaced by that value from here.

    Braces are a stylesheet's own syntax too, so only a name made of
    capitals and underscores, alone in its braces, is replaced.
    """
    values = tokens()
    register_fonts()
    values['FONT_FAMILY'] = font_family()
    return re.sub(r'\{([A-Z_]+)\}',
                  lambda m: str(values.get(m.group(1), m.group(0))), sheet)


# Looks ----------------------------------------------------------------------
# Everything above is the modern look. A look is a set of values for the
# names above, put in place as this module loads and again, if it was
# changed, as each editor window opens (take_stored_look). Widgets take
# the look as they are made, so a change shows in the next editor.
LOOK_MODERN = 'modern'    # nxt's own look, the same in every host
LOOK_CLASSIC = 'classic'  # nxt as it looked before the modern look
LOOK_HOST = 'host'        # the colors, font and widgets of the host
LOOK_NAMES = ((LOOK_MODERN, 'Modern'), (LOOK_CLASSIC, 'Classic'),
              (LOOK_HOST, 'Host application'))
LOOK_PREF = 'look'
LOOK_ENV_VAR = 'NXT_EDITOR_LOOK'
STYLESHEET_PREF = 'look_stylesheet'
STYLESHEET_ENV_VAR = 'NXT_EDITOR_STYLESHEET'
LOOK = LOOK_MODERN
# Whether node titles and attributes are in the code font, 0 or 1.
NODE_MONO = 0
# Under the host look: which host, and whether it draws the editor's
# widgets itself (a Qt host, such as Maya) or the editor draws them in
# the host's colors (Blender and Unreal, which are not Qt applications).
HOST = ''
HOST_DRAWS = 0
# The family the interface is written in under the host look, when it is
# not the host application's own.
HOST_FAMILY = ''

MAYA, BLENDER, UNREAL = 'maya', 'blender', 'unreal'
HOSTS = (MAYA, BLENDER, UNREAL)

# The colors of hosts that are not Qt applications, from their default
# themes, for the names above. Blender's are its default theme's, and
# Unreal's its editor's style colors.
HOST_LOOKS = {
    BLENDER: {
        'GRAPH': '#1d1d1d', 'BASE': '#303030', 'RAISED': '#3d3d3d',
        'INPUT': '#1d1d1d', 'BUTTON': '#545454', 'MENU': '#181818',
        'HOVER': '#474747', 'PRESSED': '#656565',
        'BORDER': '#242424', 'BORDER_STRONG': '#3d3d3d',
        'TEXT': '#e6e6e6', 'TEXT_DIM': '#a6a6a6', 'TEXT_FAINT': '#737373',
        'ACCENT': '#4772b3', 'ACCENT_STRONG': '#4772b3',
        'ACCENT_DIM': '#334a6c',
        'NODE_BODY': '#303030', 'SELECTED': '#ed5700',
        'RADIUS': 4, 'NODE_RADIUS': 5,
        'HOST_FAMILY': 'Inter',
    },
    UNREAL: {
        'GRAPH': '#262626', 'BASE': '#242424', 'RAISED': '#2f2f2f',
        'INPUT': '#0f0f0f', 'BUTTON': '#383838', 'MENU': '#242424',
        'HOVER': '#3c3c3c', 'PRESSED': '#575757',
        'BORDER': '#0f0f0f', 'BORDER_STRONG': '#383838',
        'TEXT': '#c0c0c0', 'TEXT_DIM': '#969696', 'TEXT_FAINT': '#606060',
        'ACCENT': '#0070e0', 'ACCENT_STRONG': '#0070e0',
        'ACCENT_DIM': '#40576f',
        'NODE_BODY': '#1a1a1a',
        'RADIUS': 4, 'NODE_RADIUS': 6,
        'HOST_FAMILY': 'Roboto',
    },
}


def running_host():
    """The host the editor is running in, or '' standalone.

    The host's integration names it in an environment variable as it
    opens the editor, which can be after this module loads, so a host's
    own Python module being loaded counts too.

    :return: one of HOSTS, or ''
    :rtype: str
    """
    try:
        from nxt.constants import NXT_DCC_ENV_VAR
        named = os.environ.get(NXT_DCC_ENV_VAR, '').strip().lower()
    except ImportError:
        named = ''
    if named in HOSTS:
        return named
    if 'bpy' in sys.modules:
        return BLENDER
    if 'unreal' in sys.modules:
        return UNREAL
    if 'maya.cmds' in sys.modules:
        return MAYA
    return ''

# The colors of the original dark stylesheet, which the classic look uses
# as it was written, and the sizes nodes were drawn at.
CLASSIC = {
    'GRAPH': '#232323', 'BASE': '#232323', 'RAISED': '#3e3e3e',
    'HOVER': '#4c4c4c', 'PRESSED': '#5a5a5a',
    'BORDER': '#3e3e3e', 'BORDER_STRONG': '#4c4c4c',
    'TEXT': '#f0f0f0', 'TEXT_DIM': '#a9a9a9', 'TEXT_FAINT': '#787878',
    'ACCENT': '#148cd2', 'ACCENT_STRONG': '#1464a0', 'ACCENT_DIM': '#14506e',
    'NODE_BODY': '#2b2b2b', 'NODE_TEXT': '#ffffff', 'SELECTED': '#e8e536',
    'RADIUS': 2, 'NODE_RADIUS': 2, 'NODE_MONO': 1,
    'NODE_TITLE_PX': 19, 'NODE_ATTR_PX': 12,
}


def host_colors():
    """The host's own colors for the names above, from its palette.

    There is a look to take only from a host that is a Qt application
    with a dark interface, such as Maya. Where nxt makes the application
    itself, standalone and in Blender and Unreal, the palette is Qt's
    default and nobody's look. And the graph, the nodes and the log are
    drawn for a dark interface, so they would not read on a light one.

    :return: name: value, empty when there is no host look to take
    :rtype: dict
    """
    app = QtWidgets.QApplication.instance()
    if app is None:
        return {}
    import nxt_editor
    if nxt_editor.owns_qapp():
        return {}
    palette = app.palette()
    role = QtGui.QPalette

    def name(color_role, group=role.Active):
        return palette.color(group, color_role).name()
    window, text = name(role.Window), name(role.WindowText)
    if luminance(window) >= luminance(text):
        return {}
    button, highlight = name(role.Button), name(role.Highlight)
    return {
        'GRAPH': name(role.Base), 'BASE': window, 'RAISED': button,
        'HOVER': mix(button, text, 0.12).name(),
        'PRESSED': mix(button, text, 0.22).name(),
        'BORDER': mix(window, text, 0.14).name(),
        'BORDER_STRONG': mix(window, text, 0.28).name(),
        'TEXT': text, 'TEXT_DIM': mix(text, window, 0.3).name(),
        'TEXT_FAINT': name(role.WindowText, role.Disabled),
        'ACCENT': highlight,
        'ACCENT_STRONG': mix(highlight, window, 0.35).name(),
        'ACCENT_DIM': mix(highlight, window, 0.6).name(),
        'NODE_BODY': mix(window, name(role.Base), 0.5).name(),
        'RADIUS': 2, 'NODE_RADIUS': 3,
    }


def font_family():
    """The family the interface is written in: the host's under the host
    look, the editor's own otherwise.

    :rtype: str
    """
    if LOOK == LOOK_HOST and HOST_FAMILY:
        register_fonts()
        return HOST_FAMILY
    app = QtWidgets.QApplication.instance()
    if LOOK == LOOK_HOST and HOST_DRAWS and app is not None:
        return app.font().family()
    return FONTS.DEFAULT_FAMILY


# The little the host look does style, where a host's own drawing of a
# plain Qt widget does not read: Maya draws a dock's title through its row
# of grip dots.
HOST_SHEET = '''
QDockWidget::title {
    background: {RAISED};
    padding: 3px 6px;
}
'''


def readable_on(value, background, least=4.0):
    """A color moved toward the text color until it reads on a background.

    Layer colors are dimmed for values that come from elsewhere, which is
    made for the editor's own dark panels. On a host's panel the dimmed
    color can all but vanish.

    :param value: the color to keep as much of as can be
    :param background: what it is drawn on
    :param least: the contrast ratio to reach
    :rtype: QtGui.QColor
    """
    result = QtGui.QColor(value)
    for step in range(1, 11):
        if contrast(result, background) >= least:
            break
        result = mix(value, TEXT, step / 10.0)
    return result


_unread_sheets = []


def extra_stylesheet():
    """A stylesheet of the user's or the studio's own, laid over the
    look: the file NXT_EDITOR_STYLESHEET names, or the one in the
    preferences. It can use the theme's names, as {BASE} or {TEXT}.

    :return: the sheet, or an empty string when there is none to read
    :rtype: str
    """
    path = os.environ.get(STYLESHEET_ENV_VAR, '').strip()
    if not path:
        try:
            from nxt_editor import user_dir
            path = (user_dir.user_prefs.get(STYLESHEET_PREF, '') or '')
        except Exception:
            path = ''
    path = os.path.expandvars(os.path.expanduser(path.strip()))
    if not path:
        return ''
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return fill(handle.read())
    except (IOError, OSError, UnicodeDecodeError) as error:
        if path not in _unread_sheets:
            # Once: the sheet is asked for by every window and dialog.
            _unread_sheets.append(path)
            import logging
            logging.getLogger(__name__).warning(
                'The stylesheet {} was not used: {}'.format(path, error))
        return ''


def stored_look():
    """The look asked for: NXT_EDITOR_LOOK when it names one, which is how
    a pipeline sets it for everyone, then the user's preference.

    :rtype: str
    """
    known = [look for look, _label in LOOK_NAMES]
    asked = os.environ.get(LOOK_ENV_VAR, '').strip().lower()
    if asked in known:
        return asked
    try:
        from nxt_editor import user_dir
        asked = user_dir.user_prefs.get(LOOK_PREF, LOOK_MODERN)
    except Exception:
        # Read while the editor is still loading. Never the reason it
        # does not open.
        asked = LOOK_MODERN
    if isinstance(asked, str):
        asked = asked.strip().lower()
    return asked if asked in known else LOOK_MODERN


def use_look(look):
    """Lay a look's values over the names above.

    Over the modern values: take_stored_look puts those back first. A
    module that keeps values made from these names keeps them up to date
    with follow_look.
    """
    values = {}
    host = ''
    if look == LOOK_CLASSIC:
        values = dict(CLASSIC)
    elif look == LOOK_HOST:
        host = running_host()
        values = dict(HOST_LOOKS.get(host, {}))
        if not values:
            values = host_colors()
            if values:
                values['HOST_DRAWS'] = 1
        if not values:
            # Said once, so the preference is not a riddle.
            import logging
            logging.getLogger(__name__).info(
                'The Host application look is for the editor in Maya, '
                'Blender or Unreal. Using Modern.')
            look, host = LOOK_MODERN, ''
    # Inputs, buttons and menus are what they are in modern, the field and
    # the raised colors, unless the look says otherwise.
    if 'GRAPH' in values:
        values.setdefault('INPUT', values['GRAPH'])
    if 'RAISED' in values:
        values.setdefault('BUTTON', values['RAISED'])
        values.setdefault('MENU', values['RAISED'])
    values.setdefault('HOST_DRAWS', 0)
    values.setdefault('HOST_FAMILY', '')
    globals().update(values)
    globals()['LOOK'] = look
    globals()['HOST'] = host


# Functions that rebuild values kept from the names above, by modules that
# keep any: run once as they are registered, and again on a change of look.
_look_followers = []


def follow_look(rebuild):
    """Keep a module's values made from the look up to date.

    :param rebuild: a function of no arguments that makes them again
    :return: the function, so this can be used as a decorator
    """
    _look_followers.append(rebuild)
    rebuild()
    return rebuild


def take_stored_look():
    """Put the look the preferences ask for in place, if it is not there.

    Each new editor window calls this before it builds anything, so a look
    chosen in Preferences shows in the next editor without a restart of its
    host. The window that is already open keeps the look it was built in.

    :return: True when the look changed
    :rtype: bool
    """
    look = stored_look()
    host = running_host() if look == LOOK_HOST else ''
    if (look, host) == (LOOK, HOST) or (look, host) == _last_asked[0]:
        return False
    _last_asked[0] = (look, host)
    before = (LOOK, HOST, BASE, NODE_MONO)
    # Every look is laid over the modern one, so start from it again.
    globals().update(_MODERN)
    use_look(look)
    for rebuild in _look_followers:
        rebuild()
    return (LOOK, HOST, BASE, NODE_MONO) != before


# The modern look's values, put back before another look is laid over them.
_MODERN = dict((name, value) for name, value in globals().items()
               if name.isupper() and isinstance(value, (str, int, float)))
use_look(stored_look())
# What was last asked for. The host look falls back to modern where there
# is no host, and asking again would only find the same.
_last_asked = [(stored_look(), running_host() if stored_look() == LOOK_HOST
                else '')]
