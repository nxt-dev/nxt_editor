"""Build the Blender add-on: build/nxt_blender/ and build/nxt_blender.zip.

    python build/make_blender_addon.py [path/to/nxt/nxt]

The zip is what Blender's Install from Disk takes. Inside it is one folder,
nxt_blender, holding the add-on and, under lib/, everything it runs:
nxt, nxt_editor and Qt.py. It used to ship nxt and nxt_editor loose
beside an add-on that never looked at them.

Needs nothing but python. nxt defaults to ../nxt/nxt, a checkout of nxt
beside this repository.
"""
import os
import py_compile
import shutil
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(REPO, 'build')
ADDON = os.path.join(BUILD, 'nxt_blender')
ZIP_PATH = os.path.join(BUILD, 'nxt_blender.zip')
INTEGRATION = os.path.join(REPO, 'nxt_editor', 'integration', 'blender')

JUNK = shutil.ignore_patterns('__pycache__', '.mypy_cache', '.pytest_cache',
                              '*.pyc', '*.pyo',
                              # rcc's output from older versions; nothing
                              # reads it now.
                              'qresources.py*')


def build(core_dir):
    if not os.path.isfile(os.path.join(core_dir, '__init__.py')):
        raise RuntimeError('No nxt package at {}'.format(core_dir))
    if os.path.isdir(ADDON):
        shutil.rmtree(ADDON)
    lib = os.path.join(ADDON, 'lib')
    os.makedirs(lib)

    shutil.copyfile(os.path.join(INTEGRATION, 'nxt_blender.py'),
                    os.path.join(ADDON, '__init__.py'))
    shutil.copyfile(os.path.join(INTEGRATION, 'README.md'),
                    os.path.join(ADDON, 'README.md'))
    shutil.copytree(os.path.join(REPO, 'nxt_editor'),
                    os.path.join(lib, 'nxt_editor'), ignore=JUNK)
    shutil.copytree(core_dir, os.path.join(lib, 'nxt'), ignore=JUNK)
    qt_py = os.path.join(lib, 'Qt', '__init__.py')
    os.makedirs(os.path.dirname(qt_py))
    shutil.copyfile(os.path.join(BUILD, 'vendor', 'Qt.py'), qt_py)
    py_compile.compile(qt_py, doraise=True)
    shutil.rmtree(os.path.join(os.path.dirname(qt_py), '__pycache__'),
                  ignore_errors=True)

    if os.path.isfile(ZIP_PATH):
        os.remove(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH, 'w', zipfile.ZIP_DEFLATED) as archive:
        for root, dirs, files in os.walk(ADDON):
            dirs.sort()
            for name in sorted(files):
                path = os.path.join(root, name)
                archive.write(path, os.path.relpath(path, BUILD))
    print('built {} ({} bytes)'.format(ZIP_PATH, os.path.getsize(ZIP_PATH)))
    return ZIP_PATH


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    core_dir = argv[0] if argv else os.path.join(os.path.dirname(REPO),
                                                 'nxt', 'nxt')
    build(os.path.abspath(core_dir))
    return 0


if __name__ == '__main__':
    sys.exit(main())
