"""The native modules a host package carries, for nxt's faster comp engine.

A copy of nxt from git has none, since they are built, not committed. So
the builds of every OS are taken from the nxt running this, when it has
them: a release from PyPI or the studio's rez package carries all four.
One from another version of nxt is never loaded, see nxt/native.py, so
taking them can't make a package wrong, only faster.
"""
import os
import shutil

MODULES = ('_nxt_native.pyd', '_nxt_native.so')


def builds(core_dir):
    """The platforms core_dir's nxt has a native module for."""
    bin_dir = os.path.join(core_dir, '_bin')
    if not os.path.isdir(bin_dir):
        return []
    return sorted(tag for tag in os.listdir(bin_dir)
                  if any(os.path.isfile(os.path.join(bin_dir, tag, name))
                         for name in MODULES))


def add_missing(core_dir):
    """Give the nxt copied to core_dir the native modules it lacks, from the
    running nxt, and say which platforms it has. Returns them."""
    try:
        from nxt import native
        source = os.path.dirname(native.BIN_DIR)
    except ImportError:
        source = None
    if source and os.path.abspath(source) != os.path.abspath(core_dir):
        os.makedirs(os.path.join(core_dir, '_bin'), exist_ok=True)
        for tag in builds(source):
            if tag in builds(core_dir):
                continue
            for name in MODULES:
                path = os.path.join(source, '_bin', tag, name)
                if os.path.isfile(path):
                    dest = os.path.join(core_dir, '_bin', tag)
                    os.makedirs(dest, exist_ok=True)
                    shutil.copyfile(path, os.path.join(dest, name))
    # Modules nxt's build.py moved aside on a working machine.
    for root, _, files in os.walk(os.path.join(core_dir, '_bin')):
        for name in files:
            if name.startswith(MODULES) and '.old' in name:
                os.remove(os.path.join(root, name))
    found = builds(core_dir)
    if found:
        print('native comp engine for: ' + ', '.join(found))
    else:
        print('no native modules: this package composites with the '
              'Python code, which gives the same result, slower')
    return found
