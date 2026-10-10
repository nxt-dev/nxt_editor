"""The DCC plugins report the editor's version, not one of their own.

They used to carry their own numbers and both had rotted: the maya plug-in
hardcoded 0.1.0 next to a commented out note about reading version.json,
the maya build graph substituted that same 0.1.0 into the module file, the
drag installer never substituted anything so the placeholder went into the
.mod verbatim, and the unreal manifest still said 0.1.0 while the editor
was on 4.x.

Nothing here needs a DCC. The maya plug-in itself imports maya.cmds so it
cannot be imported outside maya, but it takes its version from the same
helper these tests cover.
"""
# Built-in
import json
import os
import unittest

# Internal
from nxt_editor.integration import plugin_version

EDITOR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_FILE = os.path.join(EDITOR_DIR, 'version.json')
INTEGRATION = os.path.join(EDITOR_DIR, 'integration')
UPLUGIN = os.path.join(INTEGRATION, 'unreal', 'nxt_unreal.uplugin')
MOD_FILE = os.path.join(INTEGRATION, 'maya', 'nxt.mod')
DRAG_INSTALLER = os.path.join(INTEGRATION, 'maya', 'drag_into_maya.py')


def editor_version():
    with open(VERSION_FILE) as file_object:
        editor = json.load(file_object)['EDITOR']
    return '{MAJOR}.{MINOR}.{PATCH}'.format(**editor)


class PluginsReportTheEditorVersion(unittest.TestCase):

    def test_helper_matches_version_file(self):
        self.assertEqual(editor_version(), plugin_version())

    def test_helper_is_not_the_empty_fallback(self):
        # plugin_version returns "" when it cannot read the file, and the
        # callers turn that into 0.0.0. Catch a broken path here rather
        # than shipping a plugin that claims to be 0.0.0.
        self.assertNotEqual('', plugin_version())

    def test_unreal_manifest_matches(self):
        with open(UPLUGIN) as file_object:
            manifest = json.load(file_object)
        self.assertEqual(
            editor_version(), manifest['VersionName'],
            'nxt_unreal.uplugin VersionName has drifted from version.json')

    def test_maya_module_file_is_still_a_template(self):
        # The build and the drag installer both substitute this. A literal
        # version here would mean someone baked one in by hand again.
        with open(MOD_FILE) as file_object:
            contents = file_object.read()
        self.assertIn('<VERSION>', contents)

    def test_drag_installer_substitutes_the_placeholder(self):
        # It filled in the path but not the version, so a drag installed
        # module file carried "<VERSION>" into maya.
        with open(DRAG_INSTALLER) as file_object:
            source = file_object.read()
        self.assertIn("replace('<VERSION>'", source)
        self.assertIn("replace('<NXT_MOD_PATH>'", source)


if __name__ == '__main__':
    unittest.main()
