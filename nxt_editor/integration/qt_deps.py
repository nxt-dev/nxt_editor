"""Finding, and installing, PySide6 for hosts that don't ship Qt.

Maya brings its own PySide6. Blender and Unreal have none, and nxt_editor
is a Qt application, so for those two it has to be installed once. PySide6
is one of nxt's optional components now, see optional_deps.py, which says
where it goes and why. This module is what the Blender and Unreal menus
have always called, kept so they, and anything a studio wrote against it,
keep working.

Nothing here imports Qt or nxt_editor, because it runs before either can
be imported. The hosts load this file by its path, and it loads
optional_deps.py beside it the same way.
"""
import importlib.util
import os
import sys

if __package__:
    from . import optional_deps as _deps
else:
    _deps = sys.modules.get('nxt_optional_deps')
    if _deps is None:
        _spec = importlib.util.spec_from_file_location(
            'nxt_optional_deps',
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'optional_deps.py'))
        _deps = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_deps)
        sys.modules['nxt_optional_deps'] = _deps

optional_deps = _deps

DEPS_ENV_VAR = _deps.DEPS_ENV_VAR
LEGACY_DEPS_ENV_VAR = _deps.LEGACY_DEPS_ENV_VAR

#: What gets installed. The same range nxt_editor's package requires.
REQUIREMENT = _deps.PYSIDE6.requirement
#: What an older C++ runtime gets instead, see optional_deps.
LEGACY_CRT_REQUIREMENT = _deps.PYSIDE6.legacy_requirement
MODERN_CRT = _deps.MODERN_CRT

loaded_crt_version = _deps.loaded_crt_version
python_executable = _deps.python_executable
has_qt = _deps.has_qt


def legacy_crt():
    return _deps.is_legacy_crt(loaded_crt_version())


def requirement():
    return _deps.requirement(_deps.PYSIDE6, loaded_crt_version())


def deps_root():
    return _deps.install_root()


def deps_dir():
    """Where this python's PySide6 lives, whether or not it is there yet."""
    return _deps.folder(_deps.PYSIDE6, crt=loaded_crt_version())


def add_to_path():
    """Make the installed components importable. Returns whether Qt is."""
    _deps.add_to_path(loaded_crt_version())
    return has_qt()


def install_command():
    return _deps.install_command(_deps.PYSIDE6, deps_dir(),
                                 loaded_crt_version())


def install_instructions():
    return ('nxt_editor needs PySide6, which this application does not '
            'ship.\n' + _deps.install_instructions(_deps.PYSIDE6,
                                                  loaded_crt_version()))


def install(on_line=None):
    """pip install PySide6 into deps_dir(). Raises RuntimeError if that
    fails, with pip's output in the message.

    :param on_line: called with each line pip prints
    """
    crt = loaded_crt_version()
    _deps.install(_deps.PYSIDE6, crt, on_line=on_line)
    if not add_to_path():
        raise RuntimeError('PySide6 was installed to {} but still cannot be '
                           'imported.'.format(deps_dir()))
    return deps_dir()
