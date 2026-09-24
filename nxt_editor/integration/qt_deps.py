"""Finding, and installing, PySide6 for hosts that don't ship Qt.

Maya brings its own PySide6. Blender and Unreal have none, and nxt_editor
is a Qt application, so for those two it has to be installed once. It goes
into a folder of its own rather than into the host's python, which is
usually somewhere an artist cannot write, and which a host update would
replace anyway.

The folder is ``<root>/py<major><minor>``, because compiled extensions only
load in the python version they were built for. The root is, in order:

- ``NXT_QT_DEPS``, for a studio that installs it once somewhere shared,
- ``<nxt user dir>/deps``, which is ``~/nxt/deps`` unless ``NXT_USER_DIR``
  says otherwise.

Nothing here imports Qt or nxt_editor, because it runs before either can
be imported. The hosts load this file by its path.
"""
import os
import subprocess
import sys

DEPS_ENV_VAR = 'NXT_QT_DEPS'

#: What gets installed. The same range nxt_editor's package requires.
REQUIREMENT = 'pyside6-essentials>=6,<6.12'


def deps_root():
    root = os.environ.get(DEPS_ENV_VAR)
    if root:
        return root
    user_dir = os.environ.get('NXT_USER_DIR',
                              os.path.expanduser(os.path.join('~', 'nxt')))
    return os.path.join(user_dir, 'deps')


def deps_dir():
    """Where this python's PySide6 lives, whether or not it is there yet."""
    return os.path.join(deps_root(), 'py%d%d' % sys.version_info[:2])


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
            '--target', deps_dir(), REQUIREMENT]


def install_instructions():
    return ('nxt_editor needs PySide6, which this application does not '
            'ship. Install it once with:\n\n    {}\n\nor set {} to a folder '
            'that already has it in a py{}{} folder.'.format(
                subprocess.list2cmdline(install_command()), DEPS_ENV_VAR,
                *sys.version_info[:2]))


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
