import setuptools
import json
import os
import io
this_dir = os.path.dirname(os.path.realpath(__file__))
module_dir = os.path.join(this_dir, 'nxt_editor')

with io.open(os.path.join(this_dir, "README.md"), "r", encoding="utf-8") as fp:
    long_description = fp.read()

desc = ("A general purpose code compositor designed for rigging, "
        "scene assembly, and automation. (node execution tree)")

with open(os.path.join(module_dir, "version.json"), 'r') as fp:
    ed_version_data = json.load(fp)
ed_v_data = ed_version_data['EDITOR']
ed_major = ed_v_data['MAJOR']
ed_minor = ed_v_data['MINOR']
ed_patch = ed_v_data['PATCH']
editor_version = '{}.{}.{}'.format(ed_major, ed_minor, ed_patch)
setuptools.setup(
    name="nxt-editor",
    version=editor_version,
    author="The nxt contributors",
    author_email="dev@opennxt.dev",
    description=desc,
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/nxt-dev/nxt_editor",
    packages=setuptools.find_packages(),
    python_requires='>=2.7, <3.11',
    install_requires=['nxt-core<1.0,>=0.14',
                      'qt.py==1.1',
                      'pyside2>=5.11,<=5.16'
                      ],
    package_data={
        # covers text nxt files
        "": ["*.nxt"],
        # Covers builtin, and full depth of resources
        "nxt_editor": ["version.json",
                       "integration/*",
                       "integration/*/*",
                       "integration/*/*/*",
                       "resources/*",
                       "resources/*/*",
                       "resources/*/*/*",
                       "resources/*/*/*/*"],
    }
)
