"""How layer and backdrop colors are shown to a user: a view preference.

It only changes how colors look to the user who sets it. The color a layer
or backdrop is given is chosen in Change Color, and is the same whatever
anyone's view.

Raw, the default, shows every color exactly as it is. White-text safe
shows a color darker, keeping its hue, when it is too light for the white
names on it to read at 4.5:1. Even shows every color at one OKLCH lightness
and chroma the user sets, keeping its hue, so no layer stands out from
another; white text may read less well.

Colors are never rewritten for the range. A layer's or backdrop's stored
color is shown through it, so changing the range, or going back to the
default, loses nothing, and a teammate on another range sees the same file
in theirs. View > Options > Layer Color View sets it, see color_range_dialog.
"""
# External
from Qt import QtGui

# Internal
from nxt_editor import theme, user_dir

RAW = 'raw'
SAFE = 'white_text_safe'
EVEN = 'even'
MODES = (RAW, SAFE, EVEN)
DEFAULT = RAW
DEFAULT_LIGHTNESS = 0.65
DEFAULT_CHROMA = 0.15
LIGHTNESS_RANGE = (0.40, 0.80)
CHROMA_RANGE = (0.0, 0.20)
# A color less colorful than this is a grey, and stays one in Even.
GREY_CHROMA = 0.02
# Hues looked at to find the one white text reads worst on.
CHECK_HUES = [i * 10.0 for i in range(36)]

_current = {}


def _load():
    if not _current:
        prefs = user_dir.user_prefs
        mode = prefs.get(user_dir.USER_PREF.COLOR_RANGE_MODE, DEFAULT)
        _current.update(
            mode=mode if mode in MODES else DEFAULT,
            lightness=float(prefs.get(
                user_dir.USER_PREF.COLOR_RANGE_LIGHTNESS, DEFAULT_LIGHTNESS)),
            chroma=float(prefs.get(
                user_dir.USER_PREF.COLOR_RANGE_CHROMA, DEFAULT_CHROMA)))
    return _current


def settings():
    """The range shown: (mode, lightness, chroma).

    :rtype: (str, float, float)
    """
    current = _load()
    return current['mode'], current['lightness'], current['chroma']


def mode():
    return settings()[0]


def set_settings(mode_, lightness, chroma, save=True):
    """Show colors in a range from now on, and remember it unless save is
    False, as while it is tried out in its dialog."""
    current = _load()
    current.update(mode=mode_, lightness=float(lightness),
                   chroma=float(chroma))
    if save:
        prefs = user_dir.user_prefs
        prefs[user_dir.USER_PREF.COLOR_RANGE_MODE] = mode_
        prefs[user_dir.USER_PREF.COLOR_RANGE_LIGHTNESS] = float(lightness)
        prefs[user_dir.USER_PREF.COLOR_RANGE_CHROMA] = float(chroma)


def forget():
    """Read the range from the preferences again next time."""
    _current.clear()


def even_color(value, lightness, chroma):
    """value at a lightness and chroma, keeping its hue. A grey stays grey.

    :rtype: QtGui.QColor
    """
    _, value_chroma, hue = theme.to_oklch(value)
    if value_chroma < GREY_CHROMA:
        chroma = 0.0
    return theme.from_oklch(lightness, chroma, hue)


def shown(value):
    """How a stored layer or backdrop color is shown, in the range.

    :rtype: QtGui.QColor
    """
    mode_, lightness, chroma = settings()
    if mode_ == EVEN:
        return even_color(value, lightness, chroma)
    if mode_ == SAFE:
        return theme.white_text_safe(value)
    return QtGui.QColor(value)


def worst_contrast(lightness, chroma):
    """The contrast of white text on the hue it reads worst on, at a
    lightness and chroma, and that hue.

    :rtype: (float, float)
    """
    worst = None
    for hue in CHECK_HUES:
        color = theme.from_oklch(lightness, chroma, hue)
        ratio = theme.contrast(color, theme.NODE_TEXT)
        if worst is None or ratio < worst[0]:
            worst = (ratio, hue)
    return worst


def readable_limit(chroma, target=4.5):
    """The highest lightness at which white text reads at target on every
    hue, at a chroma.

    :rtype: float
    """
    low, high = 0.0, 1.0
    for _ in range(18):
        middle = (low + high) / 2.0
        if worst_contrast(middle, chroma)[0] >= target:
            low = middle
        else:
            high = middle
    return low


def hue_name(hue):
    """A plain name for a hue in degrees, for the contrast readout."""
    names = ((20, 'pink'), (45, 'red'), (70, 'orange'), (100, 'yellow'),
             (150, 'green'), (200, 'teal'), (250, 'blue'), (300, 'purple'),
             (345, 'magenta'), (361, 'pink'))
    hue = hue % 360.0
    for limit, name in names:
        if hue < limit:
            return name
    return 'red'
