"""The nxt menu in the Unreal editor. init_unreal.py runs this at startup.

A module of its own, rather than living in init_unreal.py, because every
plugin has an init_unreal.py and the menu commands need a name that is
surely this one to import.

The plugin carries nxt, nxt_editor and Qt.py beside this file, in the
Content/Python folder Unreal puts on sys.path for it. It used to pip
install nxt-editor from PyPI into the engine's python instead, which
fetched whatever PyPI had rather than the one this plugin shipped with,
and needed internet access and write access to the engine.

Unreal ships no Qt, so PySide6 is installed once, into a folder outside the
engine; the menu offers to do it. See nxt_editor/integration/qt_deps.py.
"""
import importlib.util
import os
import sys

import unreal

HERE = os.path.dirname(os.path.abspath(__file__))


def _put_first(path):
    """This folder ahead of site-packages, so an nxt_editor pip installed
    into the engine by an older version of this plugin does not win over
    the one shipped with it.
    """
    for existing in list(sys.path):
        if os.path.normcase(os.path.abspath(existing)) == \
                os.path.normcase(path):
            sys.path.remove(existing)
    sys.path.insert(0, path)
    for name in list(sys.modules):
        root = name.split('.')[0]
        if root in ('nxt', 'nxt_editor', 'Qt'):
            module_file = getattr(sys.modules[name], '__file__', '') or ''
            if not os.path.normcase(module_file).startswith(
                    os.path.normcase(path)):
                del sys.modules[name]


def qt_deps():
    """nxt_editor's Qt installer, loaded by path because importing anything
    under nxt_editor imports Qt, which may not be there yet.
    """
    found = sys.modules.get('nxt_qt_deps')
    if found is not None:
        return found
    path = os.path.join(HERE, 'nxt_editor', 'integration', 'qt_deps.py')
    spec = importlib.util.spec_from_file_location('nxt_qt_deps', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules['nxt_qt_deps'] = module
    return module


def is_nxt_available():
    if not qt_deps().add_to_path():
        return False
    try:
        from nxt_editor.integration.unreal import launch_nxt_in_ue  # noqa
        return True
    except Exception as error:
        unreal.log_error('nxt_editor could not be imported: {}'.format(
            error))
        return False


def install_qt():
    deps = qt_deps()
    unreal.log('Installing PySide6 into {}'.format(deps.deps_dir()))
    with unreal.ScopedSlowTask(1, 'Installing PySide6 for nxt') as task:
        task.make_dialog()
        try:
            deps.install()
        except RuntimeError as error:
            unreal.log_error(str(error))
            return
    unreal.log('PySide6 installed.')
    refresh_nxt_menu()


def _python_entry(name, label, command, tooltip=''):
    entry = unreal.ToolMenuEntry(name=name,
                                 type=unreal.MultiBlockType.MENU_ENTRY)
    entry.set_label(label)
    if tooltip:
        entry.set_tool_tip(tooltip)
    entry.set_string_command(unreal.ToolMenuStringCommandType.PYTHON,
                             'Python', string=command)
    return entry


def make_open_editor_entry():
    return _python_entry(
        'Open Editor', 'Open Editor',
        'from nxt_editor.integration.unreal import launch_nxt_in_ue; '
        'launch_nxt_in_ue()')


def make_install_qt_entry():
    return _python_entry(
        'Install Qt', 'Install Qt (PySide6)',
        'import nxt_unreal_menu; nxt_unreal_menu.install_qt()',
        'The nxt editor needs PySide6, which Unreal does not ship. This '
        'downloads it into {}'.format(qt_deps().deps_dir()))


def make_or_find_nxt_menu():
    menus = unreal.ToolMenus.get()
    nxt_menu = menus.find_menu("LevelEditor.MainMenu.NxtMenu")
    if nxt_menu:
        return nxt_menu
    main_menu = menus.find_menu("LevelEditor.MainMenu")
    if not main_menu:
        raise ValueError("Cannot find main menu")
    nxt_menu = main_menu.add_sub_menu(main_menu.get_name(), "nxt-section",
                                      "NxtMenu", "nxt", "The nxt graph editor")
    return nxt_menu


def refresh_nxt_menu():
    try:
        nxt_menu = make_or_find_nxt_menu()
    except ValueError:
        # If the plugin is loaded in unreal headless, the menu won't exist.
        return
    menus = unreal.ToolMenus.get()
    for name in ('Open Editor', 'Install Qt'):
        menus.remove_entry(nxt_menu.get_name(), "nxt-section", name)
    if is_nxt_available():
        nxt_menu.add_menu_entry("nxt-section", make_open_editor_entry())
    else:
        nxt_menu.add_menu_entry("nxt-section", make_install_qt_entry())
    menus.refresh_all_widgets()


def startup():
    _put_first(HERE)
    refresh_nxt_menu()
