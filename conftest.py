"""Test setup that has to happen before nxt_editor is imported.

The tests get a user directory of their own, unless NXT_USER_DIR already
names one. The editor keeps its preferences, caches and recent files there,
and the tests change all of them, so running them against ~/nxt rewrote the
settings of whoever ran them, and two runs at once corrupted each other's
cache files.

nxt reads NXT_USER_DIR once, when it is first imported, and pytest imports
the nxt_editor package before the conftest.py inside it, so this one sits
at the top of the repository where pytest finds it first.
"""
import os
import shutil
import tempfile

#: The user directory made for this run, removed again when it ends.
_USER_DIR = None
if not os.environ.get('NXT_USER_DIR'):
    _USER_DIR = tempfile.mkdtemp(prefix='nxt_test_user_')
    os.environ['NXT_USER_DIR'] = _USER_DIR


def pytest_sessionfinish(session, exitstatus):
    if _USER_DIR:
        shutil.rmtree(_USER_DIR, ignore_errors=True)
