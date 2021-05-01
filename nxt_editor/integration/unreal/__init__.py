# Built-in
import os
import atexit

# External
import unreal
from Qt import QtWidgets

# Internal
from nxt.constants import NXT_DCC_ENV_VAR
import nxt_editor


global __NXT_WINDOW
__NXT_WINDOW = None

def launch_nxt_in_ue():
    os.environ[NXT_DCC_ENV_VAR] = 'unreal'
    existing = QtWidgets.QApplication.instance()
    if existing:
        unreal.log('Found existing QApp')
    else:
        unreal.log('Building new QApp for nxt')
        existing = nxt_editor._new_qapp()

    global __NXT_WINDOW
    if __NXT_WINDOW:
        __NXT_WINDOW.show()
        __NXT_WINDOW.raise_()
    else:
        __NXT_WINDOW = nxt_editor.show_new_editor()

    __NXT_WINDOW.close_signal.connect(existing.exit)
    atexit.register(__NXT_WINDOW.close)
