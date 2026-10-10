# Builtin
import os
import logging
import sys

# External
from Qt import QtCore, QtWidgets, QtGui

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
    style_file = QtCore.QFile(':styles/styles/dark/dark.qss')
    style_file.open(QtCore.QFile.ReadOnly | QtCore.QFile.Text)
    stream = QtCore.QTextStream(style_file)
    app.setStyleSheet(stream.readAll())
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

