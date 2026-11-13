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
from Qt import QtCore, QtGui, QtWidgets

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
            # macOS hands back a grab in the display's color profile, so a
            # saturated red comes back a few steps off. The row is still
            # the layer's red, not the panel's grey a stylesheet rule for
            # every row would leave.
            expected = QtGui.QColor('#991c24')
            for got, want in ((color.red(), expected.red()),
                              (color.green(), expected.green()),
                              (color.blue(), expected.blue())):
                self.assertLess(abs(got - want), 24, color.name())
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()


    def test_a_rows_checkbox_shows_on_its_color(self):
        # Layers to save on close are checked off on rows of their layer's
        # color, and the box shows without the mouse over it.
        import nxt_editor
        from nxt_editor.dialogs import CheckDelegate
        window = QtWidgets.QWidget()
        window.setStyleSheet(nxt_editor.stylesheet())
        layout = QtWidgets.QVBoxLayout(window)
        tree = QtWidgets.QTreeView()
        tree.setHeaderHidden(True)
        tree.setItemDelegate(CheckDelegate(tree))
        model = QtGui.QStandardItemModel(tree)
        item = QtGui.QStandardItem('layer')
        item.setCheckable(True)
        item.setCheckState(QtCore.Qt.Unchecked)
        item.setBackground(QtGui.QBrush(QtGui.QColor('#99cc33')))
        model.appendRow(item)
        tree.setModel(model)
        layout.addWidget(tree)
        window.resize(300, 100)
        window.show()
        try:
            for _ in range(5):
                app.processEvents()
            option = QtWidgets.QStyleOptionViewItem()
            option.initFrom(tree)
            option.rect = tree.visualRect(model.index(0, 0))
            option.widget = tree
            delegate = tree.itemDelegate()
            delegate.initStyleOption(option, model.index(0, 0))
            box = tree.style().subElementRect(
                QtWidgets.QStyle.SE_ItemViewItemCheckIndicator, option, tree)
            image = tree.viewport().grab().toImage()
            color = QtGui.QColor(image.pixel(box.center()))
            self.assertEqual(theme.GRAPH, color.name())
        finally:
            window.close()
            window.deleteLater()
            app.processEvents()


class ReadableText(unittest.TestCase):

    def test_bright_layer_colors_get_dark_text(self):
        for bright in ('#99CC33', '#CFA305', '#F38B00', '#51B848',
                       '#00A5E6', '#ffffff'):
            self.assertEqual(theme.DARK_TEXT,
                             theme.readable_text(bright).name(), bright)

    def test_deep_and_mid_colors_keep_light_text(self):
        for deep in ('#991C24', '#0052AA', '#6E33BB', '#E83723',
                     '#119B77', '#787878'):
            self.assertEqual(theme.NODE_TEXT,
                             theme.readable_text(deep).name(), deep)

    def test_the_text_picked_reads_well(self):
        # Every layer color, with the text picked for it, passes WCAG's
        # contrast for large text.
        from nxt_editor import colors
        for layer_color in colors.LAYER_COLORS:
            text = theme.readable_text(layer_color)
            self.assertGreaterEqual(theme.contrast(layer_color, text), 3.0,
                                    layer_color.name())


class Stripes(unittest.TestCase):

    def test_they_darken_part_of_what_they_cross(self):
        image = QtGui.QImage(120, 30, QtGui.QImage.Format_ARGB32_Premultiplied)
        base = QtGui.QColor('#00a881')
        image.fill(base)
        painter = QtGui.QPainter(image)
        theme.paint_stripes(painter, QtCore.QRectF(0, 0, 120, 30), base)
        painter.end()
        seen = {QtGui.QColor(image.pixel(x, 15)).name()
                for x in range(120)}
        self.assertIn(base.name(), seen)
        darker = [c for c in seen if theme.luminance(c) <
                  theme.luminance(base) * 0.7]
        self.assertTrue(darker)


class ExecuteIcons(unittest.TestCase):

    def test_each_is_drawn_and_goes_green_under_the_mouse(self):
        from nxt_editor import exec_icons
        for icon in (exec_icons.execute_selected(),
                     exec_icons.execute_from(),
                     exec_icons.execute_hierarchy()):
            self.assertFalse(icon.isNull())
            normal = icon.pixmap(QtCore.QSize(17, 16)).toImage()
            active = icon.pixmap(QtCore.QSize(17, 16),
                                 QtGui.QIcon.Active).toImage()
            self.assertNotEqual(normal, active)


class RenameBox(unittest.TestCase):

    def test_it_opens_where_it_is_put(self):
        from nxt_editor.label_edit import NameEditDialog
        geometry = QtCore.QRect(300, 240, 260, 40)
        dialog = NameEditDialog(name='node', geometry=geometry)
        try:
            dialog.show()
            app.processEvents()
            self.assertEqual(geometry.topLeft(), dialog.geometry().topLeft())
        finally:
            dialog.reject()
            dialog.deleteLater()
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
