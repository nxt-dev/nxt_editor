"""Options > Optional Components: install the extras the editor can use.

One card per component, saying whether it is there and offering the one
thing that makes sense to do next: Install, Update or Remove. pip runs in a
QProcess, so the editor, and the host it is in, never stop while it
downloads. What goes where, and why, is in integration/optional_deps.py,
which also works before there is any Qt, for the hosts' own menus.

PySide6 can not be installed from here where it matters: in Blender and
Unreal there is no Qt to show this dialog until it is installed, so their
nxt menus install it. Here it is shown, and updated, once it is in use.

Everything is drawn in the editor's own colors and fonts, so it looks the
same standalone and in every host.
"""
# Builtin
import logging
import os
import sys

# External
from Qt import QtCore, QtGui, QtWidgets

# Internal
import nxt_editor
from nxt_editor import theme
from nxt_editor.integration import optional_deps as deps

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

GOOD = '#49cc54'
WARN = '#e3a52d'
BAD = '#e0564c'
#: Between the parts of a line of small print.
SEPARATOR = '&nbsp;&nbsp;\u00b7&nbsp;&nbsp;'

HOST_NAMES = {'maya': 'Maya', 'blender': 'Blender', 'unreal': 'Unreal',
              'houdini': 'Houdini', 'motionbuilder': 'MotionBuilder',
              '3dsmax': '3ds Max', 'standalone': 'nxt'}

STYLE = """
QDialog#optionalComponents { background-color: {BASE}; }
QLabel { background: transparent; }
QLabel#title { color: {TEXT}; }
QLabel#dim { color: {TEXT_DIM}; }
QLabel#faint { color: {TEXT_FAINT}; }
QLabel#error { color: #e07070; }
QFrame#card {
    background-color: {RAISED};
    border: 1px solid {BORDER};
    border-radius: 8px;
}
QFrame#card[focused="true"] { border: 1px solid {ACCENT}; }
QFrame#card QWidget#cardPart { background: transparent; }
QFrame#note {
    background-color: transparent;
    border: 1px solid {BORDER};
    border-radius: {RADIUS}px;
}
QPushButton#primary {
    background-color: {ACCENT_STRONG};
    border: 1px solid {ACCENT};
    color: {TEXT};
    min-width: 68px;
}
QPushButton#primary:hover { background-color: {PRESSED}; }
QPushButton#primary:pressed { background-color: {ACCENT_DIM}; }
QPushButton#secondary {
    background-color: {HOVER};
    border: 1px solid {BORDER_STRONG};
    min-width: 68px;
}
QPushButton#secondary:hover { background-color: {PRESSED}; }
QPlainTextEdit#log {
    background-color: {GRAPH};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT_DIM};
    padding: 2px;
}
QPlainTextEdit#log QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 2px;
    border: none;
}
QPlainTextEdit#log QScrollBar::handle:vertical {
    background-color: {BORDER_STRONG};
    border-radius: 3px;
    min-height: 24px;
}
QPlainTextEdit#log QScrollBar::handle:vertical:hover {
    background-color: {TEXT_FAINT};
}
QPlainTextEdit#log QScrollBar::add-line:vertical,
QPlainTextEdit#log QScrollBar::sub-line:vertical {
    height: 0;
    border: none;
    background: none;
}
QPlainTextEdit#log QScrollBar::add-page:vertical,
QPlainTextEdit#log QScrollBar::sub-page:vertical {
    background: none;
}
"""


def host_name(host=None):
    host = host or deps.current_host()
    return HOST_NAMES.get(host, host.capitalize())


def host_python(host=None):
    """'Maya's Python', or 'the Python nxt runs in' standalone."""
    host = host or deps.current_host()
    if host == 'standalone':
        return 'the Python nxt runs in'
    return "{}'s Python".format(host_name(host))


def short_path(path):
    """A path with the home folder as ~, which is shorter and says the same."""
    if not path:
        return ''
    home = os.path.expanduser('~')
    full = os.path.normpath(path)
    if os.path.normcase(full).startswith(os.path.normcase(home) + os.sep):
        return '~' + full[len(home):]
    return full


def open_folder(path):
    """Show a folder, or the nearest one above it that exists."""
    path = os.path.abspath(path)
    while path and not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            return False
        path = parent
    return QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))


def forget_modules(names):
    """Drop modules from sys.modules, so the next import finds the version
    on disk now rather than the one loaded before.
    """
    names = set(names)
    for key in list(sys.modules):
        if key.split('.')[0] in names:
            del sys.modules[key]


