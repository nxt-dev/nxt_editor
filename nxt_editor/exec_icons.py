"""Icons for running part of a graph, drawn rather than shipped as images.

Each is the play triangle of Execute Graph, with what it runs beside it:
one node for the selected nodes, a parent and its children for a
hierarchy, and a node with an arrow down for running on from it. Grey, with
the triangle going green under the mouse, as Execute Graph's does.
"""
# External
from Qt import QtCore, QtGui

GREY = '#a09e9e'
GREEN = '#49cc54'
NODE = '#c8c6c6'
# The size the toolbar's other icons are drawn at, and how many times over
# to draw them, so they are sharp on a high DPI screen too.
SIZE = QtCore.QSize(17, 16)
SCALE = 4


def _play(painter, color):
    painter.setBrush(QtGui.QColor(color))
    painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(0.5, 2.5),
                                         QtCore.QPointF(7.5, 8.0),
                                         QtCore.QPointF(0.5, 13.5)]))


def _node(painter, x, y, w=7.0, h=3.4):
    painter.setBrush(QtGui.QColor(NODE))
    painter.drawRoundedRect(QtCore.QRectF(x, y, w, h), 1.0, 1.0)


def _selected(painter):
    _node(painter, 9.0, 6.0, 7.5, 4.0)


def _hierarchy(painter):
    _node(painter, 9.0, 2.0, 7.5, 3.2)
    _node(painter, 11.0, 6.6, 5.5, 3.0)
    _node(painter, 11.0, 10.8, 5.5, 3.0)
    # The line down from the parent to its children.
    painter.setPen(QtGui.QPen(QtGui.QColor(NODE), 0.8))
    painter.drawLine(QtCore.QPointF(9.8, 5.2), QtCore.QPointF(9.8, 12.3))
    painter.drawLine(QtCore.QPointF(9.8, 8.1), QtCore.QPointF(11.0, 8.1))
    painter.drawLine(QtCore.QPointF(9.8, 12.3), QtCore.QPointF(11.0, 12.3))
    painter.setPen(QtCore.Qt.NoPen)


def _from(painter):
    _node(painter, 9.0, 1.5, 7.5, 3.6)
    # An arrow down, from the node on through what follows it.
    painter.setPen(QtGui.QPen(QtGui.QColor(NODE), 1.4))
    painter.drawLine(QtCore.QPointF(12.75, 5.8), QtCore.QPointF(12.75, 11.0))
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QColor(NODE))
    painter.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(9.8, 10.2),
                                         QtCore.QPointF(15.7, 10.2),
                                         QtCore.QPointF(12.75, 14.5)]))


def _pixmap(draw, play_color):
    pixmap = QtGui.QPixmap(SIZE * SCALE)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.scale(SCALE, SCALE)
    painter.setPen(QtCore.Qt.NoPen)
    _play(painter, play_color)
    draw(painter)
    painter.end()
    return pixmap


def _icon(draw):
    icon = QtGui.QIcon()
    icon.addPixmap(_pixmap(draw, GREY), QtGui.QIcon.Normal, QtGui.QIcon.Off)
    icon.addPixmap(_pixmap(draw, GREEN), QtGui.QIcon.Active, QtGui.QIcon.Off)
    return icon


def execute_selected():
    """Play, and one node.

    :rtype: QtGui.QIcon
    """
    return _icon(_selected)


def execute_hierarchy():
    """Play, and a parent with its children.

    :rtype: QtGui.QIcon
    """
    return _icon(_hierarchy)


def execute_from():
    """Play, and a node with an arrow on down from it.

    :rtype: QtGui.QIcon
    """
    return _icon(_from)
