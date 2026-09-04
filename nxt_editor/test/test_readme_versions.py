"""The README has to say the same thing setup.py does.

The supported python range is written in two places, and the one people
read is the one nothing checks. It had drifted to claiming no ceiling at
all long after setup.py had one. This fails the build instead of letting
the next bump quietly do it again.

Skipped when run against an installed copy, where neither file ships.
"""
# Built-in
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
SETUP_PY = os.path.join(REPO_ROOT, 'setup.py')
README = os.path.join(REPO_ROOT, 'README.md')

# ">=3.7, <3.14"
REQUIRES_RE = re.compile(r"python_requires\s*=\s*['\"]"
                         r">=\s*(\d+)\.(\d+)\s*,\s*<\s*(\d+)\.(\d+)")
# "- Python [3.7](...) to [3.13](...)"
README_RE = re.compile(r"^- Python \[(\d+)\.(\d+)\][^\n]*?to \[(\d+)\.(\d+)\]",
                       re.MULTILINE)


def read(path):
    with open(path) as file_object:
        return file_object.read()


class ReadmeMatchesSetup(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not (os.path.isfile(SETUP_PY) and os.path.isfile(README)):
            raise unittest.SkipTest('not running from a source checkout')

    def declared_range(self):
        """(lowest, highest) supported python, from setup.py.

        python_requires states the ceiling as the first *unsupported*
        version, so the highest supported one is the minor below it.
        """
        match = REQUIRES_RE.search(read(SETUP_PY))
        self.assertIsNotNone(match, 'could not read python_requires')
        low = (int(match.group(1)), int(match.group(2)))
        excl = (int(match.group(3)), int(match.group(4)))
        return low, (excl[0], excl[1] - 1)

    def documented_range(self):
        """(lowest, highest) supported python, from the README."""
        match = README_RE.search(read(README))
        self.assertIsNotNone(
            match, 'README needs a line like "- Python [3.7](...) to '
                   '[3.13](...)" stating the supported range')
        return ((int(match.group(1)), int(match.group(2))),
                (int(match.group(3)), int(match.group(4))))

    def test_readme_states_the_supported_range(self):
        declared_low, declared_high = self.declared_range()
        documented_low, documented_high = self.documented_range()
        fmt = '%d.%d'
        self.assertEqual(
            fmt % declared_low, fmt % documented_low,
            'README floor disagrees with setup.py python_requires')
        self.assertEqual(
            fmt % declared_high, fmt % documented_high,
            'README ceiling disagrees with setup.py python_requires')


if __name__ == '__main__':
    unittest.main()