# -- drawn pieces -------------------------------------------------------------

class Pill(QtWidgets.QWidget):
    """A component's status: a dot in its color and a word or two."""

    def __init__(self, parent=None):
        super(Pill, self).__init__(parent)
        self.text = ''
        self.color = None
        self.setFont(theme.font(theme.SMALL_PX, QtGui.QFont.Medium))
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed,
                           QtWidgets.QSizePolicy.Fixed)

    def set(self, text, color=None):
        self.text = text
        self.color = color
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        width = QtGui.QFontMetrics(self.font()).horizontalAdvance(self.text)
        dot = 12 if self.color else 0
        return QtCore.QSize(width + dot + 18, 20)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self.color:
            fill = theme.color(self.color, 0.14)
            edge = theme.color(self.color, 0.40)
            ink = theme.mix(self.color, theme.TEXT, 0.35)
        else:
            fill = theme.color(theme.HOVER)
            edge = theme.color(theme.BORDER_STRONG)
            ink = theme.color(theme.TEXT_DIM)
        painter.setPen(QtGui.QPen(edge, 1))
        painter.setBrush(fill)
        radius = rect.height() / 2.0
        painter.drawRoundedRect(rect, radius, radius)
        x = rect.left() + 9
        if self.color:
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(theme.color(self.color))
            painter.drawEllipse(QtCore.QPointF(x + 3, rect.center().y()),
                                3, 3)
            x += 12
        painter.setPen(ink)
        painter.setFont(self.font())
        painter.drawText(QtCore.QRectF(x, rect.top(), rect.right() - x,
                                       rect.height()),
                         QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                         self.text)


class Glyph(QtWidgets.QWidget):
    """A component's picture: a completion list for jedi, a window for Qt."""

    def __init__(self, kind, parent=None):
        super(Glyph, self).__init__(parent)
        self.kind = kind
        self.dim = False
        self.setFixedSize(40, 40)

    def set_dim(self, dim):
        self.dim = dim
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        tile = QtCore.QRectF(0.5, 0.5, 39, 39)
        painter.setPen(QtGui.QPen(theme.color(theme.BORDER_STRONG), 1))
        painter.setBrush(theme.color(theme.BASE))
        painter.drawRoundedRect(tile, 8, 8)
        ink = theme.color(theme.TEXT_FAINT if self.dim else theme.TEXT_DIM)
        strong = theme.color(theme.TEXT_FAINT if self.dim else theme.TEXT)
        pen = QtGui.QPen(ink, 1.6)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        if self.kind == deps.PYSIDE6.id:
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(QtCore.QRectF(9, 11, 22, 18), 3, 3)
            painter.drawLine(QtCore.QPointF(9, 16.5), QtCore.QPointF(31, 16.5))
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(strong)
            for x in (12.5, 15.5, 18.5):
                painter.drawEllipse(QtCore.QPointF(x, 13.8), 1, 1)
            return
        # A name and a dot, then a list of what can follow it, one picked.
        painter.setPen(strong)
        painter.setFont(theme.font(10, QtGui.QFont.DemiBold, mono=True))
        painter.drawText(QtCore.QRectF(9, 4.5, 26, 12),
                         QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, 'os.')
        painter.setPen(QtGui.QPen(ink, 1))
        painter.setBrush(QtCore.Qt.NoBrush)
        listing = QtCore.QRectF(12, 16, 19, 16)
        painter.drawRoundedRect(listing, 2.5, 2.5)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(theme.color(theme.ACCENT_STRONG if not self.dim
                                     else theme.BORDER_STRONG))
        painter.drawRect(QtCore.QRectF(12.5, 21, 18, 5))
        painter.setPen(pen)
        for y, end in ((18.8, 25), (23.5, 28), (28.8, 22)):
            painter.drawLine(QtCore.QPointF(15, y), QtCore.QPointF(end, y))


