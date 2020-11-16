# External
from Qt import QtWidgets, QtGui, QtCore


class OpinionDots(QtWidgets.QWidget):
    SIZE = 4
    WIDGET_SIZE = SIZE * 2.5

    def __init__(self, parent, name, vertical=False):
        super(OpinionDots, self).__init__(parent=parent)
        self._layer_colors = []
        self.setObjectName(name)
        self.vertical = vertical

    @property
    def layer_colors(self):
        return self._layer_colors

    @layer_colors.setter
    def layer_colors(self, color_list):
        self._layer_colors = color_list
        layer_count = len(color_list)
        if self.vertical:
            self.setFixedHeight(self.WIDGET_SIZE * layer_count)
            self.setFixedWidth(self.WIDGET_SIZE)
        else:
            self.setFixedHeight(self.WIDGET_SIZE)
            self.setFixedWidth(self.WIDGET_SIZE * layer_count)

    def paintEvent(self, event):
        painter = QtGui.QPainter()
        painter.begin(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        if self.vertical:
            x_pos = self.rect().center().x()
            y_pos = self.rect().top() + self.SIZE
        else:
            x_pos = self.rect().right() - self.SIZE
            y_pos = self.rect().center().y()
        for c in self.layer_colors:
            color = QtGui.QColor(c)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(color))
            point = QtCore.QPointF(x_pos, y_pos)
            painter.drawEllipse(point, self.SIZE, self.SIZE)
            if self.vertical:
                y_pos += (self.SIZE * 2.5)
            else:
                x_pos -= (self.SIZE * 2.5)
        painter.end()
