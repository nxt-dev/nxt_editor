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

from nxt_editor.integration import plugin_version

logger = logging.getLogger('nxt')
CREATED_UI = []
global __NXT_INSTANCE__
__NXT_INSTANCE__ = None


class MAYA_PLUGIN_VERSION(object):
    # The plugin ships with the editor, so it reports the editor's version
    # rather than a second number nobody remembers to bump. It used to be
    # hardcoded to 0.1.0 and had drifted years behind.
    VERSION_STR = plugin_version() or '0.0.0'
    VERSION_TUPLE = tuple(int(part) for part in VERSION_STR.split('.'))
    MAJOR, MINOR, PATCH = VERSION_TUPLE
    VERSION = VERSION_STR

def open_editor(*args):
    cmds.nxt_ui()


def about_menu(*args):
    webbrowser.open_new(NXT_WEBSITE)



def auto_reload(*args):
    cmds.nxt_ui(reload=True)



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

    kCloseFlag = '-c'
    kCloseFlagLong = '-close'
    kReloadFlag = '-r'
    kReloadFlagLong = '-reload'
    kPathFlag = '-p'
    kPathFlagLong = '-path'

    @staticmethod
    def cmdCreator():
        return NxtUiCmd()

    # Before the flags, nxt_ui took 'close' as a plain argument, and shelves
    # and pipeline tools written then still call it that way. Still accepted,
    # with a warning pointing at the flag.
    LEGACY_ARGS = ('close', 'reload')

    @staticmethod
    def syntaxCreator():
        syntax = om.MSyntax()
        syntax.addFlag(NxtUiCmd.kCloseFlag, NxtUiCmd.kCloseFlagLong)
        syntax.addFlag(NxtUiCmd.kPathFlag, NxtUiCmd.kPathFlagLong,
                       om.MSyntax.kString)
        syntax.makeFlagMultiUse(NxtUiCmd.kPathFlag)
        syntax.addFlag(NxtUiCmd.kReloadFlag, NxtUiCmd.kReloadFlagLong)
        syntax.setObjectType(om.MSyntax.kStringObjects, 0, 1)
        return syntax

    @staticmethod
    def bring_to_front(window):
        """Show an editor that is already open, however it was left.

        :return: False when Qt has already deleted the window.
        :rtype: bool
        """
        try:
            if window.isMinimized():
                window.showNormal()
            elif window.isHidden():
                window.show()
            window.raise_()
            window.activateWindow()
        except RuntimeError:
            return False
        return True

    def doIt(self, args):
        global __NXT_INSTANCE__
        os.environ[NXT_DCC_ENV_VAR] = 'maya'

        # Maya's own message says which flag it did not understand.
        parser = om.MArgParser(self.syntax(), args)
        legacy = [arg.lower() for arg in parser.getObjectStrings()]
        for arg in legacy:
            if arg not in NxtUiCmd.LEGACY_ARGS:
                raise RuntimeError(
                    "nxt_ui: unknown argument '{}'. Use -close/-c, "
                    "-reload/-r or -path/-p.".format(arg))
            cmds.warning("nxt_ui('{0}') is deprecated, use "
                         "nxt_ui({0}=True)".format(arg))

        if parser.isFlagSet(NxtUiCmd.kCloseFlag) or 'close' in legacy:
            if __NXT_INSTANCE__:
                __NXT_INSTANCE__.close()
            return

        reloading = (parser.isFlagSet(NxtUiCmd.kReloadFlag)
                     or 'reload' in legacy)
        if reloading and __NXT_INSTANCE__:
            # close() asks about unsaved changes first, and says whether
            # the window actually closed.
            if not __NXT_INSTANCE__.close():
                cmds.warning('Aborted reload!')
                return
            __NXT_INSTANCE__ = None

        paths = []
        if parser.isFlagSet(NxtUiCmd.kPathFlag):
            for i in range(parser.numberOfFlagUses(NxtUiCmd.kPathFlag)):
                flag_args = parser.getFlagArgumentList(NxtUiCmd.kPathFlag, i)
                paths.append(flag_args.asString(0))

        if __NXT_INSTANCE__ and not self.bring_to_front(__NXT_INSTANCE__):
            # Qt deleted it without the close we listen for.
            __NXT_INSTANCE__ = None
        if __NXT_INSTANCE__:
            # One editor at a time: open what was asked for in it, as tabs.
            for p in paths:
                __NXT_INSTANCE__.load_file(p)
            return

        nxt_win = nxt_editor.show_new_editor(paths=paths or None)
        __NXT_INSTANCE__ = nxt_win
        
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
        sj = cmds.scriptJob(e=["quitApplication", "cmds.nxt_ui(close=True)"],
                            protected=True)
        nxt_win.output_log.unwrap_std_streams()

        def remove_callback():
            global __NXT_INSTANCE__
        
            om.MCommandMessage.removeCallback(cb_id)
        
            try:
                cmds.scriptJob(kill=sj, force=True)
            except RuntimeError:
                pass
        
            if __NXT_INSTANCE__ is nxt_win:
                __NXT_INSTANCE__ = None

        nxt_win.close_signal.connect(remove_callback)

        nxt_win.show()



# PLUGIN BOILERPLATE #
def maya_useNewAPI(): pass


def initializePlugin(plugin):
    vendor = 'The nxt contributors'
    version = MAYA_PLUGIN_VERSION.VERSION
    pluginFn = om.MFnPlugin(plugin, vendor, version)
    # Commands
    # TODO promote to for loop if building multiple commands(same for uninit)
    try:
        pluginFn.registerCommand(NxtUiCmd.cmd_name, NxtUiCmd.cmdCreator, NxtUiCmd.syntaxCreator)
    except Exception:
        logger.exception("Failed to register: {}".format(NxtUiCmd.cmd_name))
        raise
    # UI
    maya_window = mel.eval('$_=$gMainWindow')
    nxt_menu = cmds.menu('nxt', parent=maya_window, tearOff=True)
    CREATED_UI.append(nxt_menu)
    cmds.menuItem('Open Editor', command=open_editor, parent=nxt_menu)
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