class ThinProgress(QtWidgets.QWidget):
    """A slim progress bar. None for a value means busy without knowing
    how far along, which is drawn as a sliding segment.
    """

    def __init__(self, parent=None):
        super(ThinProgress, self).__init__(parent)
        self.value = None
        self.phase = 0.0
        self.setFixedHeight(4)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._tick)

    def set_value(self, value):
        """0 to 1, or None when it is not known."""
        self.value = None if value is None else min(max(value, 0.0), 1.0)
        if self.value is None and self.isVisible():
            self.timer.start()
        elif self.value is not None:
            self.timer.stop()
        self.update()

    def showEvent(self, event):
        super(ThinProgress, self).showEvent(event)
        if self.value is None:
            self.timer.start()

    def hideEvent(self, event):
        super(ThinProgress, self).hideEvent(event)
        self.timer.stop()

    def _tick(self):
        self.phase = (self.phase + 0.018) % 1.0
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(self.rect())
        radius = rect.height() / 2.0
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(theme.color(theme.GRAPH))
        painter.drawRoundedRect(rect, radius, radius)
        painter.setBrush(theme.color(theme.ACCENT))
        if self.value is None:
            width = rect.width() * 0.28
            left = rect.left() - width + (rect.width() + width) * self.phase
            chunk = QtCore.QRectF(left, rect.top(), width, rect.height())
            painter.setClipRect(rect)
            painter.drawRoundedRect(chunk, radius, radius)
        elif self.value > 0:
            chunk = QtCore.QRectF(rect.left(), rect.top(),
                                  max(rect.width() * self.value,
                                      rect.height()), rect.height())
            painter.drawRoundedRect(chunk, radius, radius)


class Disclosure(QtWidgets.QAbstractButton):
    """'Details' with a chevron that turns when it is open."""

    def __init__(self, text, parent=None):
        super(Disclosure, self).__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFont(theme.font(theme.SMALL_PX))
        self.setAttribute(QtCore.Qt.WA_Hover)

    def sizeHint(self):
        width = QtGui.QFontMetrics(self.font()).horizontalAdvance(self.text())
        return QtCore.QSize(width + 18, 18)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        hovered = self.underMouse()
        ink = theme.color(theme.TEXT if hovered else theme.TEXT_DIM)
        pen = QtGui.QPen(ink, 1.4)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        cy = self.height() / 2.0
        if self.isChecked():
            points = [QtCore.QPointF(2, cy - 2), QtCore.QPointF(5.5, cy + 1.5),
                      QtCore.QPointF(9, cy - 2)]
        else:
            points = [QtCore.QPointF(4, cy - 3.5), QtCore.QPointF(7.5, cy),
                      QtCore.QPointF(4, cy + 3.5)]
        painter.drawPolyline(QtGui.QPolygonF(points))
        painter.setFont(self.font())
        painter.drawText(QtCore.QRectF(16, 0, self.width() - 16,
                                       self.height()),
                         QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                         self.text())


def label(text='', role=None, px=None, weight=None, wrap=False):
    widget = QtWidgets.QLabel(text)
    if role:
        widget.setObjectName(role)
    if px or weight is not None:
        widget.setFont(theme.font(px or theme.TEXT_PX, weight))
    widget.setWordWrap(wrap)
    return widget


# -- installing ---------------------------------------------------------------

