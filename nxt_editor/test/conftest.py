"""Test setup that has to happen before any test module is imported.

These tests build real widgets, and a CI runner often has no window
server to give them: one that runs as a service has none, on macOS and
Windows as much as on Linux. Qt aborts rather than falling back, so it is
told to render offscreen before anything creates a QApplication.

Only under CI. On a workstation the tests use the real display, which is
also the only way to look at what they are doing.

After each module, the windows the tests leave behind are kept rather
than freed. See keep_windows.
"""
import gc
import os

import pytest

if os.environ.get('CI') and not os.environ.get('QT_QPA_PLATFORM'):
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'


#: Every window a test left behind, for the rest of the run.
_KEPT = []


@pytest.fixture(autouse=True, scope='module')
def keep_windows():
    """Hide the windows a test module leaves behind, and never free them.

    A test that drops its last reference to a window hands the whole widget
    tree to Python's garbage collector, which frees the pieces in whatever
    order it finds them, at whatever moment something else collects. On
    macOS that segfaulted every run since 4.3.0, always inside a
    gc.collect() in test_layer_tree_indices that had nothing to do with it.

    Deleting them through Qt instead is no better: tearing down an editor
    window in the middle of a run corrupts the heap on Windows as well.
    The hosts never do that. They close the window and it lives until the
    application exits, so that is what happens here too.
    """
    yield
    for widget in _keep_all():
        if widget.isVisible():
            widget.hide()


@pytest.fixture(autouse=True)
def keep_windows_after_each_test():
    """The same, after every test, and out of the collector's reach.

    Nothing is hidden here: some classes build one window in setUpClass
    and share it between their tests.

    Keeping the windows is not enough on its own. Every test also leaves
    stage models, layer models and the command port threads they start,
    with no Qt parent, and the collector freeing those from a test long
    finished is as able to crash as a window is. gc.freeze() moves
    everything that exists now out of its reach for good, so a later
    gc.collect() only ever meets what that test made itself, which is
    what the tests that call it are asking about.
    """
    yield
    _keep_all()
    gc.freeze()


def _keep_all():
    try:
        from Qt import QtWidgets
    except ImportError:
        return []
    app = QtWidgets.QApplication.instance()
    if app is None:
        return []
    widgets = app.topLevelWidgets()
    for widget in widgets:
        if widget not in _KEPT:
            _KEPT.append(widget)
    return widgets
