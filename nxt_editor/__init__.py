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


def make_resources(qrc_path=None, result_path=None):
    import subprocess
    this_dir = os.path.dirname(os.path.realpath(__file__))
    if not qrc_path:
        qrc_path = os.path.join(this_dir, 'resources/resources.qrc')
    if not result_path:
        result_path = os.path.join(this_dir, 'qresources.py')
    msg = 'First launch nxt resource generation from {} to {}'
    logger.info(msg.format(qrc_path, result_path))

    args = [qrc_path, '-o', result_path, '-g', 'python']
    try:
        subprocess.call(['pyside6-rcc'] + args)
    except:
        raise Exception("Failed to generate UI resources using PySide rcc!"
                        " Reinstalling PySide6 may fix the problem. If you "
                        "know how to use rcc please build from: \"{}\" and "
                        "output to \"{}\"".format(qrc_path, result_path))
    else:
        return


try:
    from nxt_editor import qresources
except ImportError:
    make_resources()
    from nxt_editor import qresources


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
    style_file = QtCore.QFile(':styles/styles/dark/dark.qss')
    style_file.open(QtCore.QFile.ReadOnly | QtCore.QFile.Text)
    stream = QtCore.QTextStream(style_file)
    app.setStyleSheet(stream.readAll())
    pixmap = QtGui.QPixmap(':icons/icons/nxt.svg')
    app.setWindowIcon(QtGui.QIcon(pixmap))
    return app


def launch_editor(paths=None, start_rpc=True):
    """Launch an instance of the editor. Will attach to existing QApp if found,
    otherwise will create and open one.
    """
    existing = QtWidgets.QApplication.instance()
    if existing:
        app = existing
    else:
        app = _new_qapp()
    instance = show_new_editor(paths, start_rpc)
    app.setActiveWindow(instance)
    if not existing:
        app.exec_()
    return instance


def show_new_editor(paths=None, start_rpc=True):
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