class InstallJob(QtCore.QObject):
    """pip installing one component, in a QProcess, and putting it in place.

    The QProcess can be swapped for a stand in through process_factory,
    which is how the tests run it without pip.
    """
    #: a line pip printed
    line = QtCore.Signal(str)
    #: what it is doing, in a few words
    step = QtCore.Signal(str)
    #: bytes done and the total, for the file downloading now
    progress = QtCore.Signal(int, int)
    #: whether it worked, and 'installed', 'restart' or why it did not
    finished = QtCore.Signal(bool, str)

    def __init__(self, component, crt=None, process_factory=None,
                 parent=None):
        super(InstallJob, self).__init__(parent)
        self.component = component
        self.crt = crt
        self.process_factory = process_factory or QtCore.QProcess
        self.process = None
        self.staging = None
        self.output = []
        self._partial = ''
        self._progress = True
        self.cancelled = False
        self.running = False

    def start(self):
        self.running = True
        self.cancelled = False
        try:
            self.staging = deps.new_staging(self.component)
        except OSError as error:
            self._finish(False, "Couldn't make a folder in {}: {}".format(
                short_path(deps.install_root()), error))
            return
        if deps.python_executable() is None:
            self._finish(False, "Couldn't find this application's Python "
                                "interpreter to run pip with.")
            return
        self._run(progress=True)

    def _run(self, progress):
        self._progress = progress
        self.output = []
        self._partial = ''
        cmd = deps.install_command(self.component, self.staging, self.crt,
                                   progress=progress)
        process = self.process_factory(self)
        self.process = process
        process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        env = QtCore.QProcessEnvironment()
        for key, value in deps.pip_environment().items():
            env.insert(key, value)
        process.setProcessEnvironment(env)
        process.readyReadStandardOutput.connect(self._read)
        process.finished.connect(self._done)
        process.errorOccurred.connect(self._error)
        self.step.emit('Starting')
        self.progress.emit(0, 0)
        self.line.emit('> ' + ' '.join(cmd))
        process.start(cmd[0], cmd[1:])

    def _read(self):
        data = bytes(self.process.readAllStandardOutput())
        text = self._partial + data.decode('utf-8', errors='replace')
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        lines = text.split('\n')
        self._partial = lines.pop()
        for each in lines:
            self._line(each)

    def _line(self, text):
        self.output.append(text)
        parsed = deps.parse_line(text)
        if parsed is None:
            if text.strip():
                self.line.emit(text)
            return
        if parsed[0] == 'progress':
            # Too many to be worth reading, so they stay out of the log.
            self.progress.emit(parsed[1], parsed[2])
            return
        self.line.emit(text)
        self.step.emit(parsed[1])
        self.progress.emit(0, 0)

    def _error(self, error):
        if error == QtCore.QProcess.FailedToStart and not self.cancelled:
            self._finish(False, "Couldn't start pip: {}".format(
                self.process.errorString()))

    def _done(self, code, status=None):
        if not self.running:
            return
        if self._partial:
            self._line(self._partial)
            self._partial = ''
        if self.cancelled:
            self._finish(False, 'Cancelled.')
            return
        output = '\n'.join(self.output)
        if code != 0 and self._progress and deps.progress_unsupported(output):
            # pip before 24.1, which has no progress lines to give.
            self._run(progress=False)
            return
        if code != 0:
            self._finish(False, deps.explain_failure(output, self.component))
            return
        self.step.emit('Finishing')
        try:
            result = deps.finish_install(self.component, self.staging,
                                         self.crt)
        except Exception as error:
            self._finish(False, "Installed, but couldn't move it into "
                                "place: {}".format(error))
            return
        self._finish(True, result)

    def _finish(self, ok, message):
        self.running = False
        if self.staging and os.path.isdir(self.staging):
            deps.discard(self.staging)
        self.finished.emit(ok, message)

    def cancel(self):
        if not self.running:
            return
        self.cancelled = True
        if self.process is not None:
            self.process.kill()


# -- the dialog ---------------------------------------------------------------

