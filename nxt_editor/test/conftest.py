"""Test setup that has to happen before any test module is imported.

These tests build real widgets, and a CI runner often has no window
server to give them: one that runs as a service has none, on macOS and
Windows as much as on Linux. Qt aborts rather than falling back, so it is
told to render offscreen before anything creates a QApplication.

Only under CI. On a workstation the tests use the real display, which is
also the only way to look at what they are doing.
"""
import os

if os.environ.get('CI') and not os.environ.get('QT_QPA_PLATFORM'):
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
