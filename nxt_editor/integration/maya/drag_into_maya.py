# Built-in
import json
import os

# External
from maya import cmds


def _version():
    """The editor version, for the module file.

    Read straight off disk rather than imported, because this runs before
    nxt_editor is on the path.

    :rtype: str
    """
    here = os.path.dirname(os.path.abspath(__file__))
    version_file = os.path.join(here, os.pardir, os.pardir, 'version.json')
    try:
        with open(version_file, 'r') as fp:
            editor = json.load(fp)['EDITOR']
        return '{MAJOR}.{MINOR}.{PATCH}'.format(**editor)
    except (IOError, OSError, ValueError, KeyError):
        return '0.0.0'


def onMayaDroppedPythonFile(*args):
    mod_dir = os.path.dirname(__file__)
    template_mod_file = os.path.join(mod_dir, 'nxt.mod')

    with open(template_mod_file, 'r') as fp:
        mod_template = fp.read()
    mod_content = mod_template.replace('<NXT_MOD_PATH>', mod_dir)
    # Only the packaged plugin has this substituted already. Installed by
    # drag and drop from a checkout, the placeholder went into the .mod
    # verbatim, and maya wants a real version there.
    mod_content = mod_content.replace('<VERSION>', _version())

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