class ComponentCard(QtWidgets.QFrame):
    """One component: what it is, whether it is there, and what to do."""
    install_requested = QtCore.Signal(object)
    remove_requested = QtCore.Signal(object)
    cancel_requested = QtCore.Signal(object)

    def __init__(self, component, host=None, parent=None):
        super(ComponentCard, self).__init__(parent)
        self.component = component
        self.host = host
        self.status = None
        self.action = None
        self.working = False
        self.setObjectName('card')
        self.setProperty('focused', False)
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(12)
        self.glyph = Glyph(component.id)
        outer.addWidget(self.glyph, 0, QtCore.Qt.AlignTop)
        body = QtWidgets.QVBoxLayout()
        body.setSpacing(4)
        outer.addLayout(body, 1)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(8)
        self.name_label = label(component.name, 'title', theme.TEXT_PX + 1,
                                QtGui.QFont.DemiBold)
        top.addWidget(self.name_label)
        self.pill = Pill()
        top.addWidget(self.pill, 0, QtCore.Qt.AlignVCenter)
        top.addStretch(1)
        self.button = QtWidgets.QPushButton()
        self.button.setCursor(QtCore.Qt.PointingHandCursor)
        self.button.clicked.connect(self.on_button)
        top.addWidget(self.button)
        body.addLayout(top)
        self.description = label(component.description, 'dim', wrap=True)
        body.addWidget(self.description)
        self.meta = label('', 'faint', theme.SMALL_PX)
        self.meta.setTextFormat(QtCore.Qt.RichText)
        self.meta.setWordWrap(True)
        body.addWidget(self.meta)
        self.where = label('', 'faint', theme.SMALL_PX)
        self.where.setTextFormat(QtCore.Qt.RichText)
        self.where.linkActivated.connect(self.on_link)
        body.addWidget(self.where)

        # Shown while installing, and after, until the next refresh.
        self.work = QtWidgets.QWidget()
        self.work.setObjectName('cardPart')
        work = QtWidgets.QVBoxLayout(self.work)
        work.setContentsMargins(0, 8, 0, 0)
        work.setSpacing(6)
        self.progress = ThinProgress()
        work.addWidget(self.progress)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        self.step_label = label('', 'dim', theme.SMALL_PX, wrap=True)
        row.addWidget(self.step_label, 1)
        self.details = Disclosure('Details')
        self.details.toggled.connect(self.on_details)
        row.addWidget(self.details, 0, QtCore.Qt.AlignTop)
        work.addLayout(row)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setObjectName('log')
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setFont(theme.font(theme.SMALL_PX, mono=True))
        self.log.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.log.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.log.setFixedHeight(132)
        self.log.hide()
        work.addWidget(self.log)
        body.addWidget(self.work)
        self.work.hide()

    # -- state -------------------------------------------------------------

    def host_name(self):
        return host_name(self.host)

    def set_status(self, status):
        self.status = status
        self.working = False
        self.progress.hide()
        state = status.state
        comp = self.component
        dim = state == deps.Status.NOT_NEEDED
        self.glyph.set_dim(dim)
        self.name_label.setObjectName('dim' if dim else 'title')
        self.description.setObjectName('faint' if dim else 'dim')
        for widget in (self.name_label, self.description):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        version = status.version or ''
        action = None
        description = comp.description
        if state == deps.Status.NOT_NEEDED:
            self.pill.set('Not needed here')
            if comp is deps.PYSIDE6:
                description = ('{} has its own Qt.'.format(self.host_name())
                               if self.host != 'standalone' else
                               'Already here: it comes with the nxt '
                               'install.')
        elif state == deps.Status.NOT_INSTALLED:
            self.pill.set('Not installed')
            if comp.compiled:
                description = ('{} Install it from the nxt menu in {}.'
                               .format(comp.description, self.host_name()))
            else:
                action = 'install'
        elif state == deps.Status.INSTALLED:
            self.pill.set('Installed {}'.format(version), GOOD)
            if not comp.compiled:
                action = 'remove'
        elif state == deps.Status.UPDATE:
            self.pill.set('Update available', WARN)
            action = 'update'
        elif state == deps.Status.MANAGED:
            self.pill.set('Managed by your studio')
        elif state == deps.Status.ELSEWHERE:
            self.pill.set('Installed {}'.format(version), GOOD)
        elif state == deps.Status.RESTART:
            self.pill.set('Restart to finish', WARN)
        self.description.setText(description)
        self.set_action(action)
        self.meta.setText(self.meta_text())
        self.meta.setVisible(bool(self.meta.text()))
        self.where.setText(self.where_text())
        self.where.setVisible(bool(self.where.text()))

    def meta_text(self):
        status = self.status
        parts = []
        if status.state == deps.Status.UPDATE and status.version:
            parts.append('Version {} is {} than this nxt works with'.format(
                status.version, 'older' if status.too_old else 'newer'))
        elif status.state == deps.Status.MANAGED and status.out_of_range:
            parts.append('Version {}, and nxt wants {}. Ask your studio to '
                         'update it'.format(
                             status.version,
                             deps.describe_range(status.wanted)))
        elif status.state == deps.Status.MANAGED:
            parts.append('Version {}'.format(status.version))
        elif status.state == deps.Status.RESTART:
            parts.append('Restart {} to finish updating'.format(
                self.host_name()))
        elif status.state == deps.Status.ELSEWHERE:
            parts.append('Comes with this Python')
        elif status.state not in (deps.Status.NOT_NEEDED,):
            parts.append(self.component.size)
        return SEPARATOR.join(html(p) for p in parts if p)

    def where_text(self):
        status = self.status
        folder = status.folder
        if not folder or status.state in (deps.Status.NOT_NEEDED,
                                          deps.Status.ELSEWHERE):
            return ''
        verb = ('Installs to' if status.state == deps.Status.NOT_INSTALLED
                else 'In')
        where = elide(short_path(folder), self.where, 330)
        return ('{} {}&nbsp;&nbsp;&nbsp;<a href="open" style="color:{}; '
                'text-decoration:none">Open folder</a>'.format(
                    verb, html(where), theme.TEXT_DIM))

    def set_action(self, action):
        self.action = action
        if action is None:
            self.button.hide()
            return
        text = {'install': 'Install', 'update': 'Update', 'remove': 'Remove',
                'retry': 'Retry', 'cancel': 'Cancel'}[action]
        self.button.setText(text)
        primary = action in ('install', 'update', 'retry')
        self.button.setObjectName('primary' if primary else 'secondary')
        self.button.style().unpolish(self.button)
        self.button.style().polish(self.button)
        self.button.setEnabled(True)
        self.button.show()

    def on_button(self):
        if self.action in ('install', 'update', 'retry'):
            self.install_requested.emit(self.component)
        elif self.action == 'remove':
            self.remove_requested.emit(self.component)
        elif self.action == 'cancel':
            self.button.setEnabled(False)
            self.cancel_requested.emit(self.component)

    def on_link(self, href):
        if self.status and self.status.folder:
            open_folder(self.status.folder)

    def on_details(self, shown):
        self.log.setVisible(shown)
        if shown:
            bar = self.log.verticalScrollBar()
            bar.setValue(bar.maximum())

    # -- installing ----------------------------------------------------------

    def start_work(self):
        self.working = True
        self.log.clear()
        self.work.show()
        self.progress.show()
        self.progress.set_value(None)
        self.step_label.setObjectName('dim')
        self.step_label.style().unpolish(self.step_label)
        self.step_label.style().polish(self.step_label)
        self.step_label.setText('Starting')
        self.pill.set('Installing')
        self.set_action('cancel')

    def add_line(self, text):
        self.log.appendPlainText(text)

    def set_step(self, text):
        self._step = text
        self.step_label.setText(text)

    def set_progress(self, done, total):
        if total <= 0:
            self.progress.set_value(None)
            return
        self.progress.set_value(done / float(total))
        step = getattr(self, '_step', '')
        self.step_label.setText('{}  \u00b7  {}%'.format(
            step, int(100 * done / float(total))))

    def end_work(self, ok, message):
        """Show how it went. A failure keeps the log, and offers to try
        again."""
        self.working = False
        self.progress.hide()
        self.step_label.setObjectName('dim' if ok else 'error')
        self.step_label.style().unpolish(self.step_label)
        self.step_label.style().polish(self.step_label)
        self.step_label.setText(message)
        if not ok:
            self.pill.set('Failed', BAD)
            self.set_action('retry')


