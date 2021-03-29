# Built-in
import logging

# External
from Qt import QtWidgets
from Qt import QtGui
from Qt import QtCore

# Internal
from . import colors
from nxt import nxt_path, nxt_node
import nxt_editor
from nxt_editor.node_graphics_item import MIN_LOD

logger = logging.getLogger(nxt_editor.LOGGER_NAME)


class AttrConnectionGraphic(QtWidgets.QGraphicsLineItem):
    """Attribute connection graphics display the presence of "source_path"
    in the "target_path" attribute.
    """
    ATTR_THICKNESS = 1.5
    EXEC_THICKNESS = 3
    # INFLATE_MULT = 1.7

    def __init__(self, model, view, source_path='', target_path=''):
        super(AttrConnectionGraphic, self).__init__()
        # self.setAcceptHoverEvents(True)
        # self.is_hovered = False
        self.thickness = self.ATTR_THICKNESS
        self.color = QtCore.Qt.gray
        self.pen_style = QtCore.Qt.SolidLine

        self.model = model
        self.view = view
        # If both directions are not given, to the cursor is implied.
        if not (source_path or target_path):
            raise ValueError("Must initialize a connection graphic with at "
                             "least one path, source or target.")
        self.src_path = source_path
        self.tgt_path = target_path
        self.src_node_path = nxt_path.node_path_from_attr_path(self.src_path)
        self.src_attr_name = nxt_path.attr_name_from_attr_path(self.src_path)
        self.tgt_node_path = nxt_path.node_path_from_attr_path(self.tgt_path)
        self.tgt_attr_name = nxt_path.attr_name_from_attr_path(self.tgt_path)
        self.calculate_draw_details()

    def calculate_draw_details(self):
        self.thickness = self.ATTR_THICKNESS
        self.color = QtCore.Qt.gray
        self.pen_style = QtCore.Qt.SolidLine
        if self.src_attr_name:
            disp_layer = self.model.comp_layer
            type_ = self.model.get_node_attr_type(self.src_node_path,
                                                  self.src_attr_name,
                                                  disp_layer)
            self.color = colors.ATTR_COLORS.get(type_, QtCore.Qt.gray)
        if self.tgt_path:
            if self.tgt_attr_name == nxt_node.INTERNAL_ATTRS.EXECUTE_IN:
                self.thickness = self.EXEC_THICKNESS
                self.color = QtCore.Qt.white
            elif self.tgt_attr_name == nxt_node.INTERNAL_ATTRS.INSTANCE_PATH:
                self.pen_style = QtCore.Qt.DashDotDotLine
            elif self.tgt_attr_name:
                if self.model.node_attr_value_is_complex(self.tgt_node_path,
                                                         self.tgt_attr_name):
                    self.pen_style = QtCore.Qt.DashLine
                # Verify if attr we're connecting to has multiple tokens
        else:
            src_attr_name = nxt_path.attr_name_from_attr_path(self.src_path)
            if not src_attr_name:
                self.thickness = self.EXEC_THICKNESS
                self.color = QtCore.Qt.white
        self.rebuild_line()

    def rebuild_line(self):
        src_node = self.view.get_node_graphic(self.src_node_path)
        tgt_node = self.view.get_node_graphic(self.tgt_node_path)
        if src_node:
            self.src_pos = src_node.get_attr_out_pos(self.src_attr_name,
                                                     scene=True)
            if not self.src_pos:
                exec_attr = nxt_node.INTERNAL_ATTRS.EXECUTE_IN
                self.src_pos = src_node.get_attr_out_pos(exec_attr,
                                                         scene=True)
        else:
            self.src_pos = self.view.mouse_scene_pos
        if tgt_node:
            self.tgt_pos = tgt_node.get_attr_in_pos(self.tgt_attr_name,
                                                    scene=True)
            if not self.tgt_pos:
                exec_attr = nxt_node.INTERNAL_ATTRS.EXECUTE_IN
                self.tgt_pos = tgt_node.get_attr_in_pos(exec_attr,
                                                        scene=True)
        else:
            self.tgt_pos = self.view.mouse_scene_pos
        self.setLine(QtCore.QLineF(self.src_pos, self.tgt_pos))
        # I don't want this
        self.update()

    def paint(self, painter, option, widget):
        lod = QtWidgets.QStyleOptionGraphicsItem.levelOfDetailFromTransform(
            painter.worldTransform())
        if lod > MIN_LOD:
            painter.setRenderHints(QtGui.QPainter.Antialiasing |
                                   QtGui.QPainter.SmoothPixmapTransform)
            thick_mult = 1
            pen_style = self.pen_style
        else:
            painter.setRenderHints(QtGui.QPainter.Antialiasing |
                                   QtGui.QPainter.SmoothPixmapTransform, False)
            thick_mult = 3
            pen_style = QtCore.Qt.PenStyle.SolidLine
        pen = QtGui.QPen(self.color, self.thickness * thick_mult, pen_style)
        # if self.tgt_path in self.model.selection:
        #    pen.setColor(colors.SELECTED)
        # elif self.is_hovered:
        #    pen.setWidthF(self.INFLATE_MULT * self.thickness)
        self.setPen(pen)
        super(AttrConnectionGraphic, self).paint(painter, option, widget)

    # def hoverEnterEvent(self, event):
    #    self.is_hovered = True
    #    self.update()

    # def hoverLeaveEvent(self, event):
    #    self.is_hovered = False
    #    self.update()
