"""The README has to say the same thing setup.py does.

The supported python range is written in two places, and the one people
read is the one nothing checks. It had drifted to claiming no ceiling at
all long after setup.py had one. This fails the build instead of letting
the next bump quietly do it again.

The badges at the top of the README are checked the same way: the
version badge against version.json, the python badges against the same
range, and every workflow badge against a workflow that exists. Static
badges go stale without anyone noticing otherwise.

Skipped when run against an installed copy, where neither file ships.
"""
# Built-in
import json
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
SETUP_PY = os.path.join(REPO_ROOT, 'setup.py')
README = os.path.join(REPO_ROOT, 'README.md')
VERSION_JSON = os.path.join(REPO_ROOT, 'nxt_editor', 'version.json')
WORKFLOWS = os.path.join(REPO_ROOT, '.github', 'workflows')

# ">=3.7, <3.14"
REQUIRES_RE = re.compile(r"python_requires\s*=\s*['\"]"
                         r">=\s*(\d+)\.(\d+)\s*,\s*<\s*(\d+)\.(\d+)")
# "- Python [3.7](...) to [3.13](...)"
README_RE = re.compile(r"^- Python \[(\d+)\.(\d+)\][^\n]*?to \[(\d+)\.(\d+)\]",
                       re.MULTILINE)

VERSION_BADGE_RE = re.compile(r"img\.shields\.io/badge/version-([\d.]+)-")
PYTHON_BADGE_RE = re.compile(r"img\.shields\.io/badge/python-(\d+)\.(\d+)-")
WORKFLOW_BADGE_RE = re.compile(r"/actions/workflows/([\w.-]+)/badge\.svg")


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

    def test_python_badges_cover_the_range(self):
        low, high = self.declared_range()
        wanted = {(low[0], minor) for minor in range(low[1], high[1] + 1)}
        badges = {(int(a), int(b))
                  for a, b in PYTHON_BADGE_RE.findall(read(README))}
        self.assertEqual(sorted(wanted), sorted(badges),
                         'the python badges are not the supported range')

    def test_version_badge_is_the_version(self):
        with open(VERSION_JSON) as file_object:
            editor = json.load(file_object)['EDITOR']
        version = '{MAJOR}.{MINOR}.{PATCH}'.format(**editor)
        badges = VERSION_BADGE_RE.findall(read(README))
        self.assertEqual(badges, [version],
                         'the version badge is not version.json')

    def test_workflow_badges_point_at_workflows(self):
        names = WORKFLOW_BADGE_RE.findall(read(README))
        self.assertTrue(names, 'no workflow badges')
        for name in names:
            self.assertTrue(os.path.isfile(os.path.join(WORKFLOWS, name)),
                            'badge for a workflow that does not exist: '
                            + name)


if __name__ == '__main__':
    unittest.main()
