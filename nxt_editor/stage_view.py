# Built-in
import math
import logging
import time
from functools import partial

# External
from Qt import QtWidgets
from Qt import QtGui
from Qt import QtCore

# Interal
import nxt_editor
from nxt import nxt_node, tokens
from nxt_editor.node_graphics_item import (NodeGraphicsItem, NodeGraphicsPlug,
                                           _pyside_version)
from nxt_editor.connection_graphics_item import AttrConnectionGraphic
from nxt_editor.dialogs import NxtWarningDialog
from nxt_editor.commands import *
from nxt_editor import colors
from .user_dir import USER_PREF, user_prefs

logger = logging.getLogger(nxt_editor.LOGGER_NAME)


class CONNECTION_SIDES:
    IN = 'input'
    OUT = 'output'
    BOTH = (IN, OUT)


class StageView(QtWidgets.QGraphicsView):
    """Primary display/edit widget for node hierarchies of an nxt graph.
    Displays nodes in visual hierarchies and allows selection, parenting, and
    arranging.
    """
    POTENTIAL_CONNECTION_DEPTH = 30
    CONNECTION_DEPTH = -10
    NODE_DEPTH = 0

    def __init__(self, model, parent=None):
        super(StageView, self).__init__(parent=parent)
        self.main_window = parent
        self._do_anim_pref = user_prefs.get(USER_PREF.ANIMATION, True)
        if _pyside_version[1] < 11:
            self._do_anim_pref = False
        self.do_animations = self._do_anim_pref
        self.once_sec_timer = QtCore.QTimer(self)
        self.once_sec_timer.timeout.connect(self.calculate_fps)
        self.frames = 0
        self.fps = 0
        self.once_sec_timer.setInterval(1000)
        if user_prefs.get(USER_PREF.FPS, True):
            self.once_sec_timer.start()
        self._animating = []
        # EXEC ACTIONS
        self.exec_actions = parent.execute_actions
        self.addActions(self.exec_actions.actions())
        # ALIGNMENT ACTIONS
        self.alignment_actions = parent.alignment_actions
        self.addActions(self.alignment_actions.actions())
        # NODE AUTHORING ACTIONS
        self.authoring_actions = parent.node_actions
        self.addActions(self.authoring_actions.actions())
        # VIEW ACTIONS
        self.view_actions = parent.view_actions
        self.addActions(self.view_actions.actions())
        self.setAcceptDrops(True)
        self.setObjectName('Graph View')
        self._parent = parent
        self.nxt = parent.nxt
        self.addAction(self._parent.app_actions.undo_action)
        self.addAction(self._parent.app_actions.redo_action)
        # graph view settings
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
        self.setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)
        self.setOptimizationFlag(self.DontSavePainterState, enabled=True)
        self.setOptimizationFlag(self.DontAdjustForAntialiasing, enabled=True)
        # scene
        self._scene = QtWidgets.QGraphicsScene()
        self.setScene(self._scene)
        # TODO Currently setting scene rect and never changing it. We hope for expanding graphs in the future.
        self.scene().setSceneRect(QtCore.QRect(-5000, -5000, 10000, 10000))
        # rubber band
        self.rubber_band = QtWidgets.QRubberBand(QtWidgets.QRubberBand.Rectangle, self)

        # navigation attributes
        self._held_keys = []
        self._rubber_band_origin = None
        self._initial_click_pos = None
        self._clicked_something_locked = False
        self.new_node_selected = False
        self.panning = False
        self.zooming = False
        self._num_scheduled_scalings = 0
        self.zoom_start_pos = QtCore.QPointF(.0, .0)
        self._view_pos = self.zoom_start_pos
        self._scene_pos = self.zoom_start_pos
        self.zoom_button = QtCore.Qt.RightButton
        self.zoom_button_down = False
        self.block_context_menu = True
        self._current_pan_distance = 0.0
        self._previous_mouse_pos = None
        self._scale_minimum = 0.1
        self._scale_maximum = 2.0
        self.mouse_scene_pos = QtCore.QPointF(.0, .0)

        # scene attributes
        self.view_padding_factor = 200
        self.draw_grid_size = GRID_SIZE
        self.plug_item_depth = -10

        # graphics items collections
        self._node_graphics = {}
        self._connection_graphics = []
        self._attr_concerns = {}
        self.prev_build_focus_path = None

        # local attributes
        self.show_grid = user_prefs.get(USER_PREF.SHOW_GRID, True)
        # connection attribute used when drawing connections
        self.potential_connection = None

        # model and connections
        self.model = model
        self.model.data_state_changed.connect(self.update_resolved)
        self.model.layer_color_changed.connect(self.update_view)
        self.model.layer_lock_changed.connect(self.update_view)
        self.model.comp_layer_changed.connect(self.update_view)
        self.model.comp_layer_changed.connect(self.failure_check)
        self.model.nodes_changed.connect(self.handle_nodes_changed)
        self.model.attrs_changed.connect(self.handle_attrs_changed)
        self.model.node_moved.connect(self.handle_node_move)
        self.model.selection_changed.connect(self.on_model_selection_changed)
        self.model.frame_items.connect(self.frame_nodes)
        self.model.collapse_changed.connect(self.handle_collapse_changed)

        # initialize the view
        self.update_view()

        # HUD
        self.hud_layout = QtWidgets.QGridLayout(self)
        self.hud_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.hud_layout)

        # filepath HUD
        self.filepath_label = HUDItem(text=None)
        self.filepath_label.setFont(QtGui.QFont("Roboto Mono", 8))
        self.filepath_label.setAlignment(QtCore.Qt.AlignLeft |
                                         QtCore.Qt.AlignTop)
        self.update_filepath()
        self.hud_layout.addWidget(self.filepath_label, 0, 0)

        # resolved HUD
        self.resolved_label = HUDItem(text='resolved', fade_time=1000)
        self.resolved_label.setFont(QtGui.QFont("Roboto", 12, weight=75))
        self.resolved_label.setAlignment(QtCore.Qt.AlignRight |
                                         QtCore.Qt.AlignTop)
        self.hud_layout.addWidget(self.resolved_label, 0, 3)

        self.fps_label = HUDItem(text='resolved', fade_time=0)
        self.fps_label.setFont(QtGui.QFont("Roboto", 12, weight=75))
        self.fps_label.setAlignment(QtCore.Qt.AlignRight |
                                    QtCore.Qt.AlignBottom)
        if user_prefs.get(USER_PREF.FPS, True):
            self.hud_layout.addWidget(self.fps_label, 1, 3)

        self.SEL_ADD_MODIFIERS = QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier
        self.SEL_TOGGLE_MODIFIERS = QtCore.Qt.KeyboardModifiers(QtCore.Qt.ShiftModifier)
        self.SEL_RMV_MODIFIERS = QtCore.Qt.KeyboardModifiers(QtCore.Qt.ControlModifier)

    def calculate_fps(self):
        self.fps = (self.frames + self.fps) * .5
        self.fps_label.setText(str(round(self.fps)))
        self.frames = 0

    def drawForeground(self, painter, rect):
        super(StageView, self).drawForeground(painter, rect)
        self.frames += 1

    def focusInEvent(self, event):
        super(StageView, self).focusInEvent(event)

    def focusOutEvent(self, event):
        self.zooming = False
        self.zoom_keys_down = False
        self._held_keys = []
        self.zoom_button_down = False
        super(StageView, self).focusOutEvent(event)

    def dragEnterEvent(self, event):
        super(StageView, self).dragEnterEvent(event)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        super(StageView, self).dragMoveEvent(event)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        super(StageView, self).dropEvent(event)
        urls = event.mimeData().urls()
        for url in urls:
            file_path = url.toLocalFile()
            self._parent.load_file(file_path)

    def update_resolved(self):
        self.resolved_label.setText(self.model.data_state)

    def update_filepath(self):
        filepath = self.model.top_layer.real_path or '<unsaved>'
        self.filepath_label.setText(filepath)

    @property
    def scale_factor(self):
        return self.transform().m11()

    @property
    def implicit_connections(self):
        if self.model:
            return self.model.implicit_connections

    def failure_check(self, *args):
        if self.model.comp_layer.failure and not self.main_window.in_startup:
            info = ('There was a critical error when building the comp.\n'
                    'Please check your output window for more details as to\n'
                    'what nodes failed and possibly why.')
            NxtWarningDialog.show_message('Bad Comp!', info,
                                          details=self.model.comp_layer.failure)

    def update_view(self, dirty=()):
        """Clears and re-draws graphics items. If the dirty list is empty all
        nodes are condisered dirty and re-drawn.
        :param dirty: List or Tuple of dirty node paths
        :return: None
        """
        start = time.time()
        # The signal layer_color_changed somehow passes its layer to this
        # function. Until we clean up signals this accounts for the wrong
        # type coming through the dirty arg
        if not isinstance(dirty, (tuple, list)):
            dirty = ()
        if not dirty:
            self.clear()
            self.potential_connection = None
        else:
            # TODO: Remove this when update_hierarchy is fixed
            extra_roots = []
            for path in dirty:
                root = nxt_path.get_root_path(path)
                if root not in dirty:
                    extra_roots += [root]
            dirty += extra_roots
        self.draw_graph(dirty)
        self.update_style_sheet()
        self.on_model_selection_changed(self.model.selection)
        update_time = str(int(round((time.time() - start) * 1000)))
        logger.debug("Time to update view: " + update_time + "ms")

    def update_style_sheet(self):
        layer_color = self.model.get_layer_color(self.model.target_layer)
        color_obj = QtGui.QColor(layer_color)
        light_color = QtGui.QColor()
        light_color.setHsv(color_obj.hsvHue(), color_obj.hsvSaturation() * 0.3, color_obj.value())
        style = '''
                QToolTip {
                    font-family: Roboto Mono;
                    background-color: %s
                }

                QRubberBand {
                    selection-background-color: %s
                }
                ''' % (light_color.name(), layer_color)
        self.setStyleSheet(style)

    def clear(self):
        """Remove all graphics items and clear all object dictionaries."""
        self._node_graphics = {}
        self._connection_graphics = []
        self._attr_concerns = {}
        self.scene().clear()

    def toggle_implicit_connections(self, state=None):
        if state is None:
            state = not self.model.implicit_connections
        self.model.implicit_connections = state
        self.update_view()

    def toggle_grid(self, state=None):
        if state is None:
            self.show_grid = not self.show_grid
        else:
            self.show_grid = state
        self.update()

    def frame_all(self):
        self.frame_rect(self.scene().itemsBoundingRect())

    def frame_selection(self):
        self.frame_nodes(self.model.selection)

    def frame_nodes(self, node_paths):
        bounding_rect = QtCore.QRectF()
        for path in node_paths:
            graphic = self.get_node_graphic(path)
            if not graphic:
                continue
            bounding_rect = bounding_rect.united(graphic.sceneBoundingRect())
        if bounding_rect != QtCore.QRectF():
            self.frame_rect(bounding_rect)

    def frame_rect(self, rect):
        rect_left = -1 * self.view_padding_factor
        rect_top = -1 * self.view_padding_factor
        rect_right = self.view_padding_factor
        rect_bottom = self.view_padding_factor
        padded_rect = rect.adjusted(rect_left, rect_top, rect_right, rect_bottom)
        self.fitInView(padded_rect, QtCore.Qt.KeepAspectRatio)

    def draw_graph(self, dirty):
        """Draws all nodes and connections.
        :param dirty: List of dirty node paths
        :return: None
        """
        node_paths = []
        if dirty:
            node_paths = dirty
        else:
            node_paths = self.model.get_descendants(nxt_path.WORLD,
                                                    include_implied=True)
        og_do_anims = self.do_animations
        self.do_animations = False
        self.handle_nodes_changed(node_paths)
        self.do_animations = og_do_anims

    def draw_node(self, node_path):
        graphic = self.get_node_graphic(node_path)
        if not graphic:
            graphic = NodeGraphicsItem(node_path=node_path,
                                       model=self.model,
                                       view=self)
            self._node_graphics[node_path] = graphic
        if graphic.scene() != self.scene():
            self.scene().addItem(graphic)
            graphic.setZValue(self.NODE_DEPTH)
        for attr_concerns in self._attr_concerns.get(node_path, {}).values():
            for desire in attr_concerns:
                des_node, des_attr = desire
                if des_attr == nxt_node.INTERNAL_ATTRS.INSTANCE_PATH:
                    self._draw_inst_connections(des_node)
                elif des_attr == nxt_node.INTERNAL_ATTRS.EXECUTE_IN:
                    self._draw_exec_connections(des_node)
                elif des_attr == nxt_node.INTERNAL_ATTRS.COMPUTE:
                    self._draw_code_connections(des_node)
                else:
                    self._draw_attr_connections(des_node, [des_attr])
        return graphic

    def draw_connections(self, node_path):
        # remove items
        target_node_item = self.get_node_graphic(node_path)
        self._draw_exec_connections(node_path)
        self._draw_attr_connections(node_path,
                                    target_node_item.user_attr_names)
        self._draw_code_connections(node_path)
        self._draw_inst_connections(node_path)

    def _draw_exec_connections(self, node_path):
        exec_attr = nxt_node.INTERNAL_ATTRS.EXECUTE_IN
        self.remove_attr_connection_graphics(node_path, exec_attr,
                                             side=CONNECTION_SIDES.IN)
        src_path = self.model.get_node_exec_in(node_path=node_path,
                                               layer=self.model.comp_layer)
        if not src_path:
            return
        exec_root_path = nxt_path.get_root_path(src_path)
        if src_path != exec_root_path:
            # An exec path that is not a root?
            return
        self.register_attr_concern(src_path, None,
                                   node_path, exec_attr)
        src_node_graphic = self.get_node_graphic(src_path)
        if not src_node_graphic:
            return
        tgt_path = nxt_path.make_attr_path(node_path, exec_attr)
        new_connection = AttrConnectionGraphic(self.model, self,
                                               source_path=src_path,
                                               target_path=tgt_path)
        self.add_connection_graphic(new_connection)

    def _draw_attr_connections(self, node_path, attr_names):
        # draw attr connections
        my_root_path = nxt_path.get_root_path(node_path)
        comp_layer = self.model.comp_layer
        # Target node item attr names respects 0,1,2,3 hiding of attrs.
        for attr_name in attr_names:
            self.remove_attr_connection_graphics(node_path, attr_name,
                                                 side=CONNECTION_SIDES.IN)
            source_path = self.model.get_node_attr_source_path(node_path,
                                                               attr_name,
                                                               comp_layer)
            if source_path != node_path:
                # Only draw connections for local attrs.
                continue
            sources = self.model.get_node_attr_external_sources(node_path,
                                                                attr_name,
                                                                comp_layer)
            for src in sources:
                split = nxt_path.path_attr_partition(src)
                src_node_path, src_attr_name = split
                src_root_path = nxt_path.get_root_path(src_node_path)
                if src_root_path == my_root_path:
                    # Do not draw attr connections between shared roots
                    continue
                self.register_attr_concern(src_node_path, src_attr_name,
                                           node_path, attr_name)
                tgt = nxt_path.make_attr_path(node_path, attr_name)
                new_connection = AttrConnectionGraphic(self.model, self,
                                                       source_path=src,
                                                       target_path=tgt)
                source_node_item = self.get_node_graphic(src_node_path)
                if not source_node_item:
                    continue
                self.add_connection_graphic(new_connection)

    def _draw_inst_connections(self, node_path):
        inst_attr = nxt_node.INTERNAL_ATTRS.INSTANCE_PATH
        self.remove_attr_connection_graphics(node_path, inst_attr,
                                             side=CONNECTION_SIDES.IN)
        # draw instance connections
        comp = self.model.comp_layer
        if self.model.get_node_is_proxy(node_path):
            return
        inst_path = self.model.get_node_instance_path(node_path=node_path,
                                                      layer=comp)
        if not inst_path:
            return
        if not self.model.implicit_connections:
            return
        self.register_attr_concern(inst_path, None,
                                   node_path, inst_attr)
        if not self.get_node_graphic(inst_path):
            return
        attr_path = nxt_path.make_attr_path(node_path, inst_attr)
        new_connection = AttrConnectionGraphic(self.model, self,
                                               source_path=inst_path,
                                               target_path=attr_path)
        self.add_connection_graphic(new_connection)

    def _draw_code_connections(self, node_path):
        code_attr = nxt_node.INTERNAL_ATTRS.COMPUTE
        self.remove_attr_connection_graphics(node_path, code_attr,
                                             side=CONNECTION_SIDES.IN)
        comp = self.model.comp_layer
        my_root_path = nxt_path.get_root_path(node_path)
        # draw compute connections
        sources = self.model.get_node_code_external_sources(node_path, comp)
        if not sources:
            return
        if not self.model.implicit_connections:
            return
        for src_attr_path in sources:
            split = nxt_path.path_attr_partition(src_attr_path)
            src_node_path, src_attr_name = split
            self.register_attr_concern(src_node_path, None,
                                       node_path, code_attr)
            if not self.get_node_graphic(src_node_path):
                continue
            src_root_path = nxt_path.get_root_path(src_node_path)
            if src_root_path == my_root_path:
                continue
            inst_attr_path = nxt_path.make_attr_path(node_path, code_attr)
            new_connection = AttrConnectionGraphic(self.model, self,
                                                   source_path=src_attr_path,
                                                   target_path=inst_attr_path)
            self.add_connection_graphic(new_connection)

    def remove_attr_connection_graphics(self, node_path, attr_name,
                                        side=CONNECTION_SIDES.BOTH):
        """Remove graphics that represent given node attribute. This removes
        them from the tracking as well as removes them from the graphics scene.

        :param node_path: node path for attribute
        :type node_path: str
        :param attr_name: name of attribute to remove connectons for.
        :type attr_name: str
        """
        if side == CONNECTION_SIDES.BOTH:
            sides = side
        else:
            sides = [side]
        path = (node_path, attr_name)
        to_remove = []
        for graphic in self._connection_graphics:
            if (CONNECTION_SIDES.IN in sides and
                path == (graphic.tgt_node_path, graphic.tgt_attr_name)):
                to_remove += [graphic]
            elif (CONNECTION_SIDES.OUT in sides and
                  path == (graphic.src_node_path, graphic.src_attr_name)):
                to_remove += [graphic]
        for graphic in to_remove:
            self.scene().removeItem(graphic)
            self._connection_graphics.remove(graphic)

    def remove_node_connection_graphics(self, node_path,
                                        side=CONNECTION_SIDES.BOTH):
        """Remove connection graphics that are drawn due to given node path,
        optionally on either or both sides.

        :param node_path: path to node to remove graphics for
        :type node_path: str
        :param side: Side to remove connection graphics from,
        defaults to CONNECTION_SIDES.BOTH
        :type side: CONNECTION_SIDES, optional
        """
        for graphic in self.get_node_connection_graphics(node_path, side):
            self.scene().removeItem(graphic)
            self._connection_graphics.remove(graphic)

    def get_node_connection_graphics(self, node_path,
                                     side=CONNECTION_SIDES.BOTH):
        """Get connection graphics connected to given node path. Optionally
        on either or both sides.

        :param node_path: node path to get connection graphics for.
        :type node_path: str
        :param side: side of the node to get connections for,
        defaults to CONNECTION_SIDES.BOTH
        :type side: CONNECTION_SIDES, optional
        :return: list of connection graphics.
        :rtype: list
        """
        if side == CONNECTION_SIDES.BOTH:
            sides = side
        else:
            sides = [side]
        connections = []
        for graphic in self._connection_graphics:
            if (CONNECTION_SIDES.IN in sides and
                node_path == graphic.tgt_node_path):
                connections += [graphic]
            if (CONNECTION_SIDES.OUT in sides and
                node_path == graphic.src_node_path):
                connections += [graphic]
        return connections

    def register_attr_concern(self, src_node_path, src_attr_name,
                              tgt_node_path, tgt_attr_name):
        """Register a concern(desire for connection) by target node/attr for
        source node/attr. Used to track need for a connection when a node
        graphic comes into existence.
        An example of data formatted by given arguments.
        {
            '/src/node/path': {
                'src_attr_name' : [
                    ('/tgt/node/path', 'tgt_attr_name')
                ]
            }
        }

        :param src_node_path: host node of attr that target node/attr desires
        :type src_node_path: str
        :param src_attr_name: src attribute name on source node path
        :type src_attr_name: str
        :param tgt_node_path: host node of attr that desires source node/attr
        :type tgt_node_path: str
        :param tgt_attr_name: attribute that is concerned with source.
        :type tgt_attr_name: str
        """
        self._attr_concerns.setdefault(src_node_path, {})
        self._attr_concerns[src_node_path].setdefault(src_attr_name, [])
        concern = (tgt_node_path, tgt_attr_name)
        src_attr_concerns = self._attr_concerns[src_node_path][src_attr_name]
        if concern not in src_attr_concerns:
            src_attr_concerns += [concern]

    def add_connection_graphic(self, graphic):
        """Add given connection graphic to the scene and track.

        :param graphic: Connection graphic to add
        :type graphic: AttrConnectionGraphic
        """
        self.scene().addItem(graphic)
        graphic.setZValue(self.CONNECTION_DEPTH)
        self._connection_graphics += [graphic]

    def drawBackground(self, painter, rect):
        super(StageView, self).drawBackground(painter, rect)

        rect = self.sceneRect()
        painter.fillRect(rect, QtGui.QBrush(colors.GRAPH_BG_COLOR))

        left = int(rect.left()) - (int(rect.left()) % self.draw_grid_size)
        top = int(rect.top()) - (int(rect.top()) % self.draw_grid_size)

        if self.show_grid:
            # draw grid vertical lines
            for x in range(left, int(rect.right()), self.draw_grid_size):
                if x % (self.draw_grid_size * 10.0) == 0.0:
                    painter.setPen(QtGui.QPen(QtGui.QColor(20, 20, 20), 1.0, QtCore.Qt.SolidLine))
                else:
                    painter.setPen(QtGui.QPen(QtGui.QColor(100, 100, 100, 100), 1.0, QtCore.Qt.SolidLine))
                painter.drawLine(x, rect.top(), x, rect.bottom())

            # draw grid horizontal lines
            for y in range(top, int(rect.bottom()), self.draw_grid_size):
                if y % (self.draw_grid_size * 10.0) == 0.0:
                    painter.setPen(QtGui.QPen(QtGui.QColor(20, 20, 20), 1.0, QtCore.Qt.SolidLine))
                else:
                    painter.setPen(QtGui.QPen(QtGui.QColor(100, 100, 100, 100), 0.5, QtCore.Qt.SolidLine))
                painter.drawLine(rect.left(), y, rect.right(), y)

    def add_node(self):
        sel_node_paths = self.model.get_selected_nodes()
        if sel_node_paths:
            parent_item = self.get_node_graphic(sel_node_paths[0])
            if parent_item:
                parent_path = parent_item.node_path
                if parent_path:
                    self.new_node(parent_path=parent_path)

        else:
            # new node in the scene at mouse position
            mouse_pos = self.mapFromGlobal(QtGui.QCursor.pos())
            pos = self.mapToScene(mouse_pos)
            self.new_node(pos=[pos.x(), pos.y()])

    def new_node(self, name='node', parent_path=None, pos=None):
        """Creates a new node object on the target layer which triggers a view update.

        :param name: name of new node
        :type name: str

        :param parent_path: node to parent new node to
        :type parent_path: comptree.CompTreeNode | None

        :param pos: position for new node
        :type pos: list | tuple | None
        """
        self.model.add_node(name=name, parent_path=parent_path, pos=pos,
                            layer=self.model.target_layer)

    def rename_node(self):
        sel_node_paths = self.model.get_selected_nodes()
        if not sel_node_paths:
            return
        item = self.get_node_graphic(sel_node_paths[0])
        item.rename_node()

    def paste_nodes(self, pos=None, parent_path=None):
        if not pos:
            mouse_pos = self.mapToScene(self.mapFromGlobal(QtGui.QCursor.pos()))
            pos = [mouse_pos.x(), mouse_pos.y()]
        if not parent_path:
            sel_node_paths = self.model.get_selected_nodes()
            if sel_node_paths:
                parent_path = sel_node_paths[-1]
                pos = None
        self.model.paste_nodes(pos=pos, parent_path=parent_path,
                               layer=self.model.target_layer)

    def select_all(self):
        node_paths = list(self._node_graphics.keys())
        self.model.set_selection(paths=node_paths)

    def keyPressEvent(self, event):
        key = event.key()
        if key not in self._held_keys:
            self._held_keys.append(key)
        self.zooming = False
        if self._parent.zoom_keys_down:
            if self.zoom_button_down:
                self._previous_mouse_pos = self.mouse_scene_pos
                self.zooming = True
        super(StageView, self).keyPressEvent(event)

    def keyReleaseEvent(self, event):
        key = event.key()
        if key in self._held_keys:
            self._held_keys.remove(key)
        self.zooming = False
        if self._parent.zoom_keys_down:
            if self.zoom_button_down:
                self._previous_mouse_pos = self.mouse_scene_pos
                self.zooming = True
        super(StageView, self).keyReleaseEvent(event)

    def mousePressEvent(self, event):
        # capture initial click position which is used in the release event
        self._clicked_something_locked = False
        self._initial_click_pos = event.pos()
        self.zoom_button_down = event.button() is self.zoom_button
        self.zooming = False
        if self._parent.zoom_keys_down and self.zoom_button_down:
            self.zooming = True
            self.zoom_start_pos = event.pos()
            self._previous_mouse_pos = event.pos()
            event.accept()
        if event.buttons() == QtCore.Qt.LeftButton | QtCore.Qt.MidButton:
            self.zooming = True
            self.zoom_start_pos = event.pos()
            self._previous_mouse_pos = event.pos()
            event.accept()

        # left button event
        if event.button() == QtCore.Qt.LeftButton:
            # get item under event
            item = self.itemAt(event.pos())

            # click event in open area of scene could be start of
            # rubber band action. position recorded as rubber band origin.
            if not item:
                self._rubber_band_origin = event.pos()
                self.rubber_band.setGeometry(QtCore.QRect())
                return
            item_path = self.get_sel_path_for_graphic(item)
            if not item_path:
                # Any click on a graphics item that isn't selectable
                super(StageView, self).mousePressEvent(event)
                return
            not_intractable = self.model.get_node_locked(item_path)
            if not_intractable:
                self._clicked_something_locked = True
            # item interaction
            curr_sel = self.model.is_selected(item_path)
            mods = event.modifiers()
            if mods == QtCore.Qt.NoModifier and not curr_sel:
                self.model.set_selection([item_path])
                event.accept()

            elif mods == self.SEL_ADD_MODIFIERS:
                self.model.add_to_selection([item_path])
                return  # block immediate node movement

            # toggle item selection
            elif mods == self.SEL_TOGGLE_MODIFIERS:
                self.model.set_selected(item_path, not curr_sel)
                return  # block immediate node movement

            # de-select item
            elif mods == self.SEL_RMV_MODIFIERS:
                self.model.remove_from_selection([item_path])
                return  # block immediate node movement

        # middle and right button events
        elif event.button() == QtCore.Qt.MiddleButton:
            # start panning action
            self.panning = True
            self._previous_mouse_pos = None
            event.accept()
            return

        super(StageView, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # rubber band action
        if self._rubber_band_origin is not None:
            self.rubber_band.show()
            rect = QtCore.QRect(self._rubber_band_origin, event.pos()).normalized().translated(4, 4)
            self.rubber_band.setGeometry(rect)

        # connection action
        self.mouse_scene_pos = self.mapToScene(event.pos())
        if self.potential_connection:
            self.potential_connection.rebuild_line()

        # zooming action
        if self.zooming:
            if not self._previous_mouse_pos:
                self._previous_mouse_pos = event.pos()
            dist_x = event.pos().x() - self._previous_mouse_pos.x()
            zoom_pref_key = user_dir.USER_PREF.ZOOM_MULT
            pref_mult = user_dir.user_prefs.get(zoom_pref_key, 1.0)
            mult = pref_mult * 0.005
            dist = dist_x * mult + 1.0
            self._view_pos = self.zoom_start_pos
            self._scene_pos = self.mapToScene(self._view_pos)
            if 0 < dist < 1:
                if self.scale_factor > self._scale_minimum:
                    self.scale(dist, dist)
                    self._center_view()
                else:
                    self.scale(1, 1)
            elif dist > 1:
                if self.scale_factor < self._scale_maximum:
                    self.scale(dist, dist)
                    self._center_view()
                else:
                    self.scale(1, 1)
            self._previous_mouse_pos = event.pos()
            event.accept()
            return

        # panning action
        if self.panning:
            if not self._previous_mouse_pos:
                self._previous_mouse_pos = event.pos()
            offset = QtCore.QPointF(self._previous_mouse_pos - event.pos())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + offset.y())
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + offset.x())
            self._current_pan_distance += math.sqrt(abs(offset.x()) ** 2 + abs(offset.y()) ** 2)
            self._previous_mouse_pos = event.pos()
            event.accept()
            return
        super(StageView, self).mouseMoveEvent(event)
        item = self.itemAt(event.pos())
        app = QtWidgets.QApplication
        if item and hasattr(item, 'locked') and item.locked:
            if not app.overrideCursor():
                app.setOverrideCursor(QtCore.Qt.ForbiddenCursor)
        else:
            app.restoreOverrideCursor()

    def mouseReleaseEvent(self, event):
        was_just_zooming = self.zooming
        self.zooming = False
        if event.button() is self.zoom_button:
            self.zoom_button_down = False
        if self._parent.zoom_keys_down and self.zoom_button_down:
            self.zooming = True
            event.accept()

        if self.zooming:
            if event.buttons() == QtCore.Qt.LeftButton | QtCore.Qt.MidButton:
                self.zooming = False
            elif event.buttons() == QtCore.Qt.LeftButton:
                self.zooming = False
            elif event.buttons() == QtCore.Qt.MidButton:
                self.zooming = False
        if (self._rubber_band_origin is not None and
           event.button() is QtCore.Qt.LeftButton):
            # complete rubber band action
            self._rubber_band_origin = None
            rubber_band_geo = self.mapToScene(self.rubber_band.geometry())
            selection_area_rect = rubber_band_geo.boundingRect()
            # end rubber band action
            self.rubber_band.hide()
            # get items under selection area
            node_paths = []
            for item in self.scene().items(selection_area_rect):
                if isinstance(item, NodeGraphicsItem):
                    node_paths.append(item.node_path)
            selected_paths = node_paths
            if selected_paths:
                # add items to selection
                if event.modifiers() == self.SEL_ADD_MODIFIERS:
                    self.model.add_to_selection(selected_paths)

                # toggle items (add/remove) from selection
                elif event.modifiers() == self.SEL_TOGGLE_MODIFIERS:
                    for path in selected_paths:
                        curr_selected = self.model.is_selected(path)
                        self.model.set_selected(path, not curr_selected)

                # remove items from selection
                elif event.modifiers() == self.SEL_RMV_MODIFIERS:
                    self.model.remove_from_selection(selected_paths)

                # Since no modifiers are being used this is a new selection.
                else:
                    self.model.set_selection(selected_paths)

            # consume selection action if any selection modifiers
            elif not (event.modifiers() == self.SEL_TOGGLE_MODIFIERS or
                      event.modifiers() == self.SEL_RMV_MODIFIERS or
                      event.modifiers() == self.SEL_ADD_MODIFIERS):
                self.model.clear_selection()

        elif event.button() is QtCore.Qt.LeftButton and not self.potential_connection:
            # consume the release event if any combination of shift and ctrl are being held. this
            # release event could be the last sequence in a rubber band selection action where
            # items were being added or removed by holding down those keys. nothing needs to be
            # done here.
            if (event.modifiers() == QtCore.Qt.ControlModifier or
                    event.modifiers() == QtCore.Qt.ShiftModifier | QtCore.Qt.ControlModifier):
                # event.modifiers() == QtCore.Qt.ShiftModifier
                return

            else:
                # if the release event's position is the same as the initial click position it means
                # this is not the end of a drag-drop action. this must be the final step of a new
                # selection. if there is an item is under the event it is selected now.
                if self._initial_click_pos == event.pos():
                    item = self.itemAt(event.pos())
                    if not item:
                        self.model.clear_selection()
                    return
                # could be end of moving nodes around the scene.
                else:
                    node_positions = {}
                    for item in self.scene().selectedItems():
                        if isinstance(item, NodeGraphicsItem):
                            pos = [item.pos().x(), item.pos().y()]
                            node_positions[item.node_path] = pos

                    if node_positions:
                        if self.model.target_layer.layer_idx() == 0:
                            layer = self.model.target_layer
                        else:
                            layer = self.model.top_layer
                        self.model.set_nodes_pos(node_positions, layer=layer)

        # complete connection action
        if self.potential_connection and event.button() is QtCore.Qt.LeftButton:
            items_released_on = self.items(event.pos())
            # using the 1 index item here because the 0 index thing will always be the connection
            if len(items_released_on) > 1:
                if isinstance(items_released_on[1], NodeGraphicsPlug):
                    dropped_plug = items_released_on[1]
                    dropped_node_path = dropped_plug.parentItem().node_path
                    locked = self.model.get_node_locked(dropped_node_path)
                    dropped_attr_name = dropped_plug.attr_name_represented
                    exec_attr_name = nxt_node.INTERNAL_ATTRS.EXECUTE_IN
                    if (dropped_attr_name not in nxt_node.INTERNAL_ATTRS.ALL
                            and not locked):
                        if self.potential_connection.src_path:
                            if dropped_plug.is_input:
                                # Fixme: This isn't how tokens are created now
                                value = '${%s}' % self.potential_connection.src_path
                                self.model.set_node_attr_value(node_path=dropped_node_path,
                                                               attr_name=dropped_attr_name,
                                                               value=value,
                                                               layer=self.model.target_layer)
                            else:
                                logger.warning("cannot make connections from output to output.")
                        elif self.potential_connection.tgt_path:
                            if not dropped_plug.is_input:
                                dropped_attr_path = nxt_path.make_attr_path(dropped_node_path, dropped_attr_name)
                                value = tokens.make_token_str(dropped_attr_path)
                                target_node_path = self.potential_connection.tgt_node_path
                                self.model.set_node_attr_value(node_path=target_node_path,
                                                               attr_name=self.potential_connection.tgt_attr_name,
                                                               value=value,
                                                               layer=self.model.target_layer)
                            else:
                                logger.warning("cannot make connections from input to inputs")
                    elif dropped_attr_name == exec_attr_name and not locked:
                        src_path = self.potential_connection.src_node_path
                        tgt_path = self.potential_connection.tgt_node_path
                        locked = all((not locked,
                                      self.model.get_node_locked(tgt_path)))
                        if src_path and not locked:
                            if dropped_plug.is_input:
                                self.model.set_node_exec_in(node_path=dropped_node_path,
                                                            source_node_path=src_path,
                                                            layer=self.model.target_layer)
                            else:
                                logger.warning("cannot make connections from output to output.")
                        elif tgt_path and not locked:
                            if not dropped_plug.is_input:
                                self.model.set_node_exec_in(node_path=tgt_path,
                                                            source_node_path=dropped_node_path,
                                                            layer=self.model.target_layer)
                            else:
                                logger.warning("cannot make connections from input to input")
            if self.potential_connection:
                self.scene().removeItem(self.potential_connection)
                self.potential_connection = None

        right_button_release = event.button() == QtCore.Qt.RightButton
        if right_button_release and not was_just_zooming:
            # spawn context menu
            self.block_context_menu = False
            self.contextMenuEvent(event)
        # complete panning action
        if self.panning and event.button() == QtCore.Qt.MiddleButton:
            self._previous_mouse_pos = None
            self.panning = False
            self._current_pan_distance = 0.0
            event.accept()
            return
        super(StageView, self).mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        event.pos()
        if event.button() == QtCore.Qt.LeftButton:
            item = self.itemAt(event.pos())
            # TODO this is strictly a nodegraphicsitem's job, move there.
            if item and isinstance(item, NodeGraphicsItem):
                if modifiers == QtCore.Qt.ControlModifier:
                    item.rename_node()
                elif modifiers == QtCore.Qt.ShiftModifier:
                    item.collapse_node(recursive=True)
                elif modifiers == QtCore.Qt.AltModifier:
                    # debug helper
                    pass
                else:
                    item.collapse_node()

    def wheelEvent(self, event):
        self._view_pos = event.pos()
        self._scene_pos = self.mapToScene(self._view_pos)

        try:
            new_scale = event.delta() * .001 + 1.0
        except AttributeError:
            new_scale = 1.1

        if 0 < new_scale < 1:
            if self.scale_factor > self._scale_minimum:
                self.scale(new_scale, new_scale)
                self._center_view()
            else:
                self.scale(1, 1)
        elif new_scale > 1:
            if self.scale_factor < self._scale_maximum:
                self.scale(new_scale, new_scale)
                self._center_view()
            else:
                self.scale(1, 1)
        event.accept()
        return

    def _center_view(self):
        view_center = self.mapToScene(self.viewport().rect().center())
        delta = self.mapToScene(self._view_pos) - view_center
        self.centerOn(self._scene_pos - delta)

    def anim_finished(self):
        if self._num_scheduled_scalings > 0:
            self._num_scheduled_scalings -= 1
        else:
            self._num_scheduled_scalings += 1

    def start_connection_draw(self, src_path=None, tgt_path=None):
        """Start drawing a connection from either source or target. With
        missing end drawing toward the mouse. If the mouse is released on the
        correct side of another attribute, an attr sub token will be set as
        the value for the relevant target attr path.
        :param src_path: Potential source attribute.
        :param tgt_path: Potential target attribute.
        """
        if src_path is not None and tgt_path is not None:
            raise ValueError('Must start conneciton draw with exactly one '
                             'path: a source or target path.')
        if src_path is None:
            src_path = ''
        if tgt_path is None:
            tgt_path = ''
        self.potential_connection = AttrConnectionGraphic(self.model, self,
                                                          source_path=src_path,
                                                          target_path=tgt_path)
        self.scene().addItem(self.potential_connection)
        self.potential_connection.setZValue(self.POTENTIAL_CONNECTION_DEPTH)

    def contextMenuEvent(self, event):
        if self.block_context_menu:  # Check if we shouldn't spawn the menu
            return
        menu = QtWidgets.QMenu(self)
        item = self.itemAt(self._initial_click_pos)
        if isinstance(item, NodeGraphicsItem):
            hov_path = item.node_path
            exec_hovered_text = 'Execute {}'.format(hov_path)
            exec_hovered_action = menu.addAction(exec_hovered_text)

            def exec_hovered():
                self.model.execute_nodes([hov_path])
            exec_hovered_action.triggered.connect(exec_hovered)
        selected_nodes = self.model.get_selected_nodes()
        selected_nodes_count = len(selected_nodes)
        nodes_only_on_tgt = True
        for node in selected_nodes:
            src = self.model.get_node_source_layer(node)
            if src != self.model.target_layer:
                nodes_only_on_tgt = False
                break
        if selected_nodes_count > 0:
            menu.addAction(self.exec_actions.execute_selected_action)
        if selected_nodes_count == 1:
            menu.addAction(self.exec_actions.execute_from_action)
            menu.addAction(self.exec_actions.execute_hierarchy_action)
        if selected_nodes_count > 0:
            menu.addAction(self.authoring_actions.disable_node_action)
            menu.addSeparator()
        if selected_nodes_count <= 1:
            menu.addAction(self.authoring_actions.add_node_action)
        if selected_nodes_count == 1:
            menu.addAction(self.authoring_actions.rename_node_action)
        if selected_nodes_count > 0:
            menu.addAction(self.authoring_actions.delete_node_action)
        menu.addSeparator()
        if selected_nodes_count > 0:
            menu.addAction(self.authoring_actions.cut_node_action)
            menu.addAction(self.authoring_actions.copy_node_action)
        menu.addAction(self.authoring_actions.paste_node_action)
        if selected_nodes_count > 0:
            menu.addSeparator()
            menu.addAction(self.authoring_actions.duplicate_node_action)
            menu.addAction(self.authoring_actions.instance_node_action)
            menu.addAction(self.authoring_actions.remove_instance_action)
            menu.addSeparator()
            menu.addAction(self.authoring_actions.localize_node_action)
            if nodes_only_on_tgt:
                menu.addAction(self.authoring_actions.revert_node_action)
        has_start = False
        for path in selected_nodes:
            if self.model.get_is_node_start(path):
                has_start = True
                break
        if selected_nodes_count == 1 or has_start:
            menu.addSeparator()
        if selected_nodes_count == 1:
            add_attr = self.main_window.property_editor.add_attr_action
            menu.addAction(add_attr)
            menu.addAction(self.authoring_actions.revert_child_order_action)
        if has_start:
            menu.addAction(self.exec_actions.revert_start_action)
        menu.exec_(self.mapToGlobal(self._initial_click_pos))
        self.block_context_menu = True  # Set the block var to true again

    @staticmethod
    def get_sel_path_for_graphic(graphic):
        # NOTE maybe this can be a subclass for graphics items?
        if isinstance(graphic, NodeGraphicsItem):
            return graphic.node_path
        # if isinstance(graphic, AttrConnectionGraphic):
        #     return graphic.tgt_path
        return None

    def on_model_selection_changed(self, new_selection):
        if not new_selection:
            self.scene().clearSelection()
            return
        # Copy to prevent modifying model selection.
        new_selection = list(new_selection)

        # de-select items that were previously selected
        for graphic in self.scene().selectedItems():
            if isinstance(graphic, NodeGraphicsItem):
                path = graphic.node_path
            # elif isinstance(graphic, AttrConnectionGraphic):
            #     path = graphic.tgt_path
            else:
                logger.warning("Unknown item selected: " + str(graphic))
                continue
            if path not in new_selection:
                graphic.setSelected(False)
            else:
                # Item is already selected, remove to speed up next step.
                new_selection.remove(path)

        for path in new_selection:
            graphic = self._node_graphics.get(path)
            if graphic:
                graphic.setSelected(True)
                continue
            # TODO Track connections by target path to allow attr connections
            #  to be added here.
            if path != nxt_path.WORLD:
                logger.error("Cannot find item to select: " + str(path))

    def handle_nodes_changed(self, node_paths):
        updated_paths = []
        roots_hit = set()
        new_nodes = []
        for path in node_paths:
            if path == nxt_path.WORLD:
                # never draw world node.
                continue
            if self.model.get_collapsed_ancestor(path):
                continue
            graphic = self.get_node_graphic(path)
            exists = self.model.node_exists(path)
            if exists:
                implied = False
            else:
                implied = self.model.node_is_implied(path)
            if exists or implied:
                updated_paths += [path]
                if graphic:
                    pre_update_bb = graphic.boundingRect()
                    graphic.update_from_model()
                    post_update_bb = graphic.boundingRect()
                    # If size changed re-draw the updated bounding box
                    if pre_update_bb != post_update_bb:
                        rad = NodeGraphicsItem.ATTR_PLUG_RADIUS
                        margins = QtCore.QMargins(rad, rad, rad, rad)
                        update_bb = pre_update_bb.marginsAdded(margins)
                        update_bb = graphic.mapRectToScene(update_bb)
                        self.scene().update(update_bb)
                else:
                    self.draw_node(path)
            else:
                if not graphic:
                    continue
                self.remove_node_graphic(path)
                parent_path = nxt_path.get_parent_path(path)
                if parent_path is not nxt_path.WORLD:
                    self.handle_nodes_changed([parent_path])
            roots_hit.add(nxt_path.get_root_path(path))
        for root in roots_hit:
            graphic = self.get_node_graphic(root)
            if not graphic:
                continue
            graphic.arrange_descendants()
        for node_path in updated_paths:
            self.draw_connections(node_path)

    def handle_attrs_changed(self, attr_paths):
        """Handler for the model signal 'attrs_changes'.
        :param attr_paths: Tuple of attr paths /node.attr
        :return: None
        """
        start = time.time()
        attr_map = {}
        for attr_path in attr_paths[:]:
            attr_name = nxt_path.attr_name_from_attr_path(attr_path)
            node_path = nxt_path.node_path_from_attr_path(attr_path)
            attr_map.setdefault(node_path, [])
            graphic = self.get_node_graphic(node_path)
            if not graphic:
                continue
            if attr_name == nxt_node.INTERNAL_ATTRS.CHILD_ORDER:
                graphic.arrange_descendants()
            if attr_name == nxt_node.INTERNAL_ATTRS.INSTANCE_PATH:
                self._draw_inst_connections(node_path)
            if attr_name == nxt_node.INTERNAL_ATTRS.COMPUTE:
                self._draw_code_connections(node_path)
            else:
                attr_names = attr_map.get(node_path)
                attr_names += [attr_name]

        for node_path, attr_names in attr_map.items():
            node_graphic = self.get_node_graphic(node_path)
            if not node_graphic:
                continue
            node_graphic.update_plugs()
            self._draw_attr_connections(node_path, attr_names)
        update_time = str(int(round((time.time() - start) * 1000)))
        logger.debug("Time to update attrs: " + update_time + "ms")

    def handle_node_move(self, node_path, pos):
        node_item = self.get_node_graphic(node_path)
        if node_item:
            node_item.setPos(pos[0], pos[1])

    def handle_collapse_changed(self, node_paths):
        while self._animating:
            QtWidgets.QApplication.processEvents()
        og_do_anims = self.do_animations
        self.do_animations = self._do_anim_pref
        comp_layer = self.model.comp_layer
        roots_hit = set()
        for path in node_paths:
            if self.model.get_collapsed_ancestor(path):
                self.remove_node_graphic(path)
                continue
            graphic = self.get_node_graphic(path)
            if graphic:
                graphic.update_collapse()
            collapsed = self.model.get_node_collapse(path, comp_layer)
            if collapsed:
                descendants = self.model.get_descendants(path,
                                                         include_implied=True)
                for child_path in descendants:
                    self.remove_node_graphic(child_path)
                if descendants:
                    roots_hit.add(nxt_path.get_root_path(path))
            else:
                descendants = self.model.get_descendants(path,
                                                         include_implied=True)
                self.handle_nodes_changed(descendants)
        for root_path in roots_hit:
            root_graphic = self.get_node_graphic(root_path)
            if not root_graphic:
                continue
            root_graphic.arrange_descendants()
        self.do_animations = og_do_anims

    def remove_node_graphic(self, node_path):
        if node_path not in self._node_graphics:
            return
        graphic = self._node_graphics.pop(node_path)
        if not graphic:
            return
        self.remove_node_connection_graphics(node_path)

        def handle_del():
            self.scene().removeItem(graphic)

        graphic.out_anim_group.finished.connect(handle_del)
        graphic.anim_out()

    def get_node_graphic(self, name):
        return self._node_graphics.get(name, None)


