# Built-in
import os
import atexit

# External
import unreal
from Qt import QtWidgets

# Internal
from nxt.constants import NXT_DCC_ENV_VAR
import nxt_editor


__NXT_WINDOWS__ = []
__TICK_HANDLE__ = [None]


def _live_windows():
    alive = []
    for window in __NXT_WINDOWS__:
        try:
            if window.isVisible():
                alive.append(window)
        except RuntimeError:
            # Qt already deleted it.
            pass
    __NXT_WINDOWS__[:] = alive
    return alive


def _pump(delta_seconds):
    """Let Qt handle its events once per Slate tick.

    Unreal owns the event loop and knows nothing about Qt, so without this
    an editor window paints once and then ignores every click.
    """
    if not __NXT_WINDOWS__:
        return
    app = QtWidgets.QApplication.instance()
    if app is not None and _live_windows():
        app.processEvents()


def _start_pump():
    if __TICK_HANDLE__[0] is None:
        __TICK_HANDLE__[0] = unreal.register_slate_post_tick_callback(_pump)


def _stop_pump():
    handle = __TICK_HANDLE__[0]
    if handle is not None:
        unreal.unregister_slate_post_tick_callback(handle)
        __TICK_HANDLE__[0] = None


def close_nxt():
    while __NXT_WINDOWS__:
        window = __NXT_WINDOWS__.pop()
        try:
            window.close()
        except RuntimeError:
            pass
    _stop_pump()


def launch_nxt_in_ue(graph=None):
    os.environ[NXT_DCC_ENV_VAR] = 'unreal'
    if QtWidgets.QApplication.instance():
        unreal.log('Found existing QApp')
    else:
        unreal.log('Building new QApp for nxt')
        nxt_editor._new_qapp()

    live = _live_windows()
    if live and not graph:
        window = live[-1]
        window.show()
        window.raise_()
        window.activateWindow()
        return window

    window = nxt_editor.show_new_editor([graph] if graph else None)
    try:
        # Keeps the window above the editor, and minimized with it.
        unreal.parent_external_window_to_slate(int(window.winId()))
    except Exception:
        pass
    __NXT_WINDOWS__.append(window)
    _start_pump()
    return window


atexit.register(close_nxt)
