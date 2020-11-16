# Built-in
import unittest

# Internal
import nxt.plugin_loader


class PluginTests(unittest.TestCase):

    def test_plugins(self):
        for mod in nxt.plugin_loader._nxt_loaded_plugin_modules:
            testsuite = unittest.TestLoader().loadTestsFromModule(mod)
            if not testsuite._tests:
                continue
            results = unittest.TextTestRunner(verbosity=1).run(testsuite)
            if results.failures or results.errors:
                # Fixme: I doubt this is the right way
                try:
                    excp = results.failures[0][0].failureException
                    tb = results.failures[0][1]
                except IndexError:
                    excp = results.errors[0][0].failureException
                    tb = results.errors[0][1]
                raise excp(tb)
