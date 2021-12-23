"""Depends on the following environment variables being populated.
NXT_ENV_PATH: mapped to site-packages directory containing nxt's dependencies.
NXT_PATH: mapped to a directory containing the nxt package.
"""
# Built-in
import sys
import webbrowser
import logging
import time
import os

# External
# maya
from maya import cmds
from maya import mel
import maya.api.OpenMaya as om
from Qt import QtCore

# Internal
import nxt_editor.main_window
import nxt.remote.nxt_socket
from nxt import nxt_log
from nxt_editor.constants import NXT_WEBSITE
from nxt.constants import NXT_DCC_ENV_VAR

logger = logging.getLogger('nxt')
CREATED_UI = []
global __NXT_INSTANCE__
__NXT_INSTANCE__ = None


class MAYA_PLUGIN_VERSION(object):
    # TODO: Where/if to track these
    # with open(version_file, 'r') as f:
    #     version_data = json.load(f)
    # plugin_v_data = version_data['MAYA_PLUGIN']
    plugin_v_data = {'MAJOR': 0,
                     'MINOR': 1,
                     'PATCH': 0}
    MAJOR = plugin_v_data['MAJOR']
    MINOR = plugin_v_data['MINOR']
    PATCH = plugin_v_data['PATCH']
    VERSION_TUPLE = (MAJOR, MINOR, PATCH)
    VERSION_STR = '.'.join(str(v) for v in VERSION_TUPLE)
    VERSION = VERSION_STR


def about_menu(*args):
    webbrowser.open_new(NXT_WEBSITE)


def auto_reload(*args):
    safe = True
    global __NXT_INSTANCE__
    if __NXT_INSTANCE__:
        safe = __NXT_INSTANCE__.close()
    if safe:
        cmds.nxt_ui('reload')
    else:
        cmds.warning('Aborted reload!')


def enable_cmd_port(enable):
    logger.warning('This is a placeholder!')
    # port = nxt.remote.nxt_socket.CMD_PORT
    # host = nxt.remote.nxt_socket.HOST
    # address = '{}:{}'.format(host, port)
    # if not cmds.commandPort(address, query=True) and enable:
    #     cmds.warning('Opening nxt cmd port...')
    #     cmds.commandPort(name=address, prefix="python",
    #                      sourceType="mel", bs=2048)
    # elif cmds.commandPort(address, query=True) and not enable:
    #     cmds.warning('Closing nxt cmd port...')
    #     cmds.commandPort(name=address, cl=True)
    #     model = nxt.remote.nxt_socket.get_nxt_model()
    #     model.close(notify_server=True)


def create_remote_context(*args):
    t = 'maya' + cmds.about(version=True)
    if cmds.about(mac=True) or cmds.about(linux=True):
        partial_exe_path = 'bin/mayapy'
    elif cmds.about(win=True):
        partial_exe_path = 'bin/mayapy.exe'
    else:
        raise OSError('You are running an unsupported OS.')
    mayapy = os.path.join(os.environ['MAYA_LOCATION'], partial_exe_path)
    create_func = nxt_editor.main_window.MainWindow.create_remote_context
    create_func(place_holder_text=t, interpreter_exe=mayapy)


class NxtUiCmd(om.MPxCommand):
    cmd_name = "nxt_ui"

    @staticmethod
    def cmdCreator():
        return NxtUiCmd()

    def doIt(self, args):
        global __NXT_INSTANCE__
        os.environ[NXT_DCC_ENV_VAR] = 'maya'
        if args:
            string_args = []
            for arg in range(len(args)):
                string_args += [args.asString(arg)]
            if 'close' in string_args:
                if __NXT_INSTANCE__:
                    __NXT_INSTANCE__.close()
                return
        nxt_win = nxt_editor.main_window.MainWindow()
        if 'win32' in sys.platform:
            # gives nxt it's own entry on taskbar
            nxt_win.setWindowFlags(QtCore.Qt.Window)

        def log_callback(message, msg_type, data):
            formatting = {
                om.MCommandMessage.kWarning: '# Warning: {} #',
                om.MCommandMessage.kError: '# Error: {} #',
                om.MCommandMessage.kResult: '# Result: {} #'
            }
            if message.endswith('\n'):
                text = message[:-1]
            else:
                text = message
            text = formatting.get(msg_type, '{}').format(text)
            display_type = om.MCommandMessage.kDisplay
            if message.endswith('\n') or msg_type != display_type:
                text += '\n'
            nxt_win.output_log.write_raw.emit(text, time.time())
            model = nxt_win.model
            if model:
                model.process_events()
        cb_id = om.MCommandMessage.addCommandOutputCallback(log_callback, None)
        sj = cmds.scriptJob(e=["quitApplication", "cmds.nxt_ui('close')"],
                            protected=True)
        nxt_win.output_log.unwrap_std_streams()

        def remove_callback():
            om.MCommandMessage.removeCallback(cb_id)
            try:
                cmds.scriptJob(kill=sj, force=True)
            except RuntimeError:
                # During a real close it will try to kill the job while its
                # running. Maybe we should just block the signal?
                pass
        nxt_win.close_signal.connect(remove_callback)
        nxt_win.show()
        __NXT_INSTANCE__ = nxt_win


# PLUGIN BOILERPLATE #
def maya_useNewAPI(): pass


def initializePlugin(plugin):
    vendor = 'The nxt contributors'
    version = MAYA_PLUGIN_VERSION.VERSION
    pluginFn = om.MFnPlugin(plugin, vendor, version)
    # Commands
    # TODO promote to for loop if building multiple commands(same for uninit)
    try:
        pluginFn.registerCommand(NxtUiCmd.cmd_name, NxtUiCmd.cmdCreator)
    except Exception:
        logger.exception("Failed to register: {}".format(NxtUiCmd.cmd_name))
        raise
    # UI
    maya_window = mel.eval('$_=$gMainWindow')
    nxt_menu = cmds.menu('nxt', parent=maya_window, tearOff=True)
    CREATED_UI.append(nxt_menu)
    cmds.menuItem('Open Editor', command=cmds.nxt_ui, parent=nxt_menu)
    cmds.menuItem('Create Maya Context', command=create_remote_context,
                  parent=nxt_menu)
    # cmds.menuItem('Open Command Port', command=enable_cmd_port,
    #               parent=nxt_menu, checkBox=False)
    cmds.menuItem('About', command=about_menu, parent=nxt_menu)


def uninitializePlugin(plugin):
    # TODO: Long term we need to remove our self from the modules during the
    #  plugin unload.
    pluginFn = om.MFnPlugin(plugin)
    # Commands
    try:
        pluginFn.deregisterCommand(NxtUiCmd.cmd_name)
    except Exception:
        logger.exception("Failed to unregister: {}".format(NxtUiCmd.cmd_name))
        raise
    # UI
    for ui in CREATED_UI:
        cmds.deleteUI(ui, menu=True)
