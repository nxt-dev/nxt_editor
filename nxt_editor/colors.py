# Builtin
import logging
# External
from Qt.QtGui import QColor
# Internal
from nxt.nxt_log import GRAPHERROR, NODEOUT, EXECINFO, COMPINFO

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

GRAPH_BG_COLOR = QColor(35, 35, 35)
START_COLOR = QColor("#1bd40b")
SKIP_COLOR = QColor("#f0880a")
BREAK_COLOR = QColor(255, 0, 0)

LAYER_COLORS = [
    QColor('#991C24'),  # dark red
    QColor('#C91781'),  # fuschia
    QColor('#0052AA'),  # blue
    QColor('#E83723'),  # tangerine
    QColor('#6E33BB'),  # purple
    QColor('#01697F'),  # dark teal
    QColor('#51B848'),  # green
    QColor('#00A5E6'),  # light blue
    QColor('#99CC33'),  # lime
    QColor('#F38B00'),  # light orange
    QColor('#5633BB'),  # dark purple
    QColor('#CFA305'),  # yellow
    QColor('#BE0000'),  # red
    QColor('#AF30D8'),  # violet
    QColor('#787878'),  # grey
    QColor('#119B77')   # teal
]

SELECTED = QColor(232, 229, 54, 255)

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

