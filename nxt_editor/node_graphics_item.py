# Built-in
import math
import logging
import textwrap
import sys
from collections import OrderedDict

# External
from Qt import QtWidgets
from Qt import QtGui
from Qt import QtCore
from PySide2 import __version_info__ as qt_version

# Internal
import nxt_editor
from nxt import nxt_path, nxt_node
from nxt.nxt_layer import LAYERS
from . import colors
from nxt.stage import INTERNAL_ATTRS
from .label_edit import NameEditDialog
from .user_dir import USER_PREF, user_prefs


logger = logging.getLogger(nxt_editor.LOGGER_NAME)

MIN_LOD = user_prefs.get(USER_PREF.LOD, .4)

_pyside_version = qt_version


if _pyside_version[1] < 11:
    graphic_type = QtWidgets.QGraphicsItem
else:
    graphic_type = QtWidgets.QGraphicsObject


class NodeGraphicsItem(graphic_type):
    """The graphics item used to represent nodes in the graph. Contains
    instances of NodeGraphicsPlug for each attribute on the associated node.
    Contains functionality for arranging children into stacks.
    """

    ATTR_PLUG_RADIUS = 4
    EXEC_PLUG_RADIUS = 6
    ROUND_X = 2.
    ROUND_Y = 2.

    def __init__(self, model, node_path, view):
        super(NodeGraphicsItem, self).__init__()
        self.count = 0
        self.dim_factor = 100
        self.colors = [QtGui.QColor(QtCore.Qt.darkGray)]
        self.color_alpha = 1.0
        # graph settings
        self.node_path = node_path
        self.model = model
        self.view = view

        # item settings
        self.setCacheMode(QtWidgets.QGraphicsItem.DeviceCoordinateCache)

        self.setFlags(QtWidgets.QGraphicsItem.ItemIsMovable |
                      QtWidgets.QGraphicsItem.ItemIsFocusable |
                      QtWidgets.QGraphicsItem.ItemIsSelectable |
                      QtWidgets.QGraphicsItem.ItemSendsScenePositionChanges |
                      QtWidgets.QGraphicsItem.ItemNegativeZStacksBehindParent)
        self.setAcceptHoverEvents(True)

        # draw settings
        self.title_font = QtGui.QFont("Roboto Mono", 14)
        self.attr_font = QtGui.QFont("Roboto Mono", 9)
        self.title_rect_height = 39
        self.attr_rect_height = 26
        self.attr_rect_opacity = 0.9
        self.attr_plug_side_margin = 0
        self.plug_selection_range_mult = 1.1
        self.max_width = 260
        self.stack_offset = 20
        self.is_break = False
        self.is_start = False
        self.start_color = colors.ERROR
        self.is_proxy = False
        self.locked = False
        self.is_real = True
        self.attr_dots = [False, False, False]
        self.error_list = []
        self.error_item = None
        self.is_build_focus = False

        # local attributes
        self.user_attr_names = []
        self._attribute_draw_details = OrderedDict()
        self._attr_plug_graphics = {}
        self.exec_out_plug = NodeExecutionPlug(self.model, self.node_path, is_input=False, parent=self)
        self.exec_in_plug = NodeExecutionPlug(self.model, self.node_path, is_input=True, parent=self)
        self.is_hovered = False
        self.collapse_state = False
        self.collapse_arrows = []
        self.node_enabled = None
        self.node_instance = None

        self.model.build_idx_changed.connect(self.update_build_focus)
        self.model.executing_changed.connect(self.update_build_focus)
        # draw node
        self.update_from_model()

        # Setup groups
        # In
        self.in_anim_group = QtCore.QParallelAnimationGroup()
        self.in_anim_group.finished.connect(self.finished_anim)
        # Out
        self.out_anim_group = QtCore.QParallelAnimationGroup()
        self.out_anim_group.finished.connect(self.finished_anim)

    def _setup_anim_properties(self):
        # Position anim property
        self.pos_anim = QtCore.QPropertyAnimation(self, b"pos", self)
        # Set graphics effect
        effect = QtWidgets.QGraphicsOpacityEffect(self)
        effect.setOpacity(1)
        self.setGraphicsEffect(effect)
        # Opacity anim property
        self.opacity_anim = QtCore.QPropertyAnimation(effect, b"opacity",
                                                      effect)
        # Lower power caching
        self.setCacheMode(QtWidgets.QGraphicsItem.ItemCoordinateCache)

    def setup_in_anim(self):
        self._setup_anim_properties()
        self.in_anim_group.addAnimation(self.pos_anim)
        self.in_anim_group.addAnimation(self.opacity_anim)

    def setup_out_anim(self):
        self._setup_anim_properties()
        self.out_anim_group.addAnimation(self.pos_anim)
        self.out_anim_group.addAnimation(self.opacity_anim)

    def finished_anim(self):
        self.setGraphicsEffect(None)
        self.in_anim_group.clear()
        self.out_anim_group.clear()
        self.setCacheMode(QtWidgets.QGraphicsItem.DeviceCoordinateCache)
        self.view.update()
        self.view._animating.remove(self)

    def get_is_animating(self):
        i = self.in_anim_group.State.Running == self.in_anim_group.state()
        o = self.out_anim_group.State.Running == self.out_anim_group.state()
        return i or o

    def anim_into_place(self, end_pos):
        if self.get_is_animating():
            return
        if end_pos == self.pos():
            return
        self.view._animating.append(self)
        if self.view.do_animations:
            self.setup_in_anim()
        else:
            self.setPos(end_pos)
            self.in_anim_group.finished.emit()
            return

        self.opacity_anim.setStartValue(0)
        self.opacity_anim.setEndValue(1)
        self.opacity_anim.setDuration(80)

        curve = QtCore.QEasingCurve(QtCore.QEasingCurve.OutBack)
        curve.setAmplitude(.8)
        self.pos_anim.setEasingCurve(curve)

        self.pos_anim.setDuration(100)
        self.pos_anim.setEndValue(end_pos)
        self.in_anim_group.start()

    def anim_out(self):
        if self.get_is_animating():
            return
        self.view._animating.append(self)
        if self.view.do_animations:
            self.setup_out_anim()
        else:
            self.out_anim_group.finished.emit()
            return
        self.setCacheMode(QtWidgets.QGraphicsItem.ItemCoordinateCache)
        self.opacity_anim.setStartValue(1)
        self.opacity_anim.setEndValue(0)
        self.opacity_anim.setDuration(80)

        self.pos_anim.setDuration(80)
        self.pos_anim.setEasingCurve(QtCore.QEasingCurve.Linear)
        x_move = self.stack_offset * -1 * .5
        if not self.parentItem() or not self.parentItem().parentItem():
            y_move = 0.0
        else:
            y_move = (self.parentItem().boundingRect().height() * -1.0) * .5
        self.pos_anim.setEndValue(QtCore.QPointF(x_move, y_move))
        self.out_anim_group.start()

    def update_color(self):
        layers = self.model.get_layers_with_opinion(self.node_path)
        n_colors = []
        if layers:
            for l_path in layers:
                n_colors += [self.model.get_node_color(self.node_path, l_path)]
        elif not self.model.node_is_implied(self.node_path):
            disp_layer = self.model.comp_layer
            n_colors = [self.model.get_node_color(self.node_path, disp_layer)]
        if n_colors:
            self.colors = [QtGui.QColor(color_code) for color_code in n_colors]
            self.colors.reverse()
        else:
            self.colors = [QtGui.QColor(QtCore.Qt.darkGray)]
        if not self.is_real:
            self.color_alpha = 0.35
        else:
            self.color_alpha = 1.0
        self.dim_factor = 100
        if self.model.node_is_instance_child(self.node_path,
                                             self.model.comp_layer):
            self.dim_factor = 110

    def update_fonts(self):
        self.title_font.setStrikeOut(not self.node_enabled)
        self.node_instance = self.model.get_node_instance(self.node_path,
                                                          self.model.comp_layer)
        self.title_font.setItalic(bool(self.node_instance))

    @property
    def title_bounding_rect(self):
        """Returns the bounding rect of the title bar.

        :returns: bounding rect of the title bar
        :rtype: QtCore.QRectF
        """
        return QtCore.QRectF(0.0, 0.0, self.max_width, self.title_rect_height)

    @property
    def stack_bounding_rect(self):
        """Returns the bounding rect of this node and all it's descendants.

        :returns: bounding rect of this node and all it's descendants
        :rtype: QtCore.QRectF
        """
        out_rect = self.get_selection_rect()
        for child in self.childItems():
            if isinstance(child, NodeGraphicsItem):
                child_rect = child.stack_bounding_rect
                out_rect.setHeight(child_rect.height() + out_rect.height())
        return out_rect

    @property
    def screen_pos(self):
        node_pos = self.scenePos()
        view_pos = self.view.mapFromScene(node_pos)
        viewport_pos = self.view.viewport().mapToParent(view_pos)
        global_pos = self.view.mapToGlobal(QtCore.QPoint(0, 0))
        x = global_pos.x() + viewport_pos.x()
        y = global_pos.y() + viewport_pos.y()
        return QtCore.QPointF(x, y)

    def itemChange(self, change, value):
        """Override of QtWidgets.QGraphicsItem itemChange."""
        # keep connections drawing to node as it moves
        if change is self.ItemScenePositionHasChanged:
            graphics = self.view.get_node_connection_graphics(self.node_path)
            for connection in graphics:
                connection.rebuild_line()
        # TODO: Take into account the positions of every selected node and snap them all to a grid as soon as
        #  the user preses shift. This will avoid the weird wavy snapping effect we have right now
        if change == self.ItemPositionChange and self.scene():
            ml = QtWidgets.QApplication.mouseButtons() == QtCore.Qt.LeftButton
            shift = QtWidgets.QApplication.keyboardModifiers() == QtCore.Qt.ShiftModifier
            force_snap = self.view.alignment_actions.snap_action.isChecked()
            if (ml & shift) or force_snap and not self.get_is_animating():
                value = self.closest_grid_point(value)
                return value

        return super(NodeGraphicsItem, self).itemChange(change, value)

    def boundingRect(self):
        """Override of QtWidgets.QGraphicsItem boundingRect. If this rectangle does not encompass the entire
        drawn item, artifacting will happen.
        """
        return self.get_selection_rect()

    def paint(self, painter, option, widget):
        """Override of QtWidgets.QGraphicsItem paint. Handles all visuals of the Node. Split up into 3
        functions for organization.
        """
        lod = QtWidgets.QStyleOptionGraphicsItem.levelOfDetailFromTransform(painter.worldTransform())
        if lod > MIN_LOD:
            painter.setRenderHints(QtGui.QPainter.Antialiasing |
                                   QtGui.QPainter.TextAntialiasing |
                                   QtGui.QPainter.SmoothPixmapTransform)
        else:
            painter.setRenderHints(QtGui.QPainter.Antialiasing |
                                   QtGui.QPainter.TextAntialiasing |
                                   QtGui.QPainter.SmoothPixmapTransform, False)
        self.draw_title(painter, lod)
        self.draw_attributes(painter, lod)
        self.draw_border(painter, lod)

    def closest_grid_point(self, position):
        snapped_pos = self.model.snap_pos_to_grid((position.x(), position.y()))
        return QtCore.QPointF(*snapped_pos)

    def draw_border(self, painter, lod=1.):
        """Draws border, called exclusively by paint.

        :param painter: painter from paint.
        :type painter: QtGui.QPainter
        """

        if self.model.is_selected(self.node_path):
            color = colors.SELECTED
        elif self.is_build_focus:
            color = QtCore.Qt.red
        elif self.is_hovered:
            color = QtCore.Qt.white
        else:
            painter.setPen(QtCore.Qt.NoPen)
            return
        if self.is_proxy:
            pen = QtGui.QPen(color, 1, QtCore.Qt.PenStyle.DashLine)
        else:
            pen = QtGui.QPen(color)
        if self.locked:
            c = QtGui.QColor(self.colors[-1])
            c.setAlphaF(.3)
            b = QtGui.QBrush(c)
            painter.setBrush(b)
            painter.setPen(QtCore.Qt.NoPen)
        else:
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.NoBrush)
        rect = QtCore.QRectF(self.get_selection_rect().x() + 1,
                             self.get_selection_rect().y() + 1,
                             self.get_selection_rect().width() - 2,
                             self.get_selection_rect().height() - 2)
        painter.drawRoundedRect(rect, self.ROUND_X, self.ROUND_Y)

    def draw_title(self, painter, lod=1.):
        """Draw title of the node. Called exclusively in paint.

        :param painter: painter from paint.
        :type painter: QtGui.QPainter
        """
        # draw bg
        painter.setPen(QtCore.Qt.NoPen)
        bg = painter.background()
        bgm = painter.backgroundMode()
        if self.error_item:
            self.scene().removeItem(self.error_item)
            self.error_item.deleteLater()
        self.error_item = None
        if self.is_real and not self.locked:
            painter.setBackgroundMode(QtCore.Qt.OpaqueMode)
        else:
            painter.setBackgroundMode(QtCore.Qt.TransparentMode)
            [c.setAlphaF(self.color_alpha) for c in self.colors]
        color_count = len(self.colors)
        color_band_width = 10
        for i in range(color_count):
            color = self.colors[i]
            if self.is_proxy:
                painter.setBackground(color.darker(self.dim_factor))
                brush = QtGui.QBrush(color.darker(self.dim_factor*2),
                                     QtCore.Qt.FDiagPattern)
            else:
                brush = QtGui.QBrush(color.darker(self.dim_factor))
            if self.locked:
                c = color.darker(self.dim_factor)
                c.setAlphaF(.5)
                painter.setBackground(c)
                brush = QtGui.QBrush(c.darker(self.dim_factor * 2),
                                     QtCore.Qt.Dense1Pattern)
            painter.setBrush(brush)
            # Top Opinion
            if i+1 == color_count:
                remaining_width = self.max_width - (i*color_band_width)
                rect = QtCore.QRectF(0, 0, remaining_width,
                                     self.title_rect_height)
            # Lower Opinions
            else:
                x_pos = self.max_width - (i+1)*color_band_width
                rect = QtCore.QRectF(x_pos, 0, color_band_width,
                                     self.title_rect_height)
            painter.drawRoundedRect(rect, self.ROUND_X, self.ROUND_Y)
        painter.setBackground(bg)
        painter.setBackgroundMode(bgm)
        # draw exec plugs
        exec_attr = nxt_node.INTERNAL_ATTRS.EXECUTE_IN
        exec_in_pos = self.get_attr_in_pos(exec_attr, scene=False)
        out_pos = self.get_attr_out_pos(exec_attr, scene=False)
        self.exec_out_plug.setPos(out_pos)
        self.exec_in_plug.setPos(exec_in_pos)
        if lod > MIN_LOD:
            # draw attr dots
            offset = -6
            for fill in self.attr_dots:
                painter.setBrush(QtCore.Qt.white)
                if fill:
                    painter.setBrush(QtCore.Qt.white)
                else:
                    painter.setBrush(QtCore.Qt.NoBrush)
                dots_color = QtGui.QColor(QtCore.Qt.white).darker(self.dim_factor)
                painter.setPen(QtGui.QPen(dots_color, 0.5))
                dot_x = self.max_width - 15
                dot_y = (self.title_rect_height / 2) + offset
                painter.drawEllipse(QtCore.QPointF(dot_x, dot_y), 2, 2)
                offset += 6

        # draw title

        painter.setFont(self.title_font)
        title_str = nxt_path.node_name_from_node_path(self.node_path)
        font_metrics = QtGui.QFontMetrics(self.title_font)
        width = self.max_width - 40
        if self.error_list:
            width -= 20
        if lod > MIN_LOD:
            painter.setPen(
                QtGui.QColor(QtCore.Qt.white).darker(self.dim_factor))
            if not self.node_enabled:
                painter.setPen(QtGui.QColor(QtCore.Qt.white).darker(150))
            title = font_metrics.elidedText(title_str,
                                            QtCore.Qt.ElideRight, width)
            painter.drawText(15, 0, self.max_width - 15, self.title_rect_height,
                             QtCore.Qt.AlignVCenter, title)
        else:
            painter.setBrush(QtGui.QColor(QtCore.Qt.white).darker(self.dim_factor))
            if not self.node_enabled:
                painter.setBrush(QtGui.QColor(QtCore.Qt.white).darker(150))
            proxy_rect = font_metrics.boundingRect(title_str)
            r_width = proxy_rect.width() * .8
            height = proxy_rect.height()
            painter.drawRect(15, height * .8,
                             min(r_width, width), height * .2)

        if lod > MIN_LOD:
            # draw error
            if self.error_list:
                pos = QtCore.QPointF(self.max_width-45, self.title_rect_height/4)
                error_item = ErrorItem(font=QtGui.QFont('Roboto', 16, 75),
                                       pos=pos, text='!')
                error_item.setParentItem(self)
                error_item.setZValue(50)
                self.error_item = error_item

        # draw collapse state arrow
        for arrow in self.collapse_arrows:
            self.scene().removeItem(arrow)
        if lod > MIN_LOD:
            self.collapse_arrows = []
            # TODO calculation needed arrows should be done outside drawing

            if self.collapse_state:
                des_colors = self.model.get_descendant_colors(self.node_path)
                filled = self.model.has_children(self.node_path)
                if not filled:
                    des_colors = [QtCore.Qt.white]
                elif not des_colors:
                    disp = self.model.comp_layer
                    des_colors = [self.model.get_node_color(self.node_path, disp)]
                i = 0
                num = len(des_colors)
                for c in des_colors:
                    arrow = CollapseArrow(self, filled=filled, color=c)
                    arrow_width = arrow.width * 1.1
                    center_offset = (arrow_width * (num * .5) - arrow_width * .5)
                    cur_offset = (i * arrow_width)
                    pos = ((self.max_width * .5) + center_offset - cur_offset)
                    arrow.setPos(pos, self.boundingRect().height())
                    self.collapse_arrows += [arrow]
                    i += 1

    def draw_attributes(self, painter, lod=1.):
        """Draw attributes for this node. Called exclusively by paint.

        :param painter: painter from paint.
        :type painter: QtGui.QPainter
        """
        for attr_name in self.user_attr_names:
            # draw bg rect
            attr_details = self._attribute_draw_details[attr_name]
            painter.setBrush(attr_details['bg_color'])
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawRect(attr_details['bg_rect'])

            # draw connection points
            target_color = attr_details['plug_color']

            self._attr_plug_graphics.setdefault(attr_name, {})
            attr_plug_graphics = self._attr_plug_graphics[attr_name]
            current_in_plug = attr_plug_graphics.get('in_plug')
            if lod > MIN_LOD:
                in_pos = self.get_attr_in_pos(attr_name, scene=False)
                if current_in_plug:
                    current_in_plug.show()
                    current_in_plug.color = target_color
                    current_in_plug.update()
                else:
                    current_in_plug = NodeGraphicsPlug(radius=self.ATTR_PLUG_RADIUS,
                                                       color=target_color,
                                                       attr_name_represented=attr_name,
                                                       is_input=True,
                                                       parent=self)
                    attr_plug_graphics['in_plug'] = current_in_plug
                current_in_plug.setPos(in_pos)
            elif current_in_plug:
                current_in_plug.hide()

            current_out_plug = attr_plug_graphics.get('out_plug')
            if lod > MIN_LOD:
                out_pos = self.get_attr_out_pos(attr_name, scene=False)
                if current_out_plug:
                    current_out_plug.show()
                    current_out_plug.color = target_color
                    current_out_plug.update()
                else:
                    current_out_plug = NodeGraphicsPlug(radius=self.ATTR_PLUG_RADIUS,
                                                        color=target_color,
                                                        attr_name_represented=attr_name,
                                                        is_input=False,
                                                        parent=self)
                    attr_plug_graphics['out_plug'] = current_out_plug
                current_out_plug.setPos(out_pos)
            elif current_out_plug:
                current_out_plug.hide()

            # draw attr_name
            rect = attr_details['bg_rect']
            painter.setFont(attr_details['title_font'])
            font_metrics = QtGui.QFontMetrics(self.attr_font)
            title = font_metrics.elidedText(attr_name, QtCore.Qt.ElideRight,
                                            self.max_width - 20)
            if lod > MIN_LOD:
                painter.setPen(attr_details['title_color'])
                painter.drawText(rect.x() + 10, rect.y() - 1, rect.width(),
                                 rect.height(), QtCore.Qt.AlignVCenter, title)
            else:
                proxy_rect = font_metrics.boundingRect(title)
                height = proxy_rect.height()
                width = proxy_rect.width()
                painter.setBrush(attr_details['title_color'].darker(150))
                painter.drawRect(rect.x() + 10, rect.y() + height*.8,
                                 width, height*.2)

    def calculate_attribute_draw_details(self):
        """Calculate position of all known attr names. Details stored in
        self._attribute_draw_details. Public interface to get details is split
        into two functions, get_attr_in_pos and get_attr_out_pos.
        """
        self._attribute_draw_details = OrderedDict()
        index = -1
        comp_layer = self.model.comp_layer
        for attr_name in self.user_attr_names:
            index += 1
            draw_details = {}
            # sizes
            rect_y = self.title_rect_height + index * self.attr_rect_height
            rect_midpoint = rect_y + (self.attr_rect_height / 2)
            draw_details['text_height'] = rect_y
            draw_details['bg_rect'] = QtCore.QRectF(0, rect_y, self.max_width,
                                                    self.attr_rect_height)
            # positions
            draw_details['in_pos'] = QtCore.QPointF(self.attr_plug_side_margin,
                                                    rect_midpoint)
            out_x = self.max_width - self.attr_plug_side_margin
            draw_details['out_pos'] = QtCore.QPointF(out_x, rect_midpoint)
            # background color
            color = self.model.get_node_attr_color(self.node_path, attr_name,
                                                   comp_layer)
            bg_color = QtGui.QColor(color).darker(150).darker(self.dim_factor)
            bg_color.setAlphaF(self.attr_rect_opacity)
            draw_details['bg_color'] = bg_color
            # plug color
            type_ = self.model.get_node_attr_type(self.node_path, attr_name,
                                                  comp_layer)
            draw_details['plug_color'] = colors.ATTR_COLORS.get(type_,
                                                                QtCore.Qt.gray)
            # title color
            attr_is_instance = self.model.node_attr_is_instance(self.node_path,
                                                                attr_name,
                                                                comp_layer)
            dim_title = 150 if attr_is_instance else self.dim_factor
            white = QtGui.QColor(QtCore.Qt.white)
            draw_details['title_color'] = white.darker(dim_title)
            # font
            font = QtGui.QFont(self.attr_font.family(),
                               self.attr_font.pointSize(),
                               italic=attr_is_instance)
            draw_details['title_font'] = font

            self._attribute_draw_details[attr_name] = draw_details
        # Internal Attrs
        # Exec
        draw_details = {}
        in_pos = QtCore.QPointF(0, self.title_bounding_rect.height()*0.5)
        draw_details['in_pos'] = in_pos
        out_pos = QtCore.QPointF(self.max_width,
                                 self.title_bounding_rect.height()*0.5)
        draw_details['out_pos'] = out_pos
        draw_details['plug_color'] = QtGui.QColor(QtCore.Qt.white)
        exec_attr = nxt_node.INTERNAL_ATTRS.EXECUTE_IN
        self._attribute_draw_details[exec_attr] = draw_details
        # Inst
        draw_details = {}
        in_pos = QtCore.QPointF(0, (self.title_bounding_rect.height()/3) * 2)
        draw_details['in_pos'] = in_pos
        out_pos = QtCore.QPointF(self.max_width,
                                 (self.title_bounding_rect.height()/3) * 2)
        draw_details['out_pos'] = out_pos
        draw_details['plug_color'] = QtGui.QColor(QtCore.Qt.gray)
        inst_attr = nxt_node.INTERNAL_ATTRS.INSTANCE_PATH
        self._attribute_draw_details[inst_attr] = draw_details

    def get_selection_rect(self):
        """used by boundingRect and draw_border."""
        min_rect = self.get_title_and_attrs_rect()
        selection_scale_offset = 0.5
        out_x = min_rect.x() - selection_scale_offset
        out_y = min_rect.y() - selection_scale_offset
        out_width = min_rect.right() + (selection_scale_offset * 2)
        out_heighth = min_rect.bottom() + (selection_scale_offset * 2)
        return QtCore.QRectF(out_x, out_y, out_width, out_heighth)

    def get_title_and_attrs_rect(self):
        """Returns the rectangle that contains the title and all of the attrs

        :return: The rectangle that contains the title and all of the attrs.
        """
        attrs_height = len(self.user_attr_names) * self.attr_rect_height
        height = self.title_rect_height + attrs_height
        return QtCore.QRectF(0, 0, self.max_width, height)

    def hoverEnterEvent(self, event):
        """Override of QtWidgets.QGraphicsItem hoverEnterEvent."""
        self.is_hovered = True
        if self.view.view_actions.tooltip_action.isChecked():
            self.setToolTip(self.get_node_tool_tip())
        else:
            self.setToolTip('')
        super(NodeGraphicsItem, self).hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        """Override of QtWidgets.QGraphicsItem hoverLeaveEvent."""
        self.is_hovered = False
        self.update()
        super(NodeGraphicsItem, self).hoverLeaveEvent(event)

    def update_build_focus(self):
        if not self.model.executing:
            self.is_build_focus = False
            self.update()
            return
        self.is_build_focus = self.node_path == self.model.get_build_focus()
        self.update()

    def update_from_model(self):
        """Sync the visible state of this node with the model."""
        # Shortened var names
        comp = self.model.comp_layer
        node_path = self.node_path
        # update position
        if nxt_path.get_parent_path(node_path) == nxt_path.WORLD:
            pos = self.model.get_node_pos(node_path)
            self.setPos(pos[0], pos[1])
        self.is_real = self.model.node_exists(node_path)
        self.is_proxy = self.model.get_node_is_proxy(node_path)
        self.locked = self.model.get_node_locked(node_path)
        self.collapse_state = self.model.get_node_collapse(self.node_path,
                                                           comp)
        self.node_enabled = self.model.get_node_enabled(self.node_path)
        self.update_color()
        self.update_build_focus()
        self._update_collapse()
        self.error_list = self.model.get_node_error(node_path, comp)
        self.update_fonts()
        # update exec plugs
        # update attributes
        # 0 = no attributes
        # 1 = only local attributes
        # 2 = local and instanced attributes
        # 3 = local, instanced, and inherited attributes
        attr_display_state = self.model.get_attr_display_state(node_path)
        if attr_display_state == 1:
            attr_names = self.model.get_node_local_attr_names(node_path,
                                                              comp)
        elif attr_display_state == 2:
            local_attr_names = self.model.get_node_local_attr_names(node_path,
                                                                    comp)
            inst_attrs = self.model.get_node_instanced_attr_names(node_path,
                                                                  comp)
            attr_names = set(local_attr_names + inst_attrs)
        elif attr_display_state == 3:
            attr_names = self.model.get_node_attr_names(node_path, comp)
        else:
            attr_names = []
        removed_attr_names = set(self.user_attr_names).difference(attr_names)
        self.user_attr_names = sorted(attr_names)

        for removed_name in removed_attr_names:
            if removed_name in self._attribute_draw_details:
                self._attribute_draw_details.pop(removed_name)
            if removed_name not in self._attr_plug_graphics:
                continue
            plug_grpahics = self._attr_plug_graphics.pop(removed_name)
            plug = plug_grpahics.get('in_plug')
            if plug:
                self.scene().removeItem(plug)
            plug = plug_grpahics.get('out_plug')
            if plug:
                self.scene().removeItem(plug)
        self.calculate_attribute_draw_details()
        for key, value in self._attribute_draw_details.items():
            in_plug = value.get('in_plug')
            if in_plug:
                in_plug.update()

            out_plug = value.get('out_plug')
            if out_plug:
                out_plug.update()

        self.is_break = self.model.get_is_node_breakpoint(node_path, comp)
        self.is_start = self.model.get_is_node_start(node_path, comp)
        sp_attr = INTERNAL_ATTRS.START_POINT
        self.start_color = self.model.get_node_attr_color(node_path, sp_attr,
                                                          comp)


        if attr_display_state == 1:
            self.attr_dots = [True, False, False]
        elif attr_display_state == 2:
            self.attr_dots = [True, True, False]
        elif attr_display_state == 3:
            self.attr_dots = [True, True, True]
        else:
            self.attr_dots = [False, False, False]

        self.update()

    def update_plugs(self):
        self.calculate_attribute_draw_details()
        self.update()

    def update_collapse(self):
        self._update_collapse()
        self.update()

    def _update_collapse(self):
        comp_layer = self.model.comp_layer
        self.collapse_state = self.model.get_node_collapse(self.node_path,
                                                           comp_layer)

    def get_node_tool_tip(self):
        if not self.is_real:
            return 'Implicit node'
        disp_layer = self.model.comp_layer
        node = disp_layer.lookup(self.node_path)
        node_data = self.model.stage.get_node_data(node, disp_layer,
                                                   include_inherit=True)
        path_key = INTERNAL_ATTRS.as_save_key(INTERNAL_ATTRS.NODE_PATH)
        node_data[path_key] = self.node_path
        column_1_width = 20
        column_2_width = 80
        title = self.elided_text(getattr(node, INTERNAL_ATTRS.NAME),
                                 column_1_width + column_2_width).upper()
        table = self.table_format(node_data, column_1_width, column_2_width)
        return title + '\n' + table

    @staticmethod
    def table_format(data, col_1_width, col_2_width):
        offset = col_1_width - 1
        lines = list()
        for k, v in data.items():
            col_1_out = '\n'.join(textwrap.wrap(str(k),
                                                offset)).ljust(col_1_width, '.')
            if isinstance(v, list):
                str_v = str([str(i) for i in v])
                col_2_out = ('\n ' + (' ' * offset)).join(textwrap.wrap(str_v,
                                                          col_2_width))
            else:
                col_2_out = ('\n ' +
                             (' ' * offset)).join(textwrap.wrap(str(v),
                                                                col_2_width))
            lines += [col_1_out + col_2_out]
        return '\n'.join(lines)

    @staticmethod
    def elided_text(text, width, char='.', repeat=3):
        return text if len(str(text)) < width else text[:width - repeat] + (char * repeat)

    def rename_node(self):
        """Presents a rename dialog pop-up over the node item. The new name is sent to the model."""
        # get dialog geometry
        scale_factor = self.view.transform().m11()
        scale = scale_factor if scale_factor > 0.75 else 0.75
        title_rect = self.title_bounding_rect.toRect()
        width = title_rect.width() * scale
        height = title_rect.height() * scale
        pos = self.screen_pos
        geometry = QtCore.QRect(pos.x(), pos.y(), width, height)

        # rename dialog
        name = nxt_path.node_name_from_node_path(self.node_path)
        dialog = NameEditDialog(name=name, geometry=geometry, parent=None)
        color_name = self.colors[-1].name()
        dialog.setStyleSheet('background-color: %s; color: white' % color_name)
        font = QtGui.QFont(self.title_font.family(), self.title_font.pointSizeF() * scale)
        dialog.line_edit.setFont(font)
        dialog.exec_()

        # rename node
        if dialog.result():
            new_name = dialog.value
            self.model.set_node_name(self.node_path, new_name, self.model.target_layer)

    def collapse_node(self, recursive=False):
        """Collapse the node hierarchy below this node"""
        is_collapsed = self.model.get_node_collapse(self.node_path)
        self.model.toggle_node_collapse(node_paths=[self.node_path],
                                        recursive_down=recursive,
                                        layer_path=LAYERS.TOP)

    def arrange_descendants(self):
        """Recursively arrange this node's descendants
        """
        self.stack_height = self.get_selection_rect().height()
        if self.model.get_node_collapse(self.node_path):
            return
        children_paths = self.model.get_children(self.node_path, ordered=True,
                                                 include_implied=True)
        prev_y = 0
        prev_child = None
        index = 1
        for child_path in children_paths:
            child = self.view.get_node_graphic(child_path)
            if not child:
                continue
            child.setParentItem(self)
            child.setFlag(QtWidgets.QGraphicsItem.ItemIsMovable, False)

            if prev_child:
                y = prev_child.stack_height
                child.stackBefore(prev_child)
            else:
                y = self.get_selection_rect().height()
            y += prev_y
            new_pos = QtCore.QPointF(self.stack_offset, y)
            child.anim_into_place(new_pos)
            prev_y = y
            child.arrange_descendants()
            prev_child = child
            index += 1
        if prev_child:
            self.stack_height = y + prev_child.stack_height

    def get_attr_in_pos(self, attr_name, scene=True):
        """Get the position of given attr's input graphic, optionally in
        screen coordinates.

        :param attr_name: Name of the attribute to get position for.
        :type attr_name: str
        :param scene: Whether or not to get the position in screen coordinates.
        :type scene: bool, defautls to True
        :return: Position of the attr in pin.
        """
        details = self._attribute_draw_details.get(attr_name)
        if not details:
            return
        pos = self._attribute_draw_details[attr_name]['in_pos']
        if not scene:
            return pos
        return self.mapToScene(pos)

    def get_attr_out_pos(self, attr_name, scene=True):
        """Get the position of given attr's output graphic, optionally in
        screen coordinates.

        :param attr_name: Name of the attribute to get position for.
        :type attr_name: str
        :param scene: Whether or not to get the position in screen coordinates.
        :type scene: bool, defaults to True

        :return: Position of the attr out pin.
        """
        details = self._attribute_draw_details.get(attr_name)
        if not details:
            return
        pos = self._attribute_draw_details[attr_name]['out_pos']
        if not scene:
            return pos
        return self.mapToScene(pos)


