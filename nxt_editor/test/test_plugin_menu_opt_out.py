"""A DCC plugin can be told to leave nxt's own menu out.

Studios that open the editor from their pipeline menu ended up patching the
plug-in to comment the menu out, and redoing the patch on every update. The
env var NXT_NO_MENU does the same without touching the file.

Nothing here needs a DCC. The maya plug-in imports maya.cmds so it cannot be
imported outside maya, but it takes the decision from the helper these tests
cover, and the last test checks that it asks.
"""
# Built-in
import os
import unittest

# Internal
from nxt_editor import integration

EDITOR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAYA_PLUGIN = os.path.join(EDITOR_DIR, 'integration', 'maya', 'plug-ins',
                           'nxt_maya.py')


class MenuOptOut(unittest.TestCase):

    def setUp(self):
        self.before = os.environ.pop(integration.NO_MENU_ENV_VAR, None)

    def tearDown(self):
        os.environ.pop(integration.NO_MENU_ENV_VAR, None)
        if self.before is not None:
            os.environ[integration.NO_MENU_ENV_VAR] = self.before

    def test_menu_is_wanted_by_default(self):
        self.assertTrue(integration.wants_menu())

    def test_set_means_no_menu(self):
        for value in ('1', 'true', 'True', 'yes', 'anything'):
            os.environ[integration.NO_MENU_ENV_VAR] = value
            self.assertFalse(integration.wants_menu(), value)

    def test_falsy_strings_keep_the_menu(self):
        # NXT_NO_MENU=0 reads as "no, I do want it" to anyone setting it.
        for value in ('', '0', 'false', 'False', 'no', 'off', ' 0 '):
            os.environ[integration.NO_MENU_ENV_VAR] = value
            self.assertTrue(integration.wants_menu(), repr(value))

    def test_maya_plugin_asks_before_building_its_menu(self):
        with open(MAYA_PLUGIN) as file_object:
            source = file_object.read()
        asks = source.index('if not wants_menu():')
        builds = source.index("cmds.menu('nxt'")
        registers = source.index('pluginFn.registerCommand(')
        # The command is registered first, so it survives the opt out.
        self.assertLess(registers, asks)
        self.assertLess(asks, builds)


if __name__ == '__main__':
    unittest.main()
