"""Test setup that has to happen before any test module is imported.

These tests build real widgets, and the studio runners have no window
server to give them: a self hosted runner runs as a service, on macOS and
Windows as much as on Linux. Qt aborts rather than falling back, so it is
told to render offscreen before anything creates a QApplication.

Only under CI. On a workstation the tests use the real display, which is
also the only way to look at what they are doing.
"""
import os

if os.environ.get('CI') and not os.environ.get('QT_QPA_PLATFORM'):
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
