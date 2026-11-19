# Builtin
import os
import logging
import sys

# Optional components installed in nxt's own folder, jedi say, made
# importable before anything asks for them. See optional_deps.
from nxt_editor.integration import optional_deps as _optional_deps
try:
    _optional_deps.add_to_path()
except Exception as _error:
    logging.getLogger('nxt.nxt_editor').warning(
        'Could not add the optional components to the path: %s', _error)

# External
from Qt import QtCompat, QtCore, QtWidgets, QtGui

# Internal
import nxt

logger = logging.getLogger('nxt.nxt_editor')

LOGGER_NAME = logger.name

# Set on a QApplication nxt made itself, as opposed to a host's.
OWN_APP_PROPERTY = 'nxt_owns_app'


def owns_qapp():
    """True when the running QApplication is nxt's own, so the editor may
    set application wide state such as the font. False inside a host such
    as Maya, where that state belongs to the host.
    """
    app = QtWidgets.QApplication.instance()
    return bool(app and app.property(OWN_APP_PROPERTY))


class DIRECTIONS:
    UP = 'up'
    DOWN = 'down'
    LEFT = 'left'
    RIGHT = 'right'


class LoggingSignaler(QtCore.QObject):
    """Qt object used to emit logging messages. This object allows us to make
    thread safe visual loggers.
    """
    signal = QtCore.Signal(logging.LogRecord)


class StringSignaler(QtCore.QObject):
    """Qt object used to emit strings. This object allows us to use Qt
    signals in objects that themselves can't be a QObject.
    """
    signal = QtCore.Signal(str)


# The icons, fonts and styles behind the editor's ":" paths. Read from
# resources/ and registered in memory rather than compiled with rcc; see
# qt_resources for why.
from nxt_editor import qt_resources
qt_resources.register()

# How the host this editor runs in opens a new editor, given a list of
# files or None, when it has wiring of its own to do. Set by the host's
# integration; the editor's own show_new_editor is used without it.
host_opener = None

STYLESHEET = ':styles/styles/dark/dark.qss'
MODERN_STYLESHEET = ':styles/styles/dark/modern.qss'


def stylesheet():
    """The editor's stylesheet, as text.

    The original dark sheet, in the theme's colors, with the modern layer
    after it so the modern one wins where both style something.
    """
    from nxt_editor import theme
    if theme.LOOK == theme.LOOK_HOST and theme.HOST_DRAWS:
        # The host's own widgets, as the host draws them, but for the
        # few places that do not read.
        sheet = theme.fill(theme.HOST_SHEET)
    elif theme.LOOK == theme.LOOK_CLASSIC:
        sheet = _read_resource(STYLESHEET)
    else:
        sheet = (theme.restyle(_read_resource(STYLESHEET)) + '\n' +
                 theme.fill(_read_resource(MODERN_STYLESHEET)))
    extra = theme.extra_stylesheet()
    return sheet + '\n' + extra if extra else sheet


def modern_shapes():
    """The modern stylesheet in the look's colors, for widgets that keep
    their modern shapes in a host that draws the rest of the editor."""
    from nxt_editor import theme
    return theme.fill(_read_resource(MODERN_STYLESHEET))


def _read_resource(path):
    """A text file from the editor's resources.

    str() of the QByteArray Qt reads gives a bytes literal in PySide6,
    "b'...'" with its line breaks escaped, which Qt cannot parse.
    Standalone that went unseen because the application has the sheet
    too, but in a host such as Maya the editor's
    widgets have only their own, so they lost its padding and the workflow
    tools their rounded buttons.
    """
    style_file = QtCore.QFile(path)
    if not style_file.open(QtCore.QFile.ReadOnly):
        return ''
    try:
        return bytes(style_file.readAll()).decode('utf-8')
    finally:
        style_file.close()


def _new_qapp():
    app = QtWidgets.QApplication.instance()
    create_new = False
    if not app:
        app = QtWidgets.QApplication
        app.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
        create_new = True
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    app.setEffectEnabled(QtCore.Qt.UI_AnimateCombo, False)
    if create_new:
        app = app(sys.argv)
        # The application is nxt's own, so it can have nxt's font. Never
        # on a host's application (#284).
        app.setProperty(OWN_APP_PROPERTY, True)
    app.setStyleSheet(stylesheet())
    pixmap = QtGui.QPixmap(':icons/icons/nxt.svg')
    app.setWindowIcon(QtGui.QIcon(pixmap))
    return app


def launch_editor(paths=None, start_rpc=False):
    """Launch an instance of the editor. Will attach to existing QApp if found,
    otherwise will create and open one.
    """
    existing = QtWidgets.QApplication.instance()
    if existing:
        app = existing
    else:
        app = _new_qapp()
    from nxt_editor.dialogs import UpgradePrefsDialogue
    UpgradePrefsDialogue.confirm_upgrade_if_possible()
    instance = show_new_editor(paths, start_rpc)
    app.setActiveWindow(instance)
    if not existing:
        app.exec_()
        # Delete the windows while Qt is still running. Left to Python's
        # exit, Qt's objects can go in the wrong order and crash. There can
        # be more than the first, when the editor reopened in a new look.
        from nxt_editor.main_window import MainWindow
        for window in app.topLevelWidgets():
            if isinstance(window, MainWindow):
                QtCompat.delete(window)
    return instance


def show_new_editor(paths=None, start_rpc=False):
    path = None
    if paths and isinstance(paths, list):
        path = paths[0]
        paths.pop(0)
    elif isinstance(paths, str):
        path = paths
        paths = []
    else:
        paths = []
    # Deferred import since main window relies on us
    from nxt_editor.main_window import MainWindow
    instance = MainWindow(filepath=path, start_rpc=start_rpc)
    for other_path in paths:
        instance.load_file(other_path)
    instance.show()
    return instance