def elide(text, widget, width):
    metrics = QtGui.QFontMetrics(widget.font())
    return metrics.elidedText(text, QtCore.Qt.ElideMiddle, width)


def html(text):
    return (text.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;'))


class OptionalComponentsDialog(QtWidgets.QDialog):
    """Options > Optional Components."""
    #: a component was installed, updated or removed, by its id
    changed = QtCore.Signal(str)

    def __init__(self, parent=None, host=None, crt=None, process_factory=None,
                 status_func=None):
        """
        :param host: the host to answer for, current_host() when None
        :param crt: the loaded C++ runtime, asked for when None
        :param process_factory: makes the QProcess pip runs in
        :param status_func: gives a component's Status, for the tests
        """
        super(OptionalComponentsDialog, self).__init__(parent)
        self.setObjectName('optionalComponents')
        self.setWindowTitle('Optional Components')
        self.host = host or deps.current_host()
        self.crt = deps.loaded_crt_version() if crt is None else crt
        self.process_factory = process_factory
        self.status_func = status_func or (
            lambda comp: deps.status(comp, self.host, self.crt))
        self.jobs = {}
        # The editor's look, whatever the host's is.
        self.setFont(theme.font())
        self.setStyleSheet(nxt_editor.stylesheet() + theme.fill(STYLE))
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(label('Optional Components', 'title', 18,
                               QtGui.QFont.DemiBold))
        intro = label("Extras the editor can use. They install into a folder "
                      "of nxt's own, never into {}.".format(
                          host_python(self.host)), 'dim', wrap=True)
        layout.addWidget(intro)
        layout.addSpacing(4)
        self.cards = {}
        for comp in deps.COMPONENTS:
            card = ComponentCard(comp, self.host)
            card.install_requested.connect(self.install)
            card.remove_requested.connect(self.remove)
            card.cancel_requested.connect(self.cancel)
            layout.addWidget(card)
            self.cards[comp.id] = card
        self.note = label('', 'faint', theme.SMALL_PX, wrap=True)
        self.note.setTextFormat(QtCore.Qt.RichText)
        layout.addWidget(self.note)
        layout.addStretch(1)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self.close_button = QtWidgets.QPushButton('Close')
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)
        self.setMinimumWidth(600)
        self.refresh()

    def refresh(self):
        """Look at what is installed again, and show it, except on the cards
        busy installing."""
        order = []
        for comp in deps.COMPONENTS:
            card = self.cards[comp.id]
            if not card.working:
                card.set_status(self.status_func(comp))
            # What is not needed here goes last.
            order.append((card.status.state == deps.Status.NOT_NEEDED,
                          deps.COMPONENTS.index(comp), card))
        layout = self.layout()
        first = min(layout.indexOf(c) for c in self.cards.values())
        for offset, (_dim, _index, card) in enumerate(sorted(
                order, key=lambda o: o[:2])):
            layout.removeWidget(card)
            layout.insertWidget(first + offset, card)
        self.note.setText(self.note_text())
        self.note.setToolTip('\n'.join(
            deps.wheel_dirs() + [p for p in (deps.shared_root(),) if p]))
        self.note.setVisible(bool(self.note.text()))

    def note_text(self):
        lines = []
        wheels = deps.wheel_dirs()
        if wheels:
            lines.append('Installing from {}, offline.'.format(
                ', '.join(self.path_html(w) for w in wheels)))
        shared = deps.shared_root()
        if shared:
            if deps.writable(shared) or not os.path.isdir(shared):
                lines.append('Components are shared from {}.'.format(
                    self.path_html(shared)))
            else:
                lines.append('Your studio provides components from {}. Others '
                             'install to {}.'.format(
                                 self.path_html(shared),
                                 self.path_html(deps.user_root())))
        return '<br>'.join(lines)

    def path_html(self, path):
        """A path for the notes, shortened in the middle when long. The
        note's tooltip has them whole."""
        return html(elide(short_path(path), self.note, 260))

    def card(self, component_id):
        return self.cards[component_id]

    def focus(self, component_id):
        """Point at one card, for when the dialog is opened for it."""
        card = self.cards.get(component_id)
        if card is None:
            return
        card.setProperty('focused', True)
        card.style().unpolish(card)
        card.style().polish(card)

        def unfocus():
            try:
                card.setProperty('focused', False)
                card.style().unpolish(card)
                card.style().polish(card)
            except RuntimeError:
                pass
        QtCore.QTimer.singleShot(1600, unfocus)

    # -- doing -------------------------------------------------------------

    def install(self, component):
        if component.id in self.jobs and self.jobs[component.id].running:
            return self.jobs[component.id]
        card = self.cards[component.id]
        was_loaded = component.module in sys.modules
        job = InstallJob(component, self.crt, self.process_factory, self)
        job.line.connect(card.add_line)
        job.step.connect(card.set_step)
        job.progress.connect(card.set_progress)
        job.finished.connect(lambda ok, message: self.on_finished(
            component, ok, message, was_loaded))
        self.jobs[component.id] = job
        card.start_work()
        job.start()
        return job

    def cancel(self, component):
        job = self.jobs.get(component.id)
        if job is not None:
            job.cancel()

    def on_finished(self, component, ok, message, was_loaded=False):
        card = self.cards[component.id]
        if not ok:
            card.end_work(False, message)
            return
        if message == 'restart':
            card.end_work(True, 'Downloaded. Restart {} to finish.'.format(
                host_name(self.host)))
        else:
            if not component.compiled:
                # So the next import finds the new one.
                forget_modules(self.module_names(component))
            text = 'Installed. Ready to use.'
            if was_loaded and component.compiled:
                text = 'Updated. Restart {} to use it.'.format(
                    host_name(self.host))
            card.end_work(True, text)
        deps.add_to_path(self.crt)
        card.set_status(self.status_func(component))
        card.work.show()
        self.changed.emit(component.id)

    def module_names(self, component):
        version, where = deps.installed(component, self.crt)
        names = {component.module}
        if where:
            owned, _ = deps._owned(component, where)
            names |= {os.path.splitext(n)[0] for n in owned
                      if not n.endswith(('.dist-info', '.egg-info'))}
        return names

    def remove(self, component):
        card = self.cards[component.id]
        try:
            names = deps.remove(component, crt=self.crt)
        except RuntimeError as error:
            card.set_status(self.status_func(component))
            card.work.show()
            card.progress.hide()
            card.end_work(False, str(error))
            card.set_action('remove')
            return
        forget_modules(set(names) | {component.module})
        card.set_status(self.status_func(component))
        card.work.show()
        card.end_work(True, 'Removed.')
        self.changed.emit(component.id)

    def busy(self):
        return any(job.running for job in self.jobs.values())


