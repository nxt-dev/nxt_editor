"""The Maya module ships jedi, in the range setup.py promises.

Standalone, jedi comes from `pip install nxt-editor[completion]`. A Maya
module folder has no pip step, so Python Analysis was greyed out in Maya
unless somebody pip installed into mayapy or copied the packages in by hand.
The build graph now installs jedi into the module's scripts folder.

Two places name the jedi versions that work: the extra in setup.py and the
build graph. These tests keep them the same, and keep the step where it has
to be. Nothing here runs the build or needs the network.
"""
# Built-in
import json
import os
import re
import unittest

REPO_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
BUILD_GRAPH = os.path.join(REPO_DIR, 'build', 'make_maya_plugin.nxt')
SETUP_FILE = os.path.join(REPO_DIR, 'setup.py')
STEP = '/make_module_folder/completion_deps'


@unittest.skipUnless(os.path.isfile(BUILD_GRAPH) and os.path.isfile(SETUP_FILE),
                     'The build graph only exists in a source checkout')
class MayaModuleShipsJedi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(BUILD_GRAPH) as file_object:
            cls.nodes = json.load(file_object)['nodes']

    def test_requirement_matches_the_setup_extra(self):
        with open(SETUP_FILE) as file_object:
            setup_source = file_object.read()
        match = re.search(r"'completion':\s*\[\s*'([^']+)'\s*\]", setup_source)
        self.assertIsNotNone(match, 'setup.py lost its completion extra')
        requirement = self.nodes[STEP]['attrs']['requirement']['value']
        self.assertEqual(
            match.group(1), requirement,
            'The jedi the Maya module ships has drifted from the one '
            'pip install nxt-editor[completion] asks for')

    def test_step_runs_before_the_clean_up(self):
        # clean_up removes the caches an install leaves behind, and the
        # module folder has to exist first, which copy_source sees to.
        order = self.nodes['/make_module_folder']['child_order']
        step = STEP.rsplit('/', 1)[-1]
        self.assertIn(step, order)
        self.assertLess(order.index('copy_source'), order.index(step))
        self.assertLess(order.index(step), order.index('clean_up'))

    def test_only_released_wheels_are_installed(self):
        # A source build could run somebody's setup.py on the release
        # machine, and could differ between two builds of the same tag.
        code = '\n'.join(self.nodes[STEP]['code'])
        self.assertIn("'--only-binary', ':all:'", code)
        self.assertIn("'--target'", code)


if __name__ == '__main__':
    unittest.main()
