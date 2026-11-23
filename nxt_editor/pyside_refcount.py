"""Keeps PySide6 on Linux ARM from freeing None, True and False.

PySide6 built for Linux ARM gives back a reference to the value of each
Python method Qt calls, a paintEvent or a delegate's paint, without having
taken one, and to the True or False a signal carries. Before Python 3.12
those objects are counted like any other, so their counts run down as the
editor is used, and Python aborts when one reaches zero ("deallocating
None"). Every PySide6 version from 6.8 to 6.11 does it, with plain Qt
widgets as much as with the editor's.

Python 3.12 and later never free them, see PEP 683. This gives them the
same here: a count no session can run down. They are never freed anyway,
so nothing else changes.
"""
# Builtin
import ctypes
import platform
import sys

#: More than any session gives back.
COUNT = 1 << 60

SINGLETONS = (None, True, False)


def needed(binding):
    """Whether this Python and Qt binding are the ones that need it.

    :param binding: the Qt binding in use, Qt.__binding__
    """
    return (binding == 'PySide6' and
            sys.version_info < (3, 12) and
            platform.python_implementation() == 'CPython' and
            sys.platform.startswith('linux') and
            platform.machine().lower() in ('aarch64', 'arm64'))


def protect():
    """Give None, True and False a count PySide6 cannot run down.

    A CPython object starts with its count, a Py_ssize_t, and id() is
    its address.
    """
    for obj in SINGLETONS:
        ctypes.c_ssize_t.from_address(id(obj)).value = COUNT


def protect_if_needed(binding):
    if needed(binding):
        protect()
        return True
    return False
