# Builtin
import logging
# External
from Qt.QtGui import QColor
# Internal
from nxt.nxt_log import GRAPHERROR, NODEOUT, EXECINFO, COMPINFO
from nxt_editor import theme

ATTR_COLORS = {
    'None': QColor('#808080'),
    'raw': QColor('#e2e2e2'),
    'bool': QColor('#FF0000'),
    'str': QColor('#e598e9'),
    'float': QColor('#9cf944'),
    'int': QColor('#578233'),
    'list': QColor('#ebae1f'),
    'tuple': QColor('#eb891f'),
    'dict': QColor('#984dab'),
}

GRAPH_BG_COLOR = QColor(theme.GRAPH)
START_COLOR = QColor("#1bd40b")
SKIP_COLOR = QColor("#f0880a")
BREAK_COLOR = QColor(255, 0, 0)

# Layer colors: hues spread evenly around the circle, in OKLCH so the steps
# look even, each made dark enough for white text (theme.white_text_safe),
# and a grey. Ordered so each layer added gets a hue well away from the one
# before it.
LAYER_HUE_COUNT = 15
LAYER_FIRST_HUE = 25.0
LAYER_COLORS = [
    theme.white_text_safe(theme.from_oklch(
        theme.PALETTE_LIGHTNESS, theme.PALETTE_CHROMA,
        LAYER_FIRST_HUE + (i * 7 % LAYER_HUE_COUNT) * 360.0 / LAYER_HUE_COUNT))
    for i in range(LAYER_HUE_COUNT)
] + [theme.white_text_safe(theme.from_oklch(theme.PALETTE_LIGHTNESS, 0.0,
                                            0.0))]

SELECTED = QColor(theme.SELECTED)

UNCACHED_RED = QColor(255, 0, 0, 200)

UNSAVED = QColor(200, 160, 26, 80)

ERROR = QColor(204, 0, 0, 50)

IMPORTANT = QColor(223, 223, 22, 200)

DEFAULT_TEXT = QColor(113, 113, 113)

LIGHTER_TEXT = QColor(130, 135, 141)

LIGHTEST_TEXT = QColor(183, 180, 177)


LOGGING_COLORS = {
    GRAPHERROR: '#ea4f39',  # Deep Orange
    NODEOUT: 'light gray',
    EXECINFO: '#039be5',  # Pale blue
    COMPINFO: 'light blue',
    logging.DEBUG: 'white',
    logging.INFO: 'green',
    logging.WARNING: 'orange',
    logging.ERROR: 'red',
    logging.CRITICAL: 'purple',
}

