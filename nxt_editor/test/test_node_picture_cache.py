"""The editor keeps room for the pictures of a big graph's nodes."""
import unittest

from Qt import QtGui, QtWidgets

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from nxt_editor import main_window  # noqa: E402


class NodePictureCache(unittest.TestCase):
    def setUp(self):
        self.before = QtGui.QPixmapCache.cacheLimit()
        self.addCleanup(QtGui.QPixmapCache.setCacheLimit, self.before)

    def test_it_is_raised(self):
        QtGui.QPixmapCache.setCacheLimit(10240)
        main_window.make_room_for_node_pictures()
        self.assertEqual(main_window.NODE_PICTURE_CACHE_KB,
                         QtGui.QPixmapCache.cacheLimit())

    def test_a_larger_one_is_kept(self):
        larger = main_window.NODE_PICTURE_CACHE_KB * 2
        QtGui.QPixmapCache.setCacheLimit(larger)
        main_window.make_room_for_node_pictures()
        self.assertEqual(larger, QtGui.QPixmapCache.cacheLimit())