# -- reaching it --------------------------------------------------------------

class Hint(QtWidgets.QDialog):
    """Asks, once, whether to install jedi when Python Analysis is picked
    without it."""

    def __init__(self, parent=None):
        super(Hint, self).__init__(parent)
        self.setObjectName('optionalComponents')
        self.setWindowTitle('Python Analysis')
        self.setFont(theme.font())
        self.setStyleSheet(nxt_editor.stylesheet() + theme.fill(STYLE))
        self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(8)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(Glyph(deps.JEDI.id), 0, QtCore.Qt.AlignTop)
        text = QtWidgets.QVBoxLayout()
        text.setSpacing(4)
        text.addWidget(label('Python Analysis needs jedi', 'title',
                             theme.TEXT_PX + 1, QtGui.QFont.DemiBold))
        text.addWidget(label(
            'jedi is a free add on ({}) that makes completion smarter: it '
            'knows what a call returns and what a variable holds. It '
            "installs into nxt's own folder.".format(deps.JEDI.size), 'dim',
            wrap=True))
        top.addLayout(text, 1)
        layout.addLayout(top)
        layout.addSpacing(6)
        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        later = QtWidgets.QPushButton('Not Now')
        later.setObjectName('secondary')
        later.clicked.connect(self.reject)
        buttons.addWidget(later)
        install = QtWidgets.QPushButton('Install')
        install.setObjectName('primary')
        install.setDefault(True)
        install.clicked.connect(self.accept)
        buttons.addWidget(install)
        layout.addLayout(buttons)
        self.setFixedWidth(440)


