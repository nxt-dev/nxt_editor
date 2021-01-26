import os
import sys
import unreal
import subprocess


def is_nxt_available():
    try:
        from nxt_editor.integration.unreal import launch_nxt_in_ue
        return True
    except:
        return False

def get_python_exc_path():
    exc_name = 'python'
    if sys.platform == 'win32':
        exc_name = 'python.exe'

    real_prefix = os.path.realpath(sys.prefix)
    return os.path.join(real_prefix, exc_name)

def install_nxt_to_interpreter():
    subprocess.check_call([get_python_exc_path(), '-m', 'pip',
                           'install', 'nxt-editor'])
    unreal.log_warning("Please restart the editor for nxt menu options.")

def update_installed_nxt():
    subprocess.check_call([get_python_exc_path(), '-m', 'pip',
                           'install', '--upgrade', 'nxt-editor', 'nxt-core'])

def uninstall_nxt_from_interpreter():
    subprocess.check_call([get_python_exc_path(), '-m', 'pip',
                           'uninstall', '-y', 'nxt-editor', 'nxt-core'])
    unreal.log_warning("Nxt menu will refresh next editor launch.")

def make_open_editor_entry():
    entry = unreal.ToolMenuEntry(name='Open Editor',
                                 type=unreal.MultiBlockType.MENU_ENTRY)
    entry.set_label('Open Editor')
    launch_command = "from nxt_editor.integration.unreal import launch_nxt_in_ue; launch_nxt_in_ue()"
    entry.set_string_command(unreal.ToolMenuStringCommandType.PYTHON, 'Python',
                             string=launch_command)
    return entry

def make_install_entry():
    entry = unreal.ToolMenuEntry(name='Install Package',
                                 type=unreal.MultiBlockType.MENU_ENTRY)
    entry.set_label('Install nxt package to active python')
    entry.set_string_command(unreal.ToolMenuStringCommandType.PYTHON, 'Python',
                             string='install_nxt_to_interpreter()')
    return entry

def make_update_entry():
    entry = unreal.ToolMenuEntry(name='Update nxt package',
                                 type=unreal.MultiBlockType.MENU_ENTRY)
    entry.set_label('Update nxt python package')
    entry.set_string_command(unreal.ToolMenuStringCommandType.PYTHON, 'Python',
                             string='update_installed_nxt()')
    return entry

def make_uninstall_entry():
    entry = unreal.ToolMenuEntry(name='Uninstall Package',
                                 type=unreal.MultiBlockType.MENU_ENTRY)
    entry.set_label('Uninstall nxt package from active python')
    entry.set_string_command(unreal.ToolMenuStringCommandType.PYTHON, 'Python',
                             string='uninstall_nxt_from_interpreter()')
    return entry


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
    nxt_menu = make_or_find_nxt_menu()
    if is_nxt_available():
        nxt_menu.add_menu_entry("nxt-section", make_open_editor_entry())
        nxt_menu.add_menu_entry("nxt-section", make_update_entry())
        nxt_menu.add_menu_entry("nxt-section", make_uninstall_entry())
    else:
        nxt_menu.add_menu_entry("nxt-section", make_install_entry())
    menus = unreal.ToolMenus.get()
    menus.refresh_all_widgets()

if __name__ == '__main__':
    refresh_nxt_menu()