class HUDItem(QtWidgets.QLabel):

    """Simple heads-up display label that can be positioned around the Graph View interface."""

    def __init__(self, fade_time=1500, start_color=None, end_color=None, *args, **kwargs):
        """Initializes a hud item QLabel with font and fade settings provided.

        :param font: font to use for this label
        :type font: QtGui.QFont

        :param fade_time: how long fade should take (0 is no fade)
        :type fade_time: float | int

        :param start_color: color to begin with before fading
        :type start_color: QtGui.QColor

        :param end_color: default color - where the fade ends
        :type end_color: QtGui.QColor
        """
        super(HUDItem, self).__init__(*args, **kwargs)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)

        # local attrs
        self.start_color = start_color or QtGui.QColor(255, 255, 255, 255)
        self.end_color = end_color or QtGui.QColor(255, 255, 255, 100)
        self.fade_time = fade_time

        # animation object
        self.animation = QtCore.QVariantAnimation()
        self.animation.valueChanged.connect(self.set_color)

        # set color
        self.set_color(self.end_color)

    def setText(self, *args, **kwargs):
        """Overloading this method to trigger the fade_out animation when the text changes"""
        super(HUDItem, self).setText(*args, **kwargs)
        if hasattr(self, 'fade_time'):
            if self.fade_time > 0:
                self.fade_out()

    def set_color(self, color):
        """Applies color as it changes to the stylesheet of the HUD item"""
        style = 'color: rgba({0}, {1}, {2}, {3})'.format(color.red(),
                                                         color.green(),
                                                         color.blue(),
                                                         color.alpha())
        self.setStyleSheet(style)

    def fade_out(self):
        """Initiates a fadeout animation"""
        self.animation.stop()
        self.animation.setStartValue(self.start_color)
        self.animation.setEndValue(self.end_color)
        self.animation.setDuration(self.fade_time)
        self.animation.start()


class GraphicsScene(QtWidgets.QGraphicsScene):
    def __init__(self, parent):
        super(GraphicsScene, self).__init__(parent=parent)
        self._parent = parent

    def dragEnterEvent(self, event):
        super(GraphicsScene, self).dragEnterEvent(event)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            # event.accept()
            pass

    def dragMoveEvent(self, event):
        super(GraphicsScene, self).dragMoveEvent(event)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            # event.accept()
            pass

    def dropEvent(self, event):
        super(GraphicsScene, self).dropEvent(event)
        urls = event.mimeData().urls()
        for url in urls:
            file_path = url.toLocalFile()
            self._parent.load_file(file_path)
