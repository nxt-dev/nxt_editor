"""None, True and False are kept from being freed where PySide6 runs their
counts down, see pyside_refcount."""
# Builtin
import sys
import unittest
from unittest import mock

# Internal
from nxt_editor import pyside_refcount


class Needed(unittest.TestCase):

    def where(self, binding='PySide6', version=(3, 11), platform='linux',
              machine='aarch64'):
        with mock.patch.object(sys, 'platform', platform), \
                mock.patch.object(sys, 'version_info', version), \
                mock.patch('platform.machine', return_value=machine):
            return pyside_refcount.needed(binding)

    def test_pyside6_on_linux_arm_before_312(self):
        self.assertTrue(self.where())
        self.assertTrue(self.where(machine='arm64'))

    def test_not_from_312(self):
        self.assertFalse(self.where(version=(3, 12)))
        self.assertFalse(self.where(version=(3, 13)))

    def test_not_elsewhere(self):
        self.assertFalse(self.where(machine='x86_64'))
        self.assertFalse(self.where(platform='darwin', machine='arm64'))
        self.assertFalse(self.where(platform='win32', machine='AMD64'))

    def test_not_with_another_binding(self):
        self.assertFalse(self.where(binding='PySide2'))


class Protect(unittest.TestCase):

    @unittest.skipIf(sys.version_info >= (3, 12),
                     'already immortal, with a count of its own')
    def test_their_counts_cannot_run_down(self):
        pyside_refcount.protect()
        for obj in pyside_refcount.SINGLETONS:
            self.assertGreaterEqual(sys.getrefcount(obj),
                                    pyside_refcount.COUNT)


if __name__ == '__main__':
    unittest.main()
