"""Icons for lining up nodes and selecting them, drawn rather than shipped
as images, so they are sharp on a high DPI screen.

Grey, with the parts that move going blue under the mouse, as the toolbar's
other icons do.
"""
# External
from Qt import QtCore, QtGui

from nxt_editor import align

GREY = '#a09e9e'
BLUE = '#39aae0'
NODE = '#c8c6c6'
# The size the toolbar's other icons are drawn at, and how many times over
# to draw them.
SIZE = QtCore.QSize(17, 16)
SCALE = 4


def _bar(painter, color, x, y, w, h):
    painter.setBrush(QtGui.QColor(color))
    painter.drawRect(QtCore.QRectF(x, y, w, h))


def _align(edge):
    """Two bars of different lengths lined up on a line."""
    def draw(painter, color):
        # Drawn as left, top or their middles, then turned for the others.
        across = edge in (align.LEFT, align.HCENTER, align.RIGHT)
        if not across:
            painter.translate(SIZE.width(), 0)
            painter.rotate(90)
            painter.scale(16.0 / 17.0, 17.0 / 16.0)
        if edge in (align.RIGHT, align.BOTTOM):
            painter.translate(SIZE.width(), 0)
            painter.scale(-1, 1)
        middle = edge in (align.HCENTER, align.VCENTER)
        if middle:
            _bar(painter, GREY, 7.75, 0.5, 1.5, 15.0)
            _bar(painter, color, 3.5, 2.5, 10.0, 4.0)
            _bar(painter, color, 1.5, 9.5, 14.0, 4.0)
        else:
            _bar(painter, GREY, 0.5, 0.5, 1.5, 15.0)
            _bar(painter, color, 3.0, 2.5, 8.0, 4.0)
            _bar(painter, color, 3.0, 9.5, 13.0, 4.0)
    return draw


def _distribute(axis):
    """Three bars with the same gap between them."""
    def draw(painter, color):
        if axis == align.VERTICAL:
            painter.translate(SIZE.width(), 0)
            painter.rotate(90)
            painter.scale(16.0 / 17.0, 17.0 / 16.0)
        _bar(painter, GREY, 0.5, 2.0, 3.5, 12.0)
        _bar(painter, color, 6.75, 4.0, 3.5, 8.0)
        _bar(painter, GREY, 13.0, 2.0, 3.5, 12.0)
    return draw


def _select_all(painter, color):
    """Two nodes in a dashed box."""
    pen = QtGui.QPen(QtGui.QColor(color), 1.0, QtCore.Qt.DashLine)
    pen.setDashPattern([2.0, 1.5])
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.drawRect(QtCore.QRectF(0.5, 0.5, 16.0, 15.0))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QColor(NODE))
    painter.drawRoundedRect(QtCore.QRectF(2.5, 3.0, 7.0, 4.0), 1.0, 1.0)
    painter.drawRoundedRect(QtCore.QRectF(7.5, 9.0, 7.0, 4.0), 1.0, 1.0)


def _pixmap(draw, color):
    pixmap = QtGui.QPixmap(SIZE * SCALE)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.scale(SCALE, SCALE)
    painter.setPen(QtCore.Qt.NoPen)
    draw(painter, color)
    painter.end()
    return pixmap


def _icon(draw):
    icon = QtGui.QIcon()
    icon.addPixmap(_pixmap(draw, GREY), QtGui.QIcon.Normal, QtGui.QIcon.Off)
    icon.addPixmap(_pixmap(draw, BLUE), QtGui.QIcon.Active, QtGui.QIcon.Off)
    return icon


def align_icon(edge):
    """:param edge: one of nxt_editor.align.EDGES
    :rtype: QtGui.QIcon
    """
    return _icon(_align(edge))


def distribute_icon(axis):
    """:param axis: nxt_editor.align.HORIZONTAL or VERTICAL
    :rtype: QtGui.QIcon
    """
    return _icon(_distribute(axis))


def select_all_icon():
    """:rtype: QtGui.QIcon"""
    return _icon(_select_all)