class Notice(QtWidgets.QWidget):
    """A quiet line in the status bar saying an update is wanted, with a
    link to the dialog and a way to dismiss it."""
    open_requested = QtCore.Signal()

    def __init__(self, text, parent=None):
        super(Notice, self).__init__(parent)
        self.setObjectName('cardPart')
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)
        dot = Pill()
        dot.set('Update', WARN)
        layout.addWidget(dot)
        self.label = QtWidgets.QLabel(
            '{}&nbsp;&nbsp;<a href="open" style="color:{};">Optional '
            'Components...</a>'.format(html(text), theme.TEXT))
        self.label.setFont(theme.font(theme.SMALL_PX))
        self.label.setStyleSheet(theme.fill(
            'QLabel { color: {TEXT_DIM}; background: transparent; }'))
        self.label.linkActivated.connect(self._open)
        layout.addWidget(self.label)
        close = QtWidgets.QPushButton('\u00d7')
        close.setFlat(True)
        close.setCursor(QtCore.Qt.PointingHandCursor)
        close.setToolTip('Dismiss')
        close.setFixedSize(18, 18)
        close.setFont(theme.font(theme.TEXT_PX))
        close.setStyleSheet(theme.fill(
            'QPushButton { border: none; background: transparent; '
            'color: {TEXT_FAINT}; padding: 0; } '
            'QPushButton:hover { color: {TEXT}; }'))
        close.clicked.connect(self.dismiss)
        layout.addWidget(close)

    def _open(self, _href=None):
        self.open_requested.emit()
        self.dismiss()

    def dismiss(self):
        self.hide()
        self.deleteLater()


#: Whether this session has said an update is wanted. Said once at most.
_NOTICE_SHOWN = []


def updates_wanted(status_func=None):
    """The components that are installed but outside the range this nxt
    works with, and can be updated from the dialog."""
    status_func = status_func or deps.status
    wanted = []
    for comp in deps.COMPONENTS:
        try:
            each = status_func(comp)
        except Exception:
            logger.debug('Could not check %s', comp.id, exc_info=True)
            continue
        if each.state == deps.Status.UPDATE:
            wanted.append(each)
    return wanted


def notice_text(wanted):
    names = [w.component.name for w in wanted]
    if len(names) == 1:
        return '{} needs an update.'.format(names[0])
    return '{} need updates.'.format(' and '.join(names))


def show_startup_notice(status_bar, open_dialog, status_func=None):
    """Once a session, say in the status bar when a component needs an
    update. Returns the notice, or None when there is nothing to say."""
    if _NOTICE_SHOWN:
        return None
    wanted = updates_wanted(status_func)
    if not wanted:
        return None
    _NOTICE_SHOWN.append(True)
    notice = Notice(notice_text(wanted))
    notice.open_requested.connect(open_dialog)
    status_bar.addWidget(notice)
    return notice
