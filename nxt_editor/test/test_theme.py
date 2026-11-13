"""The editor looks the same standalone and in every host.

A host brings its own style, palette, fonts and screen scaling. The
editor's colors come from nxt_editor.theme, and its fonts are the ones
it ships, sized in pixels: a point is a different number of pixels on
macOS than on Windows, and in a host that scales its interface.
"""
# Builtin
import sys
import unittest

# External
from Qt import QtGui, QtWidgets

# Internal
from nxt_editor import theme
from nxt_editor.constants import FONTS, points_to_px

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


class Fonts(unittest.TestCase):

    def test_the_editors_fonts_are_sized_in_pixels(self):
        for font in (FONTS.default_font(), FONTS.monospace_font(9),
                     theme.font(), theme.font(15, mono=True)):
            self.assertGreater(font.pixelSize(), 0, font.toString())
            self.assertEqual(-1, font.pointSize(), font.toString())

    def test_a_size_in_points_is_its_size_at_96_dpi(self):
        self.assertEqual(13, points_to_px(10))
        self.assertEqual(FONTS.default_font(10).pixelSize(), 13)

    def test_they_are_the_shipped_faces(self):
        theme.register_fonts()
        families = QtGui.QFontDatabase.families()
        self.assertIn(FONTS.DEFAULT_FAMILY, families)
        self.assertIn(FONTS.MONOSPACE, families)
        styles = QtGui.QFontDatabase.styles(FONTS.DEFAULT_FAMILY)
        for style in ('Medium', 'Bold', 'Italic'):
            self.assertIn(style, styles)


class LayerColors(unittest.TestCase):

    def test_a_row_keeps_the_background_it_sets(self):
        # Lists show a layer by giving its row the layer's color, such as
        # the layers to save on close. A stylesheet rule for every row
        # would paint over it.
        import nxt_editor
        window = QtWidgets.QWidget()
        window.setStyleSheet(nxt_editor.stylesheet())
        layout = QtWidgets.QVBoxLayout(window)
        tree = QtWidgets.QTreeView()
        tree.setHeaderHidden(True)
        model = QtGui.QStandardItemModel(tree)
        item = QtGui.QStandardItem('layer')
        item.setBackground(QtGui.QBrush(QtGui.QColor('#991c24')))
        model.appendRow(item)
        tree.setModel(model)
        layout.addWidget(tree)
        window.resize(300, 100)
        window.show()
        try:
            for _ in range(5):
                app.processEvents()
            image = tree.viewport().grab().toImage()
            rect = tree.visualRect(model.index(0, 0))
            color = QtGui.QColor(image.pixel(rect.center()))
            self.assertEqual('#991c24', color.name())
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()


class OldColors(unittest.TestCase):

    def test_an_old_grey_depends_on_what_it_colors(self):
        sheet = theme.restyle('QFrame { background-color: #3E3E3E; '
                              'border: 1px solid #3E3E3E; '
                              'color: #F0F0F0; }')
        self.assertEqual('QFrame { background-color: %s; '
                         'border: 1px solid %s; color: %s; }'
                         % (theme.RAISED, theme.BORDER, theme.TEXT), sheet)

    def test_selection_colors_are_backgrounds(self):
        sheet = theme.restyle('a { selection-background-color: #1464A0; '
                              'selection-color: #F0F0F0; }')
        self.assertIn(theme.ACCENT_STRONG, sheet)
        self.assertIn(theme.TEXT, sheet)

    def test_other_colors_are_left_alone(self):
        sheet = 'a { color: #B14A4A; background: #12345678; }'
        self.assertEqual(sheet, theme.restyle(sheet))

    def test_names_are_filled_in(self):
        self.assertEqual('a { color: %s; }' % theme.TEXT,
                         theme.fill('a { color: {TEXT}; }'))
        # Braces of the stylesheet's own, and format fields, are not names.
        self.assertEqual('a {color: red} {0}',
                         theme.fill('a {color: red} {0}'))


if __name__ == '__main__':
    unittest.main()
