"""Finding, and installing, PySide6 for hosts that don't ship Qt.

Maya brings its own PySide6. Blender and Unreal have none, and nxt_editor
is a Qt application, so for those two it has to be installed once. It goes
into a folder of its own rather than into the host's python, which is
usually somewhere an artist cannot write, and which a host update would
replace anyway.

The folder is ``<root>/py<major><minor>``, because compiled extensions only
load in the python version they were built for. On Windows, a host that
loads an older Microsoft C++ runtime gets a folder of its own as well,
``py311-crt14.29``: PySide6 6.11 is built with a compiler whose runtime
code crashes on the 14.29 runtime Blender 4.2 through 4.5 ship, the moment
QtCore loads, so those hosts are given a PySide6 from before that change,
and never share a folder with a host that has the newer one. The root is,
in order:

- ``NXT_QT_DEPS``, for a studio that installs it once somewhere shared,
- ``<nxt user dir>/deps``, which is ``~/nxt/deps`` unless ``NXT_USER_DIR``
  says otherwise.

Nothing here imports Qt or nxt_editor, because it runs before either can
be imported. The hosts load this file by its path.
"""
import ctypes
import os
import subprocess
import sys

DEPS_ENV_VAR = 'NXT_QT_DEPS'

#: What gets installed. The same range nxt_editor's package requires.
REQUIREMENT = 'pyside6-essentials>=6,<6.12'

#: What an older C++ runtime gets instead. 6.10 is the last PySide6 built
#: with a compiler whose code the 14.29 runtime can run; 6.11 crashes in
#: std::mutex as QtCore loads. Checked in Blender 4.2 and 4.5.
LEGACY_CRT_REQUIREMENT = 'pyside6-essentials>=6,<6.11'

#: The first runtime the newer compiler's code is safe on (Visual Studio
#: 2022 17.10).
MODERN_CRT = (14, 40)

#: VerQueryValue's name for the fixed version block.
ROOT_BLOCK = chr(92)


def loaded_crt_version():
    """The version of the C++ runtime this process has loaded, on Windows.

    Read from the msvcp140.dll the host already has in memory, which is
    the one PySide6 will be given, not whatever the system has installed.

    :return: (major, minor, build), or None when there is nothing to ask
    """
    if sys.platform != 'win32':
        return None
    try:
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        handle = kernel32.GetModuleHandleW('msvcp140.dll')
        if not handle:
            return None
        path = ctypes.create_unicode_buffer(32768)
        kernel32.GetModuleFileNameW(wintypes.HMODULE(handle), path, 32768)
        version = ctypes.WinDLL('version')
        size = version.GetFileVersionInfoSizeW(path.value, None)
        if not size:
            return None
        data = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path.value, 0, size, data):
            return None
        info = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version.VerQueryValueW(data, ROOT_BLOCK, ctypes.byref(info),
                                      ctypes.byref(length)):
            return None
        # VS_FIXEDFILEINFO: signature, struct version, then the version.
        words = ctypes.cast(info, ctypes.POINTER(wintypes.DWORD))
        most, least = words[2], words[3]
        return most >> 16, most & 0xffff, least >> 16
    except Exception:
        return None


def legacy_crt():
    crt = loaded_crt_version()
    return crt is not None and crt[:2] < MODERN_CRT


def requirement():
    return LEGACY_CRT_REQUIREMENT if legacy_crt() else REQUIREMENT


def deps_root():
    root = os.environ.get(DEPS_ENV_VAR)
    if root:
        return root
    user_dir = os.environ.get('NXT_USER_DIR',
                              os.path.expanduser(os.path.join('~', 'nxt')))
    return os.path.join(user_dir, 'deps')


def deps_dir():
    """Where this python's PySide6 lives, whether or not it is there yet."""
    name = 'py%d%d' % sys.version_info[:2]
    if legacy_crt():
        name += '-crt%d.%d' % loaded_crt_version()[:2]
    return os.path.join(deps_root(), name)


def has_qt():
    try:
        import PySide6  # noqa: F401
    except ImportError:
        return False
    return True


def add_to_path():
    """Make an installed PySide6 importable. Returns whether one is.

    Appended rather than put first, so a PySide6 the host or the studio
    already provides wins over one installed here.
    """
    if has_qt():
        return True
    folder = deps_dir()
    if os.path.isdir(folder) and folder not in sys.path:
        sys.path.append(folder)
        import importlib
        importlib.invalidate_caches()
    return has_qt()


def python_executable():
    """The host's python interpreter, which is not always sys.executable.

    In Unreal sys.executable is the editor, and in older Blenders it was
    blender.exe, so the interpreter is looked for under sys.prefix too.
    """
    name = 'python.exe' if sys.platform == 'win32' else 'python3'
    candidates = [sys.executable,
                  os.path.join(sys.prefix, name),
                  os.path.join(sys.prefix, 'bin', name),
                  os.path.join(sys.prefix, 'bin', 'python')]
    for path in candidates:
        base = os.path.basename(path).lower()
        if base.startswith('python') and os.path.isfile(path):
            return os.path.abspath(path)
    return None


def install_command():
    python = python_executable() or 'python'
    return [python, '-m', 'pip', 'install', '--upgrade',
            '--target', deps_dir(), requirement()]


def install_instructions():
    return ('nxt_editor needs PySide6, which this application does not '
            'ship. Install it once with:\n\n    {}\n\nor set {} to a folder '
            'that already has it in a {} folder.'.format(
                subprocess.list2cmdline(install_command()), DEPS_ENV_VAR,
                os.path.basename(deps_dir())))


def install():
    """pip install PySide6 into deps_dir(). Raises RuntimeError if that
    fails, with pip's output in the message.
    """
    if python_executable() is None:
        raise RuntimeError('Could not find the python interpreter under '
                           '{}.\n{}'.format(sys.prefix,
                                            install_instructions()))
    os.makedirs(deps_dir(), exist_ok=True)
    cmd = install_command()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT)
    output = proc.stdout.decode(errors='replace')
    if proc.returncode != 0:
        raise RuntimeError('Installing PySide6 failed:\n{}\n{}'.format(
            output[-4000:], install_instructions()))
    if not add_to_path():
        raise RuntimeError('PySide6 was installed to {} but still cannot be '
                           'imported:\n{}'.format(deps_dir(), output[-4000:]))
    return deps_dir()
