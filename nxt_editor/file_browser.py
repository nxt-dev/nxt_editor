"""Show a file in the operating system's file browser.

Windows Explorer and the macOS Finder open the file's folder with the file
selected. Linux has no one file manager, so the freedesktop FileManager1
service is asked to do the same, which Nautilus, Dolphin, Nemo, Caja and
Thunar all answer. Without it, the folder is opened by whatever the desktop
opens folders with, and nothing is selected.
"""
# Builtin
import logging
import os
import subprocess
import sys

# External
from Qt import QtCore, QtGui

# Internal
import nxt_editor

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

if sys.platform == 'win32':
    ACTION_TEXT = 'Show in Explorer'
elif sys.platform == 'darwin':
    ACTION_TEXT = 'Reveal in Finder'
else:
    ACTION_TEXT = 'Show in File Manager'


def _nearest_existing(path):
    """The path itself if it exists, otherwise the nearest folder above it
    that does, so a layer saved to a folder since deleted still lands
    somewhere useful. None when nothing on the path exists.
    """
    path = os.path.abspath(path)
    while path and not os.path.exists(path):
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
    return path or None


def _show_items_over_dbus(path):
    """Ask the freedesktop file manager service to select path. True if it
    said it would.
    """
    uri = QtCore.QUrl.fromLocalFile(path).toString()
    command = ['dbus-send', '--session', '--print-reply',
               '--dest=org.freedesktop.FileManager1', '--type=method_call',
               '/org/freedesktop/FileManager1',
               'org.freedesktop.FileManager1.ShowItems',
               'array:string:' + uri, 'string:']
    try:
        result = subprocess.run(command, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def show_in_file_browser(path):
    """Open the file browser on path, with it selected when it is a file.

    :param path: A file or folder.
    :return: True if a file browser was asked to open, False if there was
        nothing on disk to show.
    """
    if not path:
        logger.warning('Nothing to show: the layer has not been saved.')
        return False
    target = _nearest_existing(path)
    if not target:
        logger.warning('Nothing to show: {} does not exist.'.format(path))
        return False
    if target != os.path.abspath(path):
        logger.info('{} does not exist, showing {} '
                    'instead.'.format(path, target))
    is_file = os.path.isfile(target)
    if sys.platform == 'win32':
        target = os.path.normpath(target)
        if is_file:
            # One argument: Explorer reads "/select," and the path together.
            subprocess.Popen('explorer /select,"{}"'.format(target))
        else:
            subprocess.Popen(['explorer', target])
        return True
    if sys.platform == 'darwin':
        subprocess.Popen(['open', '-R', target] if is_file
                         else ['open', target])
        return True
    if is_file and _show_items_over_dbus(target):
        return True
    folder = os.path.dirname(target) if is_file else target
    if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder)):
        logger.warning('Could not open a file browser on {}'.format(folder))
        return False
    return True
