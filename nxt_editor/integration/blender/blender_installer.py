import os
import sys

try:
    import pip
    _ = pip.main
    _ = pip._internal.main

except (ImportError, AttributeError):
    import ensurepip
    ensurepip.bootstrap()
    os.environ.pop('PIP_REQ_TRACKER', None)

try:
    import nxt_editor
except ImportError:
    import bpy
    b_major, b_minor, b_patch = bpy.app.version
    user_dir = os.path.expanduser('~/AppData/Roaming/Blender '
                                  'Foundation/Blender/'
                                  '{}.{}'.format(b_major, b_minor))
    t = os.path.join(user_dir, 'scripts/addons/modules')
    t = t.replace(os.sep, '/')
    args = ['install', 'D:/Projects/nxt_editor', '--target', t]
    if hasattr(pip, 'main'):
        pip.main(args)
    else:
        pip._internal.main(args)
    # The next time blender starts it will see this path automatically
    cwd = os.getcwd()
    os.chdir(t)
    sys.path.append(t)
    os.chdir(cwd)

# Install nxt_blender addon
from nxt_editor import integration
integration.Blender.setup()
