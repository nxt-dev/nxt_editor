import setuptools
import json

with open("README.md", "r") as fh:
    long_description = fh.read()

desc = ("A general purpose code compositor designed for rigging, "
        "scene assembly, and automation. (node execution tree)")

with open("nxt/version.json", 'r') as fh:
    version_data = json.load(fh)
api_v_data = version_data['API']
api_major = api_v_data['MAJOR']
api_minor = api_v_data['MINOR']
api_patch = api_v_data['PATCH']
api_version = 'api_v{}.{}.{}'.format(api_major, api_minor, api_patch)

with open("nxt/ui/version.json", 'r') as fh:
    ed_version_data = json.load(fh)
ed_v_data = ed_version_data['EDITOR']
ed_major = ed_v_data['MAJOR']
ed_minor = ed_v_data['MINOR']
ed_patch = ed_v_data['PATCH']
editor_version = 'editor_v{}.{}.{}'.format(ed_major, ed_minor, ed_patch)

version = editor_version + '-' + api_version
setuptools.setup(
    name="nxt",
    version=version,
    author="the nxt contributors",
    author_email="what@is.email",
    description=desc,
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/SunriseProductions/nxt",
    packages=setuptools.find_packages(),
    python_requires='>=2.7, <3',
    install_requires=['qt.py', 'pyside2'],
    entry_points={
        'console_scripts': [
            'nxt=nxt.cli:main',
        ],
    },
    package_data={
        # covers text nxt files
        "": ["*.nxt"],
        # Covers builtin, and full depth of resources
        "nxt": ["version.json",
                "ui/version.json",
                "builtin/*.nxt",
                "ui/resources/*",
                "ui/resources/*/*",
                "ui/resources/*/*/*",
                "ui/resources/*/*/*/*"],
    }
)