class NodeGraphicsPlug(QtWidgets.QGraphicsItem):

    """Graphics item for user attribute plugs on the NodeGraphicsItem."""

    def __init__(self, radius=3, hover_width=0.5, color=QtGui.QColor(255, 255, 255, 255),
                 attr_name_represented='', is_input=False, parent=None):
        super(NodeGraphicsPlug, self).__init__(parent=parent)
        self.setAcceptHoverEvents(True)
        # TODO benchmark this cache setting to see if it helps or hurts performance
        self.setCacheMode(QtWidgets.QGraphicsItem.DeviceCoordinateCache)

        self.radius = radius
        self.hover_width = hover_width
        self.color = QtGui.QColor(color)
        self.attr_name_represented = attr_name_represented
        self.is_input = is_input

        self.is_hovered = False

    def boundingRect(self):
        """Override of QtWidgets.QGraphicsItem boundingRect. If this rectangle does not encompass the entire
        drawn item, artifacting will happen.
        """
        offset = self.hover_width * 8
        return QtCore.QRect((self.radius + offset) * -1,
                            (self.radius + offset) * -1,
                            (self.radius + offset) * 2,
                            (self.radius + offset) * 2)

    def _apply_lod_to_painter(self, painter):
        lod = QtWidgets.QStyleOptionGraphicsItem.levelOfDetailFromTransform(
            painter.worldTransform())
        if lod > MIN_LOD:
            painter.setRenderHints(QtGui.QPainter.Antialiasing |
                                   QtGui.QPainter.TextAntialiasing |
                                   QtGui.QPainter.SmoothPixmapTransform)
        else:
            painter.setRenderHints(QtGui.QPainter.Antialiasing |
                                   QtGui.QPainter.TextAntialiasing |
                                   QtGui.QPainter.SmoothPixmapTransform, False)

    def paint(self, painter, option, widget):
        """Override of QtWidgets.QGraphicsItem paint. Handles all visuals of the Plug."""
        self._apply_lod_to_painter(painter)
        if self.is_hovered:
            painter.setPen(QtGui.QPen(QtCore.Qt.white, self.hover_width, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
        else:
            painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(self.color)
        painter.drawEllipse(QtCore.QPointF(0, 0), self.radius, self.radius)

    def itemChange(self, change, value):
        """Override of QtWidgets.QGraphicsItem itemChange."""
        if change is QtWidgets.QGraphicsItem.ItemSceneChange:
            if value != self.scene():
                # the z value here is really only relevant in the context of a NodeGraphicsItem,
                # which is the only place these are ever made.
                self.setZValue(1)

                # this is the moment we've been removed from a scene.
                if not value:
                    del self
                    return

        return super(NodeGraphicsPlug, self).itemChange(change, value)

    def hoverEnterEvent(self, event):
        """Override of QtWidgets.QGraphicsItem hoverEnterEvent."""
        self.is_hovered = True
        self.update()
        super(NodeGraphicsPlug, self).hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        """Override of QtWidgets.QGraphicsItem hoverLeaveEvent."""
        self.is_hovered = False
        self.update()
        super(NodeGraphicsPlug, self).hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        """Override of QtWidgets.QGraphicsItem mousePressEvent."""
        # break attribute connections
        if event.modifiers() == QtCore.Qt.AltModifier:
            raise NotImplementedError("Alt to clear attribute is broken.")
        if self.attr_name_represented:
            node_path = self.parentItem().node_path
            path = nxt_path.make_attr_path(node_path, self.attr_name_represented)
        else:
            path = self.parentItem().node_path

        if self.is_input:
            self.parentItem().view.start_connection_draw(tgt_path=path)
        else:
            self.parentItem().view.start_connection_draw(src_path=path)
        event.accept()

        # Intentionally not sending this super call because we need to absorb this click when we are
        # dragging to make a connection.
        # super(NodeGraphicsPlug, self).mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        """Override of QtWidgets.QGraphicsItem mouseReleaseEvent."""
        # parent_name = self.parentItem().node_path
        # print(parent_name + 'plug mouse press')
        super(NodeGraphicsPlug, self).mouseReleaseEvent(event)


class NodeExecutionPlug(NodeGraphicsPlug):
    """Node Graphics Plug for the plugs in the execution position.

    Handles drawing of exec plugs, as well as start, break, and skip points.
    """
    def __init__(self, model, node_path, is_input, parent=None):
        super(NodeExecutionPlug, self).__init__(
            radius=NodeGraphicsItem.EXEC_PLUG_RADIUS,
            color=QtCore.Qt.white,
            attr_name_represented=nxt_node.INTERNAL_ATTRS.EXECUTE_IN,
            is_input=is_input,
            parent=parent
        )
        self.node_path = node_path
        self.model = model

        self.is_root = None
        self.is_break = None
        self.is_start = None
        self.start_color = None
        self.is_skip = None
        self.model.starts_changed.connect(self._refresh_is_start)
        self.model.breaks_changed.connect(self._refresh_is_break)
        self.model.skips_changed.connect(self._refresh_is_skip)
        self._refresh_from_model()

    def _refresh_is_start(self):
        self.is_start = self.model.get_is_node_start(self.node_path, self.model.comp_layer)
        if self.is_start:
            self.start_color = self.model.get_node_attr_color(
                self.node_path, INTERNAL_ATTRS.START_POINT, self.model.comp_layer)
        self.update()

    def _refresh_is_break(self):
        self.is_break = self.model.get_is_node_breakpoint(self.node_path, self.model.comp_layer)
        self.update()

    def _refresh_is_skip(self):
        self.is_skip = self.model.is_node_skippoint(self.node_path, self.model.comp_layer.real_path)
        self.update()

    def _refresh_from_model(self):
        self.is_root = nxt_path.get_path_depth(self.node_path) == 1
        self._refresh_is_break()
        self._refresh_is_start()
        self._refresh_is_skip()

    def paint(self, painter, option, widget):
        """Override of QtWidgets.QGraphicsItem paint. Handles all visuals of the Plug."""
        special_input = any([self.is_break, self.is_start, self.is_skip])
        # If an output, or an non-special input.
        if (not self.is_input) or (not special_input):
            if self.is_root:
                self.radius = NodeGraphicsItem.EXEC_PLUG_RADIUS
                super(NodeExecutionPlug, self).paint(painter, option, widget)
            # For non-root non-specials, no drawing.
            return
        self._apply_lod_to_painter(painter)
        shape_border_pen = QtGui.QPen(colors.GRAPH_BG_COLOR, self.hover_width * 2)
        if self.is_start:  # A green triangle, with a border of layer color
            self.radius = 13
            painter.setBrush(QtGui.QColor(self.start_color))
            painter.setPen(shape_border_pen)
            painter.drawPolygon(self._buildTriangle(QtCore.QPointF(self.radius * -0.6, 0), self.radius))
            painter.setBrush(colors.START_COLOR)
            painter.setPen(QtCore.Qt.NoPen)
            painter.drawPolygon(self._buildTriangle(QtCore.QPointF(self.radius * -0.6, 0), self.radius * .7))
        elif self.is_skip:  # A short wide rect, a minus
            self.radius = 9
            painter.setBrush(colors.SKIP_COLOR)
            painter.setPen(shape_border_pen)
            skip_rect = QtCore.QRect(self.radius * -1, self.radius * -.6, self.radius * 2, self.radius)
            painter.drawRoundedRect(skip_rect, 4, 4)
        elif self.is_break:  # A red square
            self.radius = 8
            painter.setBrush(colors.BREAK_COLOR)
            painter.setPen(shape_border_pen)
            painter.drawRect(self.radius * -1, self.radius * -1, self.radius * 2, self.radius * 2)

    def _buildTriangle(self, offset, side_length):
        polygon = QtGui.QPolygonF()
        step_angle = 120
        for i in [0, 1, 2, 3]:
            step = step_angle * i
            x = side_length * 1.2 * math.cos(math.radians(step))
            y = side_length * 1.2 * math.sin(math.radians(step))
            polygon.append(QtCore.QPointF(x, y))
        polygon.translate(offset)
        return polygon


class CollapseArrow(QtWidgets.QGraphicsItem):

    """Graphics item for when NodeGraphicsItem stacks are collapsed."""

    def __init__(self, parent=None, filled=False, color=None):
        super(CollapseArrow, self).__init__(parent)
        self.height = 8
        self.width = 16
        self.filled = filled
        self.color = color or QtCore.Qt.white
        if sys.version_info[0] == 2:
            is_str = isinstance(self.color, basestring)
        else:
            is_str = isinstance(self.color, str)
        if is_str:
            self.color = QtGui.QColor(self.color)
        self.setZValue(30)

    def boundingRect(self):
        """Override of QtWidgets.QGraphicsItem boundingRect. If this rectangle
        does not encompass the entire drawn item, artifacting will happen.
        """
        return QtCore.QRect(0-(self.width*.5), 0, self.width, self.height)

    def paint(self, painter, option, widget):
        """Override of QtWidgets.QGraphicsItem paint."""
        painter.setRenderHints(QtGui.QPainter.Antialiasing |
                               QtGui.QPainter.TextAntialiasing |
                               QtGui.QPainter.SmoothPixmapTransform)
        if self.filled:
            brush = QtGui.QBrush(self.color)
            painter.setBrush(brush)
            if self.color.lightness() < 100:
                pen_color = QtGui.QColor(self.color.lighter(300))
            else:
                pen_color = QtGui.QColor(self.color.darker(300))
            pen = QtGui.QPen(pen_color)
            pen.setJoinStyle(QtCore.Qt.RoundJoin)
            painter.setPen(QtCore.Qt.NoPen)
        else:
            brush = QtGui.QBrush(QtCore.Qt.white, QtCore.Qt.Dense6Pattern)
            painter.setBrush(brush)
            pen = QtGui.QPen(QtCore.Qt.white)
            pen.setStyle(QtCore.Qt.DotLine)
            painter.setPen(pen)

        # draw triangle
        points = [
            QtCore.QPointF(0 - (self.width * .5), 0),
            QtCore.QPointF(self.width*.5, 0),
            QtCore.QPointF(0, self.height)
        ]
        painter.drawPolygon(points)
        # Draw outline
        if self.filled:
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.setPen(pen)
            painter.drawLine(0 - (self.width * .5), 0,
                             0, self.height)
            painter.drawLine(0, self.height,
                             self.width * .5, 0)

    def itemChange(self, change, value):
        """Override of QtWidgets.QGraphicsItem itemChange."""
        if change is QtWidgets.QGraphicsItem.ItemSceneChange:
            if value != self.scene():
                # z value only relevant in the context of a NodeGraphicsItem,
                # which is the only place these are ever made.
                self.setZValue(1)

                # this is the moment we've been removed from a scene.
                if not value:
                    del self
                    return

        return super(CollapseArrow, self).itemChange(change, value)


class ErrorItem(QtWidgets.QGraphicsTextItem):
    def __init__(self, font, pos=QtCore.QPointF(), text='!', color=QtCore.Qt.red):
        super(ErrorItem, self).__init__()
        self.setPos(pos)
        self.text = text
        self.color = color
        self.setFont(font)

    def boundingRect(self):
        return QtCore.QRectF(-10, -10, 10, 10)

    def paint(self, painter, option, widget):
        painter.setRenderHints(QtGui.QPainter.Antialiasing |
                               QtGui.QPainter.TextAntialiasing)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(colors.ERROR)
        painter.drawEllipse(0, 0, 20, 20)
        painter.setPen(QtCore.Qt.black)
        painter.setFont(self.font())
        painter.drawText(QtCore.QRectF(0.6, 0.1, 20, 20), QtCore.Qt.AlignCenter,
                         self.text)
