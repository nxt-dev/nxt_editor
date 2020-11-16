# Built-in
import os

# External
from maya import cmds


def onMayaDroppedPythonFile(*args):
    mod_dir = os.path.dirname(__file__)
    template_mod_file = os.path.join(mod_dir, 'nxt.mod')

    with open(template_mod_file, 'r') as fp:
        mod_template = fp.read()
    mod_content = mod_template.replace('<NXT_MOD_PATH>', mod_dir)

    user_maya_dir = os.environ.get('MAYA_APP_DIR')
    user_mods_dir = os.path.join(user_maya_dir, 'modules')
    if not os.path.isdir(user_mods_dir):
        os.makedirs(user_mods_dir)
    cap = "nxt module file location"
    result = cmds.fileDialog2(caption=cap, dir=user_mods_dir, fileMode=2)
    chosen_dir = result[0]
    chosen_mod_path = os.path.join(chosen_dir, 'nxt.mod')
    with open(chosen_mod_path, 'w+') as fp:
        fp.write(mod_content)
    print("Placed nxt mod file at {}".format(chosen_mod_path))
