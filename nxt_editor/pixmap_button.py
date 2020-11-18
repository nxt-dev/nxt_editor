# External
from Qt import QtWidgets
from Qt import QtGui
from Qt import QtCore


class PixmapButton(QtWidgets.QAbstractButton):
    """https://stackoverflow.com/questions/2711033/how-code-a-image-button-in-pyqt"""
    def __init__(self, pixmap, pixmap_hover, pixmap_pressed, pixmap_checked=None,
                 pixmap_checked_hover=None, pixmap_checked_pressed=None, size=32, checkable=False,
                 parent=None):
        super(PixmapButton, self).__init__(parent=parent)
        self.pixmap = pixmap
        self.pixmap_hover = pixmap_hover
        self.pixmap_pressed = pixmap_pressed
        self.pixmap_checked = pixmap_checked
        self.pixmap_checked_hover = pixmap_checked_hover
        self.pixmap_checked_pressed = pixmap_checked_pressed
        self.size = size

        if checkable:
            self.setCheckable(checkable)

        self.pressed.connect(self.update)
        self.released.connect(self.update)

        self.action = None

    def set_action(self, action):
        self.action = action

        # get properties
        self.setToolTip(self.action.toolTip())
        self.setWhatsThis(self.action.whatsThis())

        # connect signals
        action.triggered.connect(self.update_state)
        action.toggled.connect(self.update_state)
        if action.isCheckable():
            self.toggled.connect(action.toggle)
        else:
            self.clicked.connect(action.trigger)

    def update_state(self):
        if self.action:
            self.blockSignals(True)
            self.setChecked(self.action.isChecked())
            self.blockSignals(False)

    def paintEvent(self, event):
        if not isinstance(event, QtGui.QPaintEvent):
            return
        if self.isChecked():
            pix = self.pixmap_checked_hover if self.underMouse() else self.pixmap_checked
            if self.isDown():
                pix = self.pixmap_checked_pressed
        else:
            pix = self.pixmap_hover if self.underMouse() else self.pixmap
            if self.isDown():
                pix = self.pixmap_pressed

        painter = QtGui.QPainter(self)
        painter.drawPixmap(event.rect(), pix)
        del painter

    def enterEvent(self, event):
        self.update()

    def leaveEvent(self, event):
        self.update()

    def sizeHint(self):
        return QtCore.QSize(self.size, self.size)