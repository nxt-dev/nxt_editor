# Built-in
import copy
import math
import logging
import time
from collections import namedtuple
from functools import partial

# External
from Qt import QtWidgets
from Qt import QtGui
from Qt import QtCore
from Qt import QtCompat

# Interal
import nxt_editor
from nxt import nxt_node, tokens
from nxt_editor.constants import FONTS
from nxt_editor.node_graphics_item import NodeGraphicsItem, NodeGraphicsPlug
from nxt_editor.backdrop_graphics_item import (BackdropGraphicsItem,
                                               BackdropEditDialog)
from nxt_editor import align, auto_layout, backdrops, bookmarks, theme
from nxt_editor.connection_graphics_item import (AttrConnectionGraphic,
                                                  WirePointGraphic)
from nxt_editor import connection_graphics_item as lines
from nxt_editor import sub_graphs, user_dir, wires
from nxt_editor.dialogs import NxtWarningDialog
from nxt_editor.layer_color_dialog import LayerColorDialog
from nxt_editor.mini_map import MiniMap, node_scene_rect
from nxt_editor.commands import *
from nxt_editor import colors
from .user_dir import USER_PREF, user_prefs

logger = logging.getLogger(nxt_editor.LOGGER_NAME)


#: A plug a line being dragged can be dropped on, see
#: StageView.snap_plug_near. pos is in the scene.
PlugTarget = namedtuple('PlugTarget', 'node_path attr_name is_input pos '
                                      'radius')


class CONNECTION_SIDES:
    IN = 'input'
    OUT = 'output'
    BOTH = (IN, OUT)


class ConnectionGraphics(object):
    """The view's connection graphics, in the order they were added, with
    lookups by the node and attr at either end.

    Iterates like the list it replaces. Finding the lines at a node used to
    walk every line in the graph, which made drawing a graph quadratic in
    its line count.
    """
    def __init__(self):
        self._order = {}  # graphic: the order it was added in
        self._next = 0
        # (node path, attr name) or node path: {graphic: None}, in order.
        self._by_tgt = {}
        self._by_src = {}
        self._by_tgt_node = {}
        self._by_src_node = {}

    def __iter__(self):
        return iter(list(self._order))

    def __len__(self):
        return len(self._order)

    def __bool__(self):
        return bool(self._order)

    def __contains__(self, graphic):
        return graphic in self._order

    def _indexes(self, graphic):
        return ((self._by_tgt, (graphic.tgt_node_path,
                                graphic.tgt_attr_name)),
                (self._by_src, (graphic.src_node_path,
                                graphic.src_attr_name)),
                (self._by_tgt_node, graphic.tgt_node_path),
                (self._by_src_node, graphic.src_node_path))

    def add(self, graphic):
        if graphic in self._order:
            return
        self._order[graphic] = self._next
        self._next += 1
        for index, key in self._indexes(graphic):
            index.setdefault(key, {})[graphic] = None

    def remove(self, graphic):
        """Remove a graphic, raising ValueError if it isn't here, like
        list.remove."""
        if graphic not in self._order:
            raise ValueError('Connection graphic is not tracked.')
        del self._order[graphic]
        for index, key in self._indexes(graphic):
            bucket = index.get(key)
            if bucket is not None:
                bucket.pop(graphic, None)
                if not bucket:
                    del index[key]

    def _in_order(self, graphics):
        return sorted(graphics, key=self._order.__getitem__)

    def at_attr(self, node_path, attr_name, sides):
        """Lines into (or out of) one attr, in the order added."""
        key = (node_path, attr_name)
        found = {}
        if CONNECTION_SIDES.IN in sides:
            found.update(self._by_tgt.get(key, {}))
        if CONNECTION_SIDES.OUT in sides:
            found.update(self._by_src.get(key, {}))
        return self._in_order(found)

    def at_node(self, node_path, sides):
        """Lines at a node, in the order added. A line with both ends at
        the node is listed once per side asked for, as before."""
        found = {}
        if CONNECTION_SIDES.IN in sides:
            found.update(self._by_tgt_node.get(node_path, {}))
        if CONNECTION_SIDES.OUT in sides:
            found.update(self._by_src_node.get(node_path, {}))
        out = []
        for graphic in self._in_order(found):
            if (CONNECTION_SIDES.IN in sides and
                    graphic.tgt_node_path == node_path):
                out += [graphic]
            if (CONNECTION_SIDES.OUT in sides and
                    graphic.src_node_path == node_path):
                out += [graphic]
        return out


class StageView(QtWidgets.QGraphicsView):
    """Primary display/edit widget for node hierarchies of an nxt graph.
    Displays nodes in visual hierarchies and allows selection, parenting, and
    arranging.
    """
    POTENTIAL_CONNECTION_DEPTH = 30
    CONNECTION_DEPTH = -10
    NODE_DEPTH = 0
    # Behind the connections, so a wire across a backdrop stays visible.
    BACKDROP_DEPTH = -1000
    # Room left around the nodes a new backdrop is drawn around.
    BACKDROP_PADDING = 40
    # How far past a plug's edge, in pixels on screen whatever the zoom, a
    # line being dragged still snaps to it, see snap_plug_near.
    PLUG_SNAP_PIXELS = 12
    # Held down, a left drag pans the graph as a middle drag does.
    PAN_KEY = QtCore.Qt.Key_Space

    def __init__(self, model, parent=None):
        super(StageView, self).__init__(parent=parent)
        self.main_window = parent
        # Off by default. Every node animates separately, so opening a
        # parent with a lot of children spends most of its time on the
        # animation rather than on drawing the result.
        self._do_anim_pref = user_prefs.get(USER_PREF.ANIMATION, False)
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
        self.setOptimizationFlag(QtWidgets.QGraphicsView.DontSavePainterState, enabled=True)
        self.setOptimizationFlag(QtWidgets.QGraphicsView.DontAdjustForAntialiasing, enabled=True)
        # The grid is drawn once into a pixmap and kept, rather than drawn
        # again under every node that moves. Panning draws only the strip
        # that comes into view, and zooming starts the pixmap over.
        self.setCacheMode(QtWidgets.QGraphicsView.CacheBackground)
        # scene
        self._scene = QtWidgets.QGraphicsScene()
        self.setScene(self._scene)
        # The canvas has no edge: see make_room.
        self.scene().setSceneRect(self.SCENE_START)
        # rubber band
        self.rubber_band = QtWidgets.QRubberBand(QtWidgets.QRubberBand.Rectangle, self)

        # navigation attributes
        self._held_keys = []
        self._rubber_band_origin = None
        self._initial_click_pos = None
        self._clicked_something_locked = False
        self.new_node_selected = False
        self.panning = False
        # Space held down turns a left drag into panning, for anyone
        # without a middle button. See PAN_KEY.
        self._pan_key_held = False
        self._pan_key_panning = False
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
        self._connection_graphics = ConnectionGraphics()
        # Nodes of a big graph not drawn yet, drawn while the editor is idle,
        # see draw_graph: {root path: [its node paths, in drawing order]},
        # and each of those paths' root.
        self._pending_draw = {}
        self._pending_root_of = {}
        self._pending_timer = QtCore.QTimer(self)
        self._pending_timer.setSingleShot(True)
        self._pending_timer.setInterval(0)
        self._pending_timer.timeout.connect(self._draw_some_pending)
        # How the view was framed when the graph was opened, while it still
        # is, so it can be framed again once every node is drawn and its
        # size known. See frame_opened.
        self._open_frame = None
        self._mini_map_marked = 0.0
        self._pending_slice_end = 0.0
        self._attr_concerns = {}
        self._backdrop_graphics = {}
        # Whether a layer was hidden the last time visibility was applied,
        # so a graph with every layer showing never pays for the check.
        self._layers_were_hidden = False
        # The nodes hidden with their layers, worked out once each time
        # visibility is applied. See apply_layer_visibility.
        self._hidden_nodes = frozenset()
        # What a backdrop being moved or resized started from, see
        # backdrop_press.
        self._backdrop_drag = None
        # How lines are drawn, kept here so moving a node does not ask the
        # layers for them again, see draw_wires.
        self.connection_style = model.get_connection_style()
        self._line_points = model.get_line_points()
        # Selected points as (line key, index), and the one being dragged.
        self._selected_points = set()
        self._point_drag = None
        self.prev_build_focus_path = None
        # A tab nobody has selected has nobody to show a graph to, so the
        # scene is left empty until the view is first put in front of
        # somebody. See ensure_drawn.
        self._drawn = False
        # Edits made while the view is hidden, turned off from the Window
        # menu or in a host window that is closed, are not drawn for
        # nobody. The graph is drawn again once, when it is shown. See
        # defer_update.
        self._stale = False
        self._forced = False

        # local attributes
        self.show_grid = user_prefs.get(USER_PREF.SHOW_GRID, True)
        self.show_mini_map = user_prefs.get(USER_PREF.SHOW_MINI_MAP, True)
        # Drawn in drawForeground rather than being a child widget, see
        # nxt_editor.mini_map.MiniMap.
        self.mini_map = MiniMap(self)
        # connection attribute used when drawing connections
        self.potential_connection = None
        # The plug the line being dragged would connect to if dropped now.
        self.snap_plug = None

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
        self.model.backdrops_changed.connect(self.draw_backdrops)
        self.model.layer_visibility_changed.connect(
            self.on_layer_visibility_changed)
        self.model.status_message.connect(self.show_status)
        self.model.wires_changed.connect(self.draw_wires)
        # The node a build is running, so each step redraws only it and the
        # one before it, rather than every node hearing every step.
        self._build_focus_path = ''
        self.model.build_idx_changed.connect(self._build_focus_changed)
        self.model.executing_changed.connect(self._build_focus_changed)
        # A reloaded or muted layer can bring or take away points.
        self.model.comp_layer_changed.connect(self.draw_wires)

        # The view is drawn when it is first shown, not here: see
        # ensure_drawn.

        # HUD
        self.hud_layout = QtWidgets.QGridLayout(self)
        self.hud_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.hud_layout)

        # filepath HUD
        self.filepath_label = HUDItem(text=None)
        self.filepath_label.setAlignment(QtCore.Qt.AlignLeft |
                                         QtCore.Qt.AlignTop)
        self.update_filepath()
        self.hud_layout.addWidget(self.filepath_label, 0, 0)

        # resolved HUD
        self.resolved_label = HUDItem(text='resolved', fade_time=1000)
        self.resolved_label.setAlignment(QtCore.Qt.AlignRight |
                                         QtCore.Qt.AlignTop)
        self.hud_layout.addWidget(self.resolved_label, 0, 3)

        self.fps_label = HUDItem(text='fps', fade_time=0)
        self.fps_label.setAlignment(QtCore.Qt.AlignRight |
                                    QtCore.Qt.AlignBottom)
        if user_prefs.get(USER_PREF.FPS, True):
            self.hud_layout.addWidget(self.fps_label, 1, 3)

        # A word about something the editor did, or chose not to do, by
        # itself. See show_status.
        text_color = theme.color(theme.TEXT)
        self.status_label = HUDItem(text='', fade_time=0,
                                    start_color=text_color,
                                    end_color=text_color)
        self.status_label.setAlignment(QtCore.Qt.AlignLeft |
                                       QtCore.Qt.AlignBottom)
        self.hud_layout.addWidget(self.status_label, 1, 0)
        self._status_timer = QtCore.QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(
            lambda: self.status_label.setText(''))

        # mini map
        # Anything that changes what the graph looks like invalidates the
        # map's cached node blocks. Selection is deliberately left out, the
        # map draws selection live rather than baking it into the cache.
        self.model.comp_layer_changed.connect(self.mini_map.mark_dirty)
        self.model.nodes_changed.connect(self.mini_map.mark_dirty)
        self.model.node_moved.connect(self.mini_map.mark_dirty)
        self.model.collapse_changed.connect(self.mini_map.mark_dirty)
        self.model.layer_color_changed.connect(self.mini_map.mark_dirty)
        self.toggle_mini_map(self.show_mini_map)

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
        self.draw_snap_plug(painter)
        self.mini_map.draw(painter)

    def focusInEvent(self, event):
        super(StageView, self).focusInEvent(event)

    def focusOutEvent(self, event):
        self.zooming = False
        self.zoom_keys_down = False
        self._held_keys = []
        self.zoom_button_down = False
        # The pan key's release goes to whatever has focus now.
        self._pan_key_held = False
        if not self.panning:
            self.update_pan_cursor()
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

    @property
    def is_drawn(self):
        """Whether this view has drawn its graph yet."""
        return self._drawn

    def ensure_drawn(self):
        """Draw the graph if this view has never shown it.

        Called when the view is put in front of somebody. Opening a file
        no longer draws a scene and composites a graph that is sitting in
        a tab nobody has looked at; the tab being selected pays for that,
        once. After that the view keeps its scene and the model keeps its
        comp, so coming back to the tab costs nothing -- anything edited
        in between was drawn as it happened.

        :return: whether this call did the drawing
        :rtype: bool
        """
        if self._drawn:
            return False
        self._drawn = True
        self.redraw()
        self.frame_opened()
        # The comp this graph has just been drawn from is the first one
        # anybody has seen of it, and a comp that failed is worth saying
        # so about here rather than only when the next edit lands.
        self.failure_check()
        return True

    def showEvent(self, event):
        # Selecting a tab shows its view, and so does showing the window
        # for the first time. Either way this is the moment the graph has
        # somebody to be drawn for.
        super(StageView, self).showEvent(event)
        if not self.ensure_drawn() and self._stale:
            self.redraw()
        if self._pending_draw:
            self._pending_timer.start()

    def redraw(self):
        """Draw the whole graph, shown or not."""
        self._stale = False
        self._forced = True
        try:
            self.update_view()
            self.draw_wires()
        finally:
            self._forced = False

    def defer_update(self):
        """Whether to leave an edit undrawn: before the graph is first
        drawn, or while nobody can see the view, when the graph is drawn
        again once it is shown.

        :rtype: bool
        """
        if not self._drawn:
            return True
        if self._forced or self.isVisible():
            return False
        self._stale = True
        return True

    def failure_check(self, *args):
        if not self._drawn:
            return
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
        if self.defer_update():
            # There is nothing drawn to update, and drawing only the dirty
            # part now would leave the rest of the graph missing. The whole
            # graph is drawn when the tab is first selected, or the view
            # shown again.
            return
        start = time.time()
        # The signal layer_color_changed somehow passes its layer to this
        # function. Until we clean up signals this accounts for the wrong
        # type coming through the dirty arg
        if not isinstance(dirty, (tuple, list)):
            dirty = ()
        if not dirty:
            self.forget_drawing_state()
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
                    font-family: %s;
                    background-color: %s;
                    color: #111111;
                }

                QRubberBand {
                    selection-background-color: %s
                }
                ''' % (FONTS.DEFAULT_FAMILY, light_color.name(), layer_color)
        self.setStyleSheet(style)

    def forget_drawing_state(self):
        """Get ready to draw the whole graph again over what is drawn.

        Redrawing the whole graph after an edit used to clear the scene and
        make every node again, which for a graph of thousands of nodes took
        longer than the edit. The nodes are kept now and brought up to date,
        see draw_graph. What only lasts for one drawing is forgotten, as
        clear() does.
        """
        self._attr_concerns = {}
        self._backdrop_drag = None
        self._selected_points = set()
        self._point_drag = None
        self.snap_plug = None
        if self.potential_connection is not None:
            if self.potential_connection.scene():
                self.scene().removeItem(self.potential_connection)
            self.potential_connection = None

    def clear(self):
        """Remove all graphics items and clear all object dictionaries."""
        self._forget_pending()
        self._node_graphics = {}
        self._connection_graphics = ConnectionGraphics()
        self._attr_concerns = {}
        self._backdrop_graphics = {}
        self._backdrop_drag = None
        self._selected_points = set()
        self._point_drag = None
        self.snap_plug = None
        self.scene().clear()

    def toggle_implicit_connections(self, state=None):
        """Show or hide instance lines."""
        if state is None:
            state = not lines.lines_shown(lines.INSTANCE_LINES)
        self.model.implicit_connections = state
        self.show_lines(lines.INSTANCE_LINES, state)

    def toggle_grid(self, state=None):
        if state is None:
            self.show_grid = not self.show_grid
        else:
            self.show_grid = state
        self.resetCachedContent()
        self.viewport().update()

    def toggle_mini_map(self, state=None):
        if state is None:
            self.show_mini_map = not self.show_mini_map
        else:
            self.show_mini_map = state
        self.mini_map.set_visible(self.show_mini_map)
        # Keep the HUD items clear of the map's corner.
        bottom = 0
        if self.show_mini_map:
            bottom = MiniMap.HEIGHT + MiniMap.MARGIN
        self.hud_layout.setContentsMargins(0, 0, 0, bottom)

    def shown_items_rect(self):
        """The scene rect around everything showing: what is hidden with
        its layers is left out."""
        self.finish_drawing()
        return self._drawn_items_rect()

    def _drawn_items_rect(self):
        """shown_items_rect, of the nodes drawn so far."""
        if not self._layers_were_hidden:
            return self.scene().itemsBoundingRect()
        # itemsBoundingRect counts items that are not showing.
        rect = QtCore.QRectF()
        for item in self.scene().items():
            if item.isVisible() and item.parentItem() is None:
                rect = rect.united(item.sceneBoundingRect())
        return rect

    def frame_all(self):
        self.frame_rect(self.shown_items_rect())

    def apply_layer_visibility(self):
        """Show or hide what belongs to layers hidden in the Layer Manager.

        The nodes hidden with them, see StageModel.hidden_nodes, the lines
        to and from those, with their points, and the backdrops only those
        layers draw. Nothing is removed: the items are there, drawn or not.
        A hidden child takes no room under its parent, so the children
        after it close up, and open up again when it is shown.
        """
        hiding = bool(self.model.hidden_layer_paths())
        if not hiding and not self._layers_were_hidden:
            return
        self._layers_were_hidden = hiding
        was_hidden = self._hidden_nodes
        self._hidden_nodes = self.model.hidden_nodes()
        for node_path, graphic in list(self._node_graphics.items()):
            graphic.setVisible(node_path not in self._hidden_nodes)
        changed = was_hidden ^ self._hidden_nodes
        roots = set(nxt_path.get_root_path(path) for path in changed)
        og_do_anims = self.do_animations
        self.do_animations = False
        for root in roots:
            graphic = self.get_node_graphic(root)
            if graphic:
                graphic.arrange_descendants()
        self.do_animations = og_do_anims
        self.update_lines_shown()
        hidden_backdrops = self.model.hidden_backdrop_ids()
        for backdrop_id, graphic in self._backdrop_graphics.items():
            graphic.setVisible(backdrop_id not in hidden_backdrops)
        self.mini_map.mark_dirty()

    def frame_opened(self):
        """Show a graph the way it is first shown: framed around all of it
        with Frame All on Open on, never zoomed in past 100% so a small
        graph is not blown up, and otherwise, or with nothing in it, at the
        origin. Nodes hidden with their layers are left out.

        While a big graph is still being drawn, see _draw_later, it is
        framed on where the nodes waiting start, and framed again once
        they are drawn unless the view was moved in between.
        """
        self._open_frame = None
        if self._pending_draw:
            rect = self._drawn_items_rect()
            for root in self._pending_draw:
                if root == nxt_path.WORLD:
                    continue
                x, y = self.model.get_node_pos(root)
                rect = rect.united(QtCore.QRectF(
                    x, y, NodeGraphicsItem.MAX_WIDTH_GUESS,
                    NodeGraphicsItem.TITLE_HEIGHT_GUESS))
        else:
            rect = self.shown_items_rect()
        if rect.isEmpty() or not user_prefs.get(USER_PREF.FRAME_ON_OPEN,
                                                True):
            self.centerOn(0, 0)
            return
        self.frame_rect(rect)
        if self.scale_factor > 1.0:
            self.resetTransform()
            self.centerOn(rect.center())
        if self._pending_draw:
            self._open_frame = self._frame_state()

    # Camera bookmarks, see nxt_editor.bookmarks ----------------------------

    def view_rect(self):
        """The part of the scene in view."""
        return self.mapToScene(self.viewport().rect()).boundingRect()

    def add_bookmark(self, name=None):
        """Bookmark the part of the graph in view.

        :return: the new bookmark's index
        """
        rect = self.view_rect()
        return self.model.add_bookmark(
            (rect.x(), rect.y(), rect.width(), rect.height()), name)

    def ask_bookmark_name(self, title, name):
        """Ask for a bookmark's name.

        :return: the name, or None when cancelled
        """
        text, ok = QtWidgets.QInputDialog.getText(
            self, title, 'Name:', QtWidgets.QLineEdit.Normal, name)
        if not ok or not text.strip():
            return None
        return text.strip()

    def add_bookmark_named(self):
        """Bookmark the part of the graph in view, asking what to call it."""
        default = bookmarks.unique_name(self.model.get_bookmarks())
        name = self.ask_bookmark_name('Add Bookmark', default)
        if name is None:
            return None
        return self.add_bookmark(name)

    def rename_bookmark_named(self, index):
        records = self.model.get_bookmarks()
        if not (0 <= index < len(records)):
            return
        name = self.ask_bookmark_name('Rename Bookmark',
                                      records[index][bookmarks.NAME])
        if name is not None:
            self.model.rename_bookmark(index, name)

    def go_to_bookmark(self, index):
        """Show the part of the graph a bookmark saved.

        :return: False when there is no such bookmark
        """
        records = self.model.get_bookmarks()
        if not (0 <= index < len(records)):
            return False
        rect = QtCore.QRectF(*records[index][bookmarks.RECT])
        # Scaled to fit the whole of it, with nothing added round the edge
        # as fitInView does, so going back to a view in the same window
        # shows just what was saved.
        viewport = self.viewport().rect()
        scale = min(viewport.width() / rect.width(),
                    viewport.height() / rect.height())
        self.setTransform(QtGui.QTransform.fromScale(scale, scale))
        self.centerOn(rect.center())
        return True

    def on_layer_visibility_changed(self):
        """A layer was hidden or shown. What went out of sight is taken out
        of the selection too, so nothing done to the selection, such as
        copy or delete, reaches what cannot be seen."""
        self.apply_layer_visibility()
        if not self._hidden_nodes:
            return
        hidden = [path for path in self.model.selection
                  if self.node_hidden(path)]
        if hidden:
            self.model.remove_from_selection(hidden)
        self.select_points(ref for ref in self._selected_points
                           if self._point_line_shown(ref))
        self.select_backdrops([backdrop_id for backdrop_id
                               in self.selected_backdrops
                               if self._backdrop_graphics[backdrop_id]
                               .isVisible()])

    def node_hidden(self, node_path):
        """Whether a node is hidden with its layers. See
        StageModel.hidden_nodes."""
        return node_path in self._hidden_nodes

    def _point_line_shown(self, ref):
        for connection in self._connection_graphics:
            if connection.key == ref[0]:
                return connection.isVisible()
        return False

    def show_status(self, text, msecs=4000):
        """Show a short message in the corner of the graph for a while."""
        self.status_label.setText(text)
        self._status_timer.start(msecs)

    def show_hidden_status(self, hidden):
        """Say why the view stayed put: the nodes it was asked to show are
        on layers hidden in the graph."""
        if len(hidden) == 1:
            text = '{} is on a layer hidden in the graph'.format(hidden[0])
        else:
            text = '{} nodes are on layers hidden in the graph'.format(
                len(hidden))
        self.show_status(text)

    def frame_selection(self):
        self.frame_nodes(self.model.selection)

    def frame_nodes(self, node_paths):
        """Frame the given nodes. Nodes hidden with their layers are left
        out, and when that is all of them nothing is framed: the view stays
        put and says why. Their layer is shown from the Layer Manager."""
        node_paths = list(node_paths)
        hidden = [path for path in node_paths if self.node_hidden(path)]
        if hidden:
            node_paths = [path for path in node_paths if path not in hidden]
            if not node_paths:
                self.show_hidden_status(hidden)
                return
        bounding_rect = QtCore.QRectF()
        for path in node_paths:
            graphic = self.get_node_graphic(path)
            if not graphic:
                continue
            bounding_rect = bounding_rect.united(node_scene_rect(graphic))
        if bounding_rect != QtCore.QRectF():
            self.frame_rect(bounding_rect)

    def frame_rect(self, rect):
        rect_left = -1 * self.view_padding_factor
        rect_top = -1 * self.view_padding_factor
        rect_right = self.view_padding_factor
        rect_bottom = self.view_padding_factor
        padded_rect = rect.adjusted(rect_left, rect_top, rect_right, rect_bottom)
        self.make_room(padded_rect)
        self.fitInView(padded_rect, QtCore.Qt.KeepAspectRatio)

    # The scene rect bounds how far the view pans and where it can be
    # centered. It starts here and grows ahead of the view, so the canvas
    # has no edge. It grows by at least half again on a side each time, so
    # only a few times however far the view goes, and only toward where the
    # view has been: the item index divides it up, and a rect far bigger
    # than the graph would slow finding items under the mouse.
    SCENE_START = QtCore.QRectF(-5000, -5000, 10000, 10000)
    # Least room kept round what is shown, in scene units.
    MIN_ROOM = 1000

    def make_room(self, rect):
        """Grow the scene rect, if needed, to hold rect with room round it
        as big as rect itself, so the view can be centered anywhere on it
        and still pan on.

        :return: True when it grew
        """
        room = max(rect.width(), rect.height(), self.MIN_ROOM)
        needed = rect.adjusted(-room, -room, room, room)
        scene_rect = self.scene().sceneRect()
        if scene_rect.contains(needed):
            return False
        pad_x = scene_rect.width() / 2
        pad_y = scene_rect.height() / 2
        grown = QtCore.QRectF(scene_rect)
        if needed.left() < grown.left():
            grown.setLeft(needed.left() - pad_x)
        if needed.right() > grown.right():
            grown.setRight(needed.right() + pad_x)
        if needed.top() < grown.top():
            grown.setTop(needed.top() - pad_y)
        if needed.bottom() > grown.bottom():
            grown.setBottom(needed.bottom() + pad_y)
        self.scene().setSceneRect(grown)
        # The grid kept for the background stopped at the old edge.
        self.resetCachedContent()
        return True

    def centerOn(self, *args):
        """Center on a point, x and y, or an item, anywhere: the scene
        grows first rather than the view stopping at its edge."""
        if len(args) == 2:
            point = QtCore.QPointF(*args)
        elif isinstance(args[0], QtWidgets.QGraphicsItem):
            point = args[0].sceneBoundingRect().center()
        else:
            point = QtCore.QPointF(args[0])
        shown = self.view_rect()
        shown.moveCenter(point)
        self.make_room(shown)
        super(StageView, self).centerOn(*args)

    def resizeEvent(self, event):
        super(StageView, self).resizeEvent(event)
        if self.scene() is not None:
            self.make_room(self.view_rect())

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
        # Drawn nodes the graph no longer has go, and so do ones now under a
        # collapsed node: a whole graph redraw keeps the nodes it can.
        gone = []
        if not dirty:
            current = set(node_paths)
            gone = [path for path in self._node_graphics
                    if path not in current or
                    self.model.get_collapsed_ancestor(path)]
        kept = set(self._node_graphics)
        if not dirty:
            # A whole graph redraw works out again what is left to draw.
            self._forget_pending()
            node_paths = self._draw_later(node_paths)
        og_do_anims = self.do_animations
        self.do_animations = False
        for path in gone:
            self.remove_node_graphic(path)
        self.handle_nodes_changed(node_paths)
        self.do_animations = og_do_anims
        if not dirty:
            self._stack_in_graph_order(node_paths, kept)
            self.draw_backdrops()

    def _stack_in_graph_order(self, node_paths, kept):
        """Put the nodes a whole graph redraw made under the ones after them
        in the graph, where drawing the graph from nothing puts them, so of
        two nodes in the same place the same one is on top either way.

        :param node_paths: the graph's node paths, in drawing order
        :param kept: paths whose nodes were drawn before this redraw
        """
        if len(kept) == len(self._node_graphics) and                 kept.issuperset(self._node_graphics):
            return
        drawn = []
        for path in node_paths:
            graphic = self._node_graphics.get(path)
            if graphic is not None:
                drawn += [(path, graphic)]
        # Only siblings stack against each other: the next kept node under
        # the same parent, or at the top for roots.
        later = {}
        for path, graphic in reversed(drawn):
            parent = graphic.parentItem()
            if path in kept:
                later[parent] = graphic
            elif parent in later:
                graphic.stackBefore(later[parent])

    # Drawing a big graph a part at a time ---------------------------------

    #: A whole graph redraw making more nodes than this draws the ones in
    #: view, up to FIRST_DRAW of them, at once and the rest while the editor
    #: is idle, so a big graph shows, and can be worked on, in seconds.
    #: Anything that asks for a node not drawn yet has it drawn there and
    #: then, see get_node_graphic, and anything that needs every node, like
    #: Select All, finishes the drawing first, see finish_drawing.
    LAZY_DRAW_OVER = 2000
    FIRST_DRAW = 1000
    #: Seconds of drawing each time the editor is idle. Each stretch is
    #: followed by a repaint of what is in view, so not too short.
    IDLE_DRAW_SECONDS = 0.15
    #: Seconds between bringing the mini map up to date while drawing: it
    #: goes over every node drawn, so not after every stretch.
    MINI_MAP_EVERY = 1.0

    def _draw_later(self, node_paths):
        """Of a whole graph redraw's node paths, the ones to draw now. The
        nodes of roots left out wait in _pending_draw.

        :param node_paths: every node path, in drawing order
        :rtype: list
        """
        new_count = 0
        for path in node_paths:
            if path not in self._node_graphics:
                new_count += 1
        if new_count <= self.LAZY_DRAW_OVER:
            return node_paths
        groups = {}
        order = []
        for path in node_paths:
            root = nxt_path.get_root_path(path)
            if root not in groups:
                groups[root] = []
                order += [root]
            groups[root] += [path]
        view = self.view_rect()
        margin = max(view.width(), view.height()) * 0.5
        near = view.adjusted(-margin, -margin, margin, margin)
        center = view.center()

        def place(root):
            pos = self.model.get_node_pos(root) if root != nxt_path.WORLD \
                else (0.0, 0.0)
            point = QtCore.QPointF(pos[0], pos[1])
            offset = point - center
            return (not near.contains(point),
                    offset.x() * offset.x() + offset.y() * offset.y())

        new_roots = [r for r in order
                     if any(p not in self._node_graphics for p in groups[r])]
        by_place = sorted(new_roots, key=place)
        now = set(r for r in order if r not in set(new_roots))
        budget = self.FIRST_DRAW
        for root in by_place:
            if budget <= 0:
                break
            now.add(root)
            budget -= len(groups[root])
        for root in by_place:
            if root in now:
                continue
            self._pending_draw[root] = groups[root]
            for path in groups[root]:
                self._pending_root_of[path] = root
        if self._pending_draw:
            self._pending_timer.start()
        return [p for p in node_paths if nxt_path.get_root_path(p) in now]

    def _forget_pending(self):
        self._pending_draw = {}
        self._pending_root_of = {}
        if getattr(self, '_pending_timer', None) is not None:
            self._pending_timer.stop()

    @property
    def drawing(self):
        """Whether nodes of the graph are still waiting to be drawn."""
        return bool(self._pending_draw)

    def _draw_pending_roots(self, roots):
        paths = []
        for root in roots:
            for path in self._pending_draw.pop(root, ()):
                self._pending_root_of.pop(path, None)
                paths += [path]
        if not paths:
            return
        og_do_anims = self.do_animations
        self.do_animations = False
        try:
            self.handle_nodes_changed(paths)
        finally:
            self.do_animations = og_do_anims
        now = time.time()
        if not self._pending_draw or                 now - self._mini_map_marked > self.MINI_MAP_EVERY:
            self._mini_map_marked = now
            self.mini_map.mark_dirty()
        if not self._pending_draw:
            self._finished_drawing()

    def _draw_some_pending(self):
        """Draw waiting nodes for a moment, and come back for more."""
        if not self._pending_draw:
            return
        if not self.isVisible():
            # Picked up again when the view is shown, see showEvent.
            return
        start = time.time()
        # What came in between, mostly repainting what is in view, which
        # with a whole big graph in view takes long: draw for twice that,
        # so repainting stays a third of the time at most.
        between = start - self._pending_slice_end             if self._pending_slice_end else 0.0
        end = start + max(self.IDLE_DRAW_SECONDS, min(between * 2, 1.0))
        while self._pending_draw and time.time() < end:
            root = next(iter(self._pending_draw))
            self._draw_pending_roots([root])
        self._pending_slice_end = time.time()
        if self._pending_draw:
            self._pending_timer.start()
        else:
            self._pending_slice_end = 0.0

    def finish_drawing(self):
        """Draw every node still waiting, for what needs all of them."""
        if self._pending_draw:
            self._draw_pending_roots(list(self._pending_draw))

    def _finished_drawing(self):
        # Framed when it was opened on where the nodes waiting to be drawn
        # start; now their sizes are known, frame it again unless it was
        # moved since.
        opened, self._open_frame = self._open_frame, None
        if opened and opened == self._frame_state():
            self.frame_opened()

    def _frame_state(self):
        center = self.mapToScene(self.viewport().rect().center())
        return (self.transform(), round(center.x(), 3),
                round(center.y(), 3))

    def draw_node(self, node_path):
        graphic = self._node_graphics.get(node_path)
        if not graphic:
            graphic = NodeGraphicsItem(node_path=node_path,
                                       model=self.model,
                                       view=self)
            self._node_graphics[node_path] = graphic
        if graphic.scene() != self.scene():
            self.scene().addItem(graphic)
            graphic.setZValue(self.NODE_DEPTH)
            # Selected while a node above it was collapsed.
            if self.model.is_selected(node_path):
                graphic.setSelected(True)
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
        self._draw_exec_connections(node_path)
        # Every property, shown or not: a line shows while either of its
        # ends is, see line_shown.
        self._draw_attr_connections(
            node_path, self.model.get_node_attr_names(node_path,
                                                      self.model.comp_layer))
        self._draw_code_connections(node_path)
        self._draw_inst_connections(node_path)

    def _draw_exec_connections(self, node_path):
        exec_attr = nxt_node.INTERNAL_ATTRS.EXECUTE_IN
        self._sync_lines_into(node_path, exec_attr,
                              self._exec_line_sources(node_path))

    def _exec_line_sources(self, node_path):
        exec_attr = nxt_node.INTERNAL_ATTRS.EXECUTE_IN
        src_path = self.model.get_node_exec_in(node_path=node_path,
                                               layer=self.model.comp_layer)
        if not src_path:
            return []
        exec_root_path = nxt_path.get_root_path(src_path)
        if src_path != exec_root_path:
            # An exec path that is not a root?
            return []
        self.register_attr_concern(src_path, None,
                                   node_path, exec_attr)
        if not self._node_graphics.get(src_path):
            return []
        return [src_path]

    def _draw_attr_connections(self, node_path, attr_names):
        # draw attr connections
        my_root_path = nxt_path.get_root_path(node_path)
        comp_layer = self.model.comp_layer
        # Target node item attr names respects 0,1,2,3 hiding of attrs.
        for attr_name in attr_names:
            # Inherited properties get lines too, dotted, see
            # AttrConnectionGraphic.inherited.
            sources = self.model.get_node_attr_external_sources(node_path,
                                                                attr_name,
                                                                comp_layer)
            wanted = []
            for src in sources:
                split = nxt_path.path_attr_partition(src)
                src_node_path, src_attr_name = split
                src_root_path = nxt_path.get_root_path(src_node_path)
                if src_root_path == my_root_path:
                    # Do not draw attr connections between shared roots
                    continue
                self.register_attr_concern(src_node_path, src_attr_name,
                                           node_path, attr_name)
                if not self._node_graphics.get(src_node_path):
                    continue
                wanted += [src]
            self._sync_lines_into(node_path, attr_name, wanted)

    def _draw_inst_connections(self, node_path):
        inst_attr = nxt_node.INTERNAL_ATTRS.INSTANCE_PATH
        self._sync_lines_into(node_path, inst_attr,
                              self._inst_line_sources(node_path))

    def _inst_line_sources(self, node_path):
        inst_attr = nxt_node.INTERNAL_ATTRS.INSTANCE_PATH
        comp = self.model.comp_layer
        if self.model.get_node_is_proxy(node_path):
            return []
        inst_path = self.model.get_node_instance_path(node_path=node_path,
                                                      layer=comp)
        if not inst_path:
            return []
        self.register_attr_concern(inst_path, None,
                                   node_path, inst_attr)
        if not self._node_graphics.get(inst_path):
            return []
        return [inst_path]

    def _draw_code_connections(self, node_path):
        code_attr = nxt_node.INTERNAL_ATTRS.COMPUTE
        comp = self.model.comp_layer
        my_root_path = nxt_path.get_root_path(node_path)
        # draw compute connections
        sources = self.model.get_node_code_external_sources(node_path, comp)
        wanted = []
        for src_attr_path in sources or ():
            split = nxt_path.path_attr_partition(src_attr_path)
            src_node_path, src_attr_name = split
            self.register_attr_concern(src_node_path, None,
                                       node_path, code_attr)
            if not self._node_graphics.get(src_node_path):
                continue
            src_root_path = nxt_path.get_root_path(src_node_path)
            if src_root_path == my_root_path:
                continue
            wanted += [src_attr_path]
        self._sync_lines_into(node_path, code_attr, wanted)

    def _sync_lines_into(self, node_path, attr_name, sources):
        """Draw the lines into one attr from sources, in that order.

        A line already drawn from a source is kept and brought up to date
        rather than made again, so redrawing a graph after an edit only
        makes and removes the lines that changed.

        :param node_path: the node the lines go into
        :param attr_name: the attr on it they go into
        :param sources: source node or attr paths, one line each
        """
        target = nxt_path.make_attr_path(node_path, attr_name)
        drawn = self._connection_graphics.at_attr(node_path, attr_name,
                                                  [CONNECTION_SIDES.IN])
        keep = {}
        for source in sources:
            for graphic in drawn:
                if graphic.src_path == source and graphic not in keep:
                    keep[graphic] = source
                    break
        for graphic in drawn:
            if graphic not in keep:
                self.scene().removeItem(graphic)
                self._connection_graphics.remove(graphic)
        kept = {}
        for graphic, source in keep.items():
            kept.setdefault(source, []).append(graphic)
        for source in sources:
            graphic = kept[source].pop(0) if kept.get(source) else None
            if graphic is not None:
                # Its type, or whether it is inherited, may have changed.
                graphic.calculate_draw_details()
                graphic.setVisible(self.line_shown(graphic))
                continue
            self.add_connection_graphic(
                AttrConnectionGraphic(self.model, self, source_path=source,
                                      target_path=target))

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
        to_remove = self._connection_graphics.at_attr(node_path, attr_name,
                                                      sides)
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
        return self._connection_graphics.at_node(node_path, sides)

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
        # Concerns in the order registered, as dict keys so a repeat is
        # found without walking them all.
        self._attr_concerns[src_node_path].setdefault(src_attr_name, {})
        concern = (tgt_node_path, tgt_attr_name)
        self._attr_concerns[src_node_path][src_attr_name][concern] = None

    def add_connection_graphic(self, graphic):
        """Add given connection graphic to the scene and track.

        :param graphic: Connection graphic to add
        :type graphic: AttrConnectionGraphic
        """
        self.scene().addItem(graphic)
        graphic.setZValue(self.CONNECTION_DEPTH)
        self._connection_graphics.add(graphic)
        graphic.drawn = True
        graphic.setVisible(self.line_shown(graphic))
        points = self._line_points.get(graphic.key)
        if points:
            graphic.set_points(points)
            self._show_point_selection()

    # Line style and points, see nxt_editor.wires ------------------------

    def draw_wires(self, *args):
        """Bring the lines drawn in line with the model's style and
        points."""
        self.connection_style = self.model.get_connection_style()
        self._line_points = self.model.get_line_points()
        if self.defer_update():
            return
        for graphic in self._connection_graphics:
            points = self._line_points.get(graphic.key, [])
            drawn = [[p.x(), p.y()] for p in graphic.points]
            if drawn != points:
                graphic.set_points(points)
            else:
                graphic.rebuild_line()
        if self.potential_connection:
            self.potential_connection.rebuild_line()
        self._show_point_selection()
        self.mini_map.mark_dirty()

    def _point_ref(self, graphic):
        connection = graphic.connection
        return connection.key, connection.point_graphics.index(graphic)

    def _show_point_selection(self):
        """Mark the selected points, forgetting any that are gone."""
        shown = set()
        for connection in self._connection_graphics:
            for index, graphic in enumerate(connection.point_graphics):
                ref = (connection.key, index)
                graphic.set_selected(ref in self._selected_points)
                shown.add(ref)
        self._selected_points &= shown

    @property
    def selected_points(self):
        return sorted(self._selected_points)

    def select_points(self, refs):
        self._selected_points = set(refs)
        self._show_point_selection()

    def points_in(self, scene_rect):
        """The points on lines inside a scene rectangle.

        Asked of each line rather than of the scene: a point keeps its
        size on screen as the view zooms, and the scene does not find
        items like that by area reliably. Points on hidden lines are left
        out.
        """
        refs = set()
        for connection in self._connection_graphics:
            if not connection.isVisible():
                continue
            for index, graphic in enumerate(connection.point_graphics):
                if scene_rect.contains(graphic.scenePos()):
                    refs.add((connection.key, index))
        return refs

    def box_select_points(self, refs, modifiers):
        """Select the points a box was dragged around, with the same
        modifiers as nodes: Ctrl+Shift adds them, Shift toggles them, Ctrl
        takes them out, and none makes them the selection."""
        refs = set(refs)
        if modifiers == self.SEL_ADD_MODIFIERS:
            refs = self._selected_points | refs
        elif modifiers == self.SEL_TOGGLE_MODIFIERS:
            refs = self._selected_points ^ refs
        elif modifiers == self.SEL_RMV_MODIFIERS:
            refs = self._selected_points - refs
        self.select_points(refs)

    def point_at(self, view_pos):
        for item in self.items(view_pos):
            if isinstance(item, WirePointGraphic):
                return item
        return None

    def line_shown(self, line):
        """Whether a line is shown. Exec lines always are. Others when
        lines are, its kind is, and for a property line, the property is
        showing on at least one of its nodes, so with every node's
        properties hidden there are none. A line to or from a node hidden
        with its layers never is, exec lines included."""
        if self._hidden_nodes:
            for path in (line.src_node_path, line.tgt_node_path):
                if path and self.node_hidden(path):
                    return False
        kind = line.kind
        if kind == lines.EXEC_LINES:
            return True
        if not (lines.lines_shown() and lines.lines_shown(kind)):
            return False
        if kind != lines.PROPERTY_LINES:
            return True
        for path, attr in ((line.src_node_path, line.src_attr_name),
                           (line.tgt_node_path, line.tgt_attr_name)):
            graphic = self.get_node_graphic(path)
            if graphic and attr in graphic.user_attr_names:
                return True
        return False

    def show_lines(self, kind, shown):
        """Show or hide a kind of line, or with kind None all lines,
        remembered for every graph."""
        lines.show_lines(kind, shown)
        self.update_lines_shown()

    def update_lines_shown(self):
        for line in self._connection_graphics:
            line.setVisible(self.line_shown(line))

    def go_to_node(self, node_path):
        """Select a node, everywhere it is shown, and bring it into view
        here without zooming. A node hidden with its layers is selected
        but the view stays put and says why, as framing does."""
        self.model.set_selection([node_path])
        if self.node_hidden(node_path):
            self.show_hidden_status([node_path])
            return
        graphic = self.get_node_graphic(node_path)
        if graphic:
            self.centerOn(node_scene_rect(graphic).center())

    def connection_at(self, scene_pos):
        """The line a click at scene_pos lands on, allowing a few pixels on
        screen whatever the zoom, and the nearest where lines are close."""
        room = lines.HIT_PIXELS / (self.scale_factor or 1.0)
        area = QtCore.QRectF(scene_pos.x() - room, scene_pos.y() - room,
                             room * 2, room * 2)
        nearest, best = None, None
        # By their boxes, as a thin line's own outline can miss the area.
        for item in self.scene().items(
                area, QtCore.Qt.IntersectsItemBoundingRect):
            if not (isinstance(item, AttrConnectionGraphic) and
                    item.isVisible() and
                    item is not self.potential_connection and
                    item.drawn):
                continue
            gap = item.distance(scene_pos) - item.thickness / 2.0
            if gap <= room and (best is None or gap < best):
                nearest, best = item, gap
        return nearest

    def add_line_point(self, connection, scene_pos):
        """Add a point to a line where it was double clicked."""
        points = [[p.x(), p.y()] for p in connection.points]
        pos = (scene_pos.x(), scene_pos.y())
        if self.alignment_actions.snap_action.isChecked():
            pos = tuple(self.model.snap_pos_to_grid(pos))
        index = wires.insert_index(
            (connection.src_pos.x(), connection.src_pos.y()), points,
            (connection.tgt_pos.x(), connection.tgt_pos.y()), pos)
        points.insert(index, [pos[0], pos[1]])
        self.model.set_line_points(connection.key, points,
                                   text='Add connection point')
        self.select_points([(connection.key, index)])

    def remove_line_point(self, graphic):
        connection = graphic.connection
        index = connection.point_graphics.index(graphic)
        points = [[p.x(), p.y()] for p in connection.points]
        points.pop(index)
        self.select_points([])
        self.model.set_line_points(connection.key, points,
                                   text='Remove connection point')

    def delete_selected_points(self):
        """Remove the selected points, and only them.

        :return: True when there were some to remove
        """
        if not self._selected_points:
            return False
        by_line = {}
        for key, index in self._selected_points:
            by_line.setdefault(key, set()).add(index)
        self.select_points([])
        stack = self.model.undo_stack
        text = 'Remove connection points'
        stack.beginMacro(text)
        for key, indexes in by_line.items():
            points = self.model.get_line_points(key)
            kept = [p for i, p in enumerate(points) if i not in indexes]
            self.model.set_line_points(key, kept, text=text)
        stack.endMacro()
        return True

    def point_press(self, event):
        """Select a point under a left click and start dragging it. Shift
        click adds it to or takes it out of the selected points.

        :return: True when the click was on a point
        """
        graphic = self.point_at(event.pos())
        if graphic is None:
            if event.modifiers() == QtCore.Qt.NoModifier:
                self.select_points([])
            return False
        ref = self._point_ref(graphic)
        if event.modifiers() == self.SEL_TOGGLE_MODIFIERS:
            self.select_points(self._selected_points ^ {ref})
            return True
        if ref not in self._selected_points:
            self.select_points([ref])
        self.select_backdrops([])
        self.model.clear_selection()
        # Every selected point moves with the one dragged, as nodes do.
        moving = [g for c in self._connection_graphics
                  for g in c.point_graphics
                  if self._point_ref(g) in self._selected_points]
        if graphic not in moving:
            moving.append(graphic)
        self._point_drag = {'graphic': graphic,
                            'start': self.mapToScene(event.pos()),
                            'pos': QtCore.QPointF(graphic.pos()),
                            'moving': [(g, QtCore.QPointF(g.pos()))
                                       for g in moving],
                            'moved': False}
        return True

    def point_drag_move(self, event):
        drag = self._point_drag
        new_pos = drag['pos'] + (self.mapToScene(event.pos()) - drag['start'])
        shift = event.modifiers() & QtCore.Qt.ShiftModifier
        if shift or self.alignment_actions.snap_action.isChecked():
            new_pos = QtCore.QPointF(*self.model.snap_pos_to_grid(
                (new_pos.x(), new_pos.y())))
        # The others keep their places around the one dragged.
        offset = new_pos - drag['pos']
        connections = []
        for graphic, start in drag['moving']:
            graphic.setPos(start + offset)
            if graphic.connection not in connections:
                connections.append(graphic.connection)
        for connection in connections:
            connection.rebuild_line()
        drag['moved'] = True
        self.mini_map.mark_dirty()

    def point_release(self):
        """Save where the points were dragged to, as one undo."""
        drag = self._point_drag
        self._point_drag = None
        if not drag['moved']:
            return
        connections = []
        for graphic, _ in drag['moving']:
            if graphic.connection not in connections:
                connections.append(graphic.connection)
        multiple = len(drag['moving']) > 1
        text = 'Move connection points' if multiple else \
            'Move connection point'
        # Read them all before saving any, as saving one redraws its line.
        moved = [(c.key, [[p.x(), p.y()] for p in c.points])
                 for c in connections]
        stack = self.model.undo_stack
        stack.beginMacro(text)
        for key, points in moved:
            self.model.set_line_points(key, points, text=text)
        stack.endMacro()

    # Screen pixels between minor grid lines below which they are left out.
    MIN_GRID_SPACING = 4

    def drawBackground(self, painter, rect):
        super(StageView, self).drawBackground(painter, rect)

        # Only the exposed area, clamped to the scene. Redrawing the whole
        # scene rect meant every partial repaint, however small, drew the
        # entire grid.
        rect = rect.intersected(self.sceneRect())
        if rect.isEmpty():
            return
        painter.fillRect(rect, QtGui.QBrush(colors.GRAPH_BG_COLOR))

        left = int(rect.left()) - (int(rect.left()) % self.draw_grid_size)
        top = int(rect.top()) - (int(rect.top()) % self.draw_grid_size)

        if self.show_grid:
            # Cosmetic pens stay one pixel wide at any zoom. Every tenth
            # line is a little brighter, to judge distance by. Each kind is
            # drawn in one call: a call per line was thousands of them on
            # every repaint, zoomed out.
            step = self.draw_grid_size
            every = step * 10
            # Minor lines closer than this on screen are only a wash.
            show_minor = step * self.scale_factor >= self.MIN_GRID_SPACING
            minor_lines = []
            major_lines = []
            for x in range(left, int(rect.right()), step):
                line = QtCore.QLineF(x, rect.top(), x, rect.bottom())
                if x % every == 0:
                    major_lines.append(line)
                elif show_minor:
                    minor_lines.append(line)
            for y in range(top, int(rect.bottom()), step):
                line = QtCore.QLineF(rect.left(), y, rect.right(), y)
                if y % every == 0:
                    major_lines.append(line)
                elif show_minor:
                    minor_lines.append(line)
            # Level, one pixel lines need no smoothing, and smoothing
            # them was most of what drawing the grid cost.
            painter.save()
            painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
            if minor_lines:
                painter.setPen(QtGui.QPen(theme.color(theme.GRID_MINOR), 0))
                painter.drawLines(minor_lines)
            if major_lines:
                painter.setPen(QtGui.QPen(theme.color(theme.GRID_MAJOR), 0))
                painter.drawLines(major_lines)
            painter.restore()

    def add_node(self):
        sel_node_paths = self.model.get_selected_nodes()
        if sel_node_paths:
            parent_item = self.get_node_graphic(sel_node_paths[0])
            if parent_item:
                parent_path = parent_item.node_path
                if parent_path:
                    self.new_node(parent_path=parent_path)

        else:
            pos = self.placement_pos()
            self.new_node(pos=[pos.x(), pos.y()])

    def placement_pos(self):
        """Where a node added or pasted from a menu or hotkey goes: at the
        mouse, or in the middle of the graph when the mouse is not over
        it, such as for a node added from the Outliner."""
        mouse_pos = self.mapFromGlobal(QtGui.QCursor.pos())
        if not self.viewport().rect().contains(mouse_pos):
            mouse_pos = self.viewport().rect().center()
        return self.mapToScene(mouse_pos)

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
            mouse_pos = self.placement_pos()
            pos = [mouse_pos.x(), mouse_pos.y()]
        if not parent_path:
            sel_node_paths = self.model.get_selected_nodes()
            if sel_node_paths:
                parent_path = sel_node_paths[-1]
                pos = None
        self.model.paste_nodes(pos=pos, parent_path=parent_path,
                               layer=self.model.target_layer)


    # Backdrops ------------------------------------------------------------

    def draw_backdrops(self):
        """Bring the backdrops drawn in line with the model's."""
        if self.defer_update():
            return
        records = self.model.get_backdrops()
        for backdrop_id in list(self._backdrop_graphics):
            if backdrop_id not in records:
                graphic = self._backdrop_graphics.pop(backdrop_id)
                if graphic.scene():
                    self.scene().removeItem(graphic)
        for backdrop_id, record in records.items():
            graphic = self._backdrop_graphics.get(backdrop_id)
            if graphic is None:
                graphic = BackdropGraphicsItem(backdrop_id, record)
                self._backdrop_graphics[backdrop_id] = graphic
                self.scene().addItem(graphic)
            else:
                graphic.set_record(record)
        # Larger ones behind smaller ones, so a backdrop inside another can
        # still be grabbed.
        by_area = sorted(self._backdrop_graphics.values(),
                         key=lambda g: -(g.width * g.height))
        for index, graphic in enumerate(by_area):
            graphic.setZValue(self.BACKDROP_DEPTH + (index * .01))
        self.apply_layer_visibility()
        self.mini_map.mark_dirty()

    def get_backdrop_graphic(self, backdrop_id):
        return self._backdrop_graphics.get(backdrop_id)

    @property
    def selected_backdrops(self):
        return [backdrop_id for backdrop_id, graphic
                in self._backdrop_graphics.items() if graphic.selected]

    def select_backdrops(self, backdrop_ids):
        for backdrop_id, graphic in self._backdrop_graphics.items():
            selected = backdrop_id in backdrop_ids
            if graphic.selected != selected:
                graphic.selected = selected
                graphic.update()

    def backdrop_contents(self, graphic):
        """What moves with a backdrop: every top level node whose middle is
        inside it, and every backdrop wholly inside it.

        :return: ([NodeGraphicsItem], [BackdropGraphicsItem])
        """
        area = graphic.scene_rect()
        nodes = []
        self.finish_drawing()
        for path, node_graphic in self._node_graphics.items():
            if nxt_path.get_root_path(path) != path:
                # Children are stacked under their root and go with it.
                continue
            if node_graphic.scene() is None:
                continue
            if area.contains(node_scene_rect(node_graphic).center()):
                nodes += [node_graphic]
        inner = []
        for other in self._backdrop_graphics.values():
            if other is not graphic and area.contains(other.scene_rect()):
                inner += [other]
        return nodes, inner

    def _position_layer(self):
        """The layer node positions are written to, see mouseReleaseEvent."""
        if self.model.target_layer.layer_idx() == 0:
            return self.model.target_layer
        return self.model.top_layer

    def _nodes_rect(self, node_graphics):
        """Scene rectangle around nodes, the children stacked under them
        included, but not those hidden with their layers."""
        rect = QtCore.QRectF()
        for graphic in node_graphics:
            rect = rect.united(node_scene_rect(graphic))
            for child in graphic.childItems():
                if isinstance(child, NodeGraphicsItem):
                    if not self.node_hidden(child.node_path):
                        rect = rect.united(self._nodes_rect([child]))
                elif child.isVisible():
                    # Plugs and the like, which reach past the node's edge.
                    rect = rect.united(child.sceneBoundingRect())
        return rect

    def add_backdrop(self):
        """Add a backdrop around the selected nodes, or an empty one under
        the mouse when nothing is selected."""
        roots = []
        for path in self.model.get_selected_nodes():
            graphic = self.get_node_graphic(nxt_path.get_root_path(path))
            if graphic and graphic not in roots:
                roots += [graphic]
        nodes_rect = self._nodes_rect(roots)
        if not nodes_rect.isEmpty():
            pad = self.BACKDROP_PADDING
            # Measure the header the new backdrop will have, so the nodes
            # start below it.
            sizer = BackdropGraphicsItem('', backdrops.make((0, 0)))
            header = sizer.header_rect().height()
            pos = (nodes_rect.left() - pad, nodes_rect.top() - pad - header)
            size = (nodes_rect.width() + (pad * 2),
                    nodes_rect.height() + (pad * 2) + header)
        else:
            view_pos = self.mapFromGlobal(QtGui.QCursor.pos())
            if not self.viewport().rect().contains(view_pos):
                view_pos = self.viewport().rect().center()
            center = self.mapToScene(view_pos)
            size = backdrops.DEFAULT_SIZE
            pos = (center.x() - (size[0] * .5), center.y() - 30)
        record = backdrops.make(pos, size)
        stack = self.model.undo_stack
        stack.beginMacro('Add backdrop')
        backdrop_id = self.model.add_backdrop(record)
        self.model.clear_selection()
        stack.endMacro()
        self.select_backdrops([backdrop_id])
        return backdrop_id

    def delete_selected_backdrops(self):
        """Delete the selected backdrops, and only them.

        :return: True when there were some to delete
        """
        selected = self.selected_backdrops
        if not selected:
            return False
        self.model.remove_backdrops(selected)
        return True

    def edit_backdrop(self, backdrop_id):
        record = self.model.get_backdrop(backdrop_id)
        if record is None:
            return
        dialog = BackdropEditDialog(record, parent=self)
        if not dialog.exec_():
            return
        values = dialog.values()
        if all(record.get(k) == v for k, v in values.items()):
            return
        self.model.edit_backdrop(backdrop_id, text='Edit backdrop "{}"'.format(
            values[backdrops.TITLE]), **values)

    def pick_backdrop_color(self, backdrop_id):
        record = self.model.get_backdrop(backdrop_id)
        if record is None:
            return
        # The same colors as layers, ones white text reads on.
        color = LayerColorDialog.get_color(record[backdrops.COLOR], self,
                                           title='Backdrop Color')
        if color:
            self.model.edit_backdrop(backdrop_id, text='Color backdrop',
                                     color=color)

    def fit_backdrop(self, backdrop_id):
        """Size a backdrop to just hold the nodes inside it."""
        graphic = self.get_backdrop_graphic(backdrop_id)
        if not graphic:
            return
        nodes, inner = self.backdrop_contents(graphic)
        rect = self._nodes_rect(nodes)
        for other in inner:
            rect = rect.united(other.scene_rect())
        if rect.isEmpty():
            return
        pad = self.BACKDROP_PADDING
        header = graphic.header_rect().height()
        self.model.edit_backdrop(
            backdrop_id, text='Fit backdrop',
            pos=[rect.left() - pad, rect.top() - pad - header],
            size=[rect.width() + (pad * 2),
                  rect.height() + (pad * 2) + header])

    def select_backdrop_nodes(self, backdrop_id):
        graphic = self.get_backdrop_graphic(backdrop_id)
        if not graphic:
            return
        nodes, _ = self.backdrop_contents(graphic)
        self.select_backdrops([])
        self.model.set_selection([g.node_path for g in nodes])

    def backdrop_menu(self, graphic):
        backdrop_id = graphic.backdrop_id
        menu = QtWidgets.QMenu(self)
        edit = menu.addAction('Edit Backdrop...')
        edit.triggered.connect(partial(self.edit_backdrop, backdrop_id))
        color_menu = menu.addMenu('Color')
        for name, hex_color in backdrops.PRESET_COLORS:
            swatch = QtGui.QPixmap(14, 14)
            swatch.fill(QtGui.QColor(hex_color))
            action = color_menu.addAction(QtGui.QIcon(swatch), name)
            action.triggered.connect(partial(
                self.model.edit_backdrop, backdrop_id,
                text='Color backdrop', color=hex_color))
        color_menu.addSeparator()
        custom = color_menu.addAction('Custom...')
        custom.triggered.connect(partial(self.pick_backdrop_color,
                                         backdrop_id))
        menu.addSeparator()
        select = menu.addAction('Select Nodes Inside')
        select.triggered.connect(partial(self.select_backdrop_nodes,
                                         backdrop_id))
        fit = menu.addAction('Fit to Nodes Inside')
        fit.triggered.connect(partial(self.fit_backdrop, backdrop_id))
        menu.addSeparator()
        delete = menu.addAction('Delete Backdrop')
        delete.triggered.connect(partial(self.model.remove_backdrops,
                                         [backdrop_id]))
        menu.exec_(self.mapToGlobal(self._initial_click_pos))

    def backdrop_press(self, event):
        """Start moving or resizing the backdrop under a left click.

        Dragging the header moves the backdrop and everything inside it,
        holding Ctrl moves the backdrop alone. Dragging the bottom right
        corner resizes it. Shift click adds it to or takes it out of the
        selected backdrops.

        :return: True when the click was on a backdrop
        """
        item = self.itemAt(event.pos())
        if not isinstance(item, BackdropGraphicsItem):
            if event.modifiers() == QtCore.Qt.NoModifier:
                self.select_backdrops([])
            return False
        scene_pos = self.mapToScene(event.pos())
        part = item.part_at(scene_pos)
        if part is None:
            return False
        mods = event.modifiers()
        if mods == self.SEL_TOGGLE_MODIFIERS:
            selected = self.selected_backdrops
            if item.backdrop_id in selected:
                selected.remove(item.backdrop_id)
            else:
                selected += [item.backdrop_id]
            self.select_backdrops(selected)
            return True
        self.select_backdrops([item.backdrop_id])
        self.model.clear_selection()
        nodes, inner = [], []
        if part == 'header' and not mods & QtCore.Qt.ControlModifier:
            nodes, inner = self.backdrop_contents(item)
        self._backdrop_drag = {
            'graphic': item, 'part': part, 'start': scene_pos,
            'pos': QtCore.QPointF(item.pos()),
            'size': (item.width, item.height), 'moved': False,
            'nodes': [(g, QtCore.QPointF(g.pos())) for g in nodes
                      if not g.locked],
            'inner': [(g, QtCore.QPointF(g.pos())) for g in inner]}
        return True

    def backdrop_drag_move(self, event):
        drag = self._backdrop_drag
        graphic = drag['graphic']
        delta = self.mapToScene(event.pos()) - drag['start']
        shift = event.modifiers() & QtCore.Qt.ShiftModifier
        snap = shift or self.alignment_actions.snap_action.isChecked()
        grid = float(self.draw_grid_size)
        if drag['part'] == 'resize':
            width = drag['size'][0] + delta.x()
            height = drag['size'][1] + delta.y()
            if snap:
                width = round(width / grid) * grid
                height = round(height / grid) * grid
            graphic.set_size(width, height)
        else:
            new_pos = drag['pos'] + delta
            if snap:
                new_pos = QtCore.QPointF(*self.model.snap_pos_to_grid(
                    (new_pos.x(), new_pos.y())))
                delta = new_pos - drag['pos']
            graphic.setPos(new_pos)
            for moved, start in drag['nodes'] + drag['inner']:
                moved.setPos(start + delta)
        drag['moved'] = True
        self.mini_map.mark_dirty()

    def backdrop_release(self):
        """Save where a backdrop was moved or resized to, as one undo."""
        drag = self._backdrop_drag
        self._backdrop_drag = None
        if not drag['moved']:
            return
        graphic = drag['graphic']
        changes = {}
        for moved in [graphic] + [g for g, _ in drag['inner']]:
            record = copy.deepcopy(moved.record)
            record[backdrops.POS] = [moved.pos().x(), moved.pos().y()]
            changes[moved.backdrop_id] = record
        node_positions = {}
        for node_graphic, _ in drag['nodes']:
            node_positions[node_graphic.node_path] = [node_graphic.pos().x(),
                                                      node_graphic.pos().y()]
        if drag['part'] == 'resize':
            text = 'Resize backdrop'
        else:
            text = 'Move backdrop'
        stack = self.model.undo_stack
        stack.beginMacro(text)
        if node_positions:
            self.model.set_nodes_pos(node_positions,
                                     layer=self._position_layer())
        self.model.set_backdrops(changes, text=text)
        stack.endMacro()

    def select_all(self):
        """Select every node in sight. Nodes hidden with their layers are
        not."""
        self.finish_drawing()
        node_paths = [path for path in self._node_graphics
                      if not self.node_hidden(path)]
        self.model.set_selection(paths=node_paths)

    # Aligning, see nxt_editor.align -----------------------------------------

    def layout_boxes(self):
        """The selected top level nodes and points, as boxes to line up.

        :return: {('node', path) or ('point', (key, index)):
                  (left, top, right, bottom)}
        """
        boxes = {}
        for path in self.model.get_selected_nodes():
            if nxt_path.get_root_path(path) != path:
                # Only top level nodes have a place of their own.
                continue
            graphic = self.get_node_graphic(path)
            if graphic is None:
                continue
            rect = node_scene_rect(graphic)
            boxes[('node', path)] = (rect.left(), rect.top(), rect.right(),
                                     rect.bottom())
        points = {}
        for connection in self._connection_graphics:
            for index, graphic in enumerate(connection.point_graphics):
                points[(connection.key, index)] = graphic.pos()
        for ref in self._selected_points:
            pos = points.get(ref)
            if pos is not None:
                boxes[('point', ref)] = (pos.x(), pos.y(), pos.x(), pos.y())
        return boxes

    def align(self, edge):
        """Line the selected nodes and points up on an edge, as one undo.

        :param edge: one of nxt_editor.align.EDGES
        """
        names = {align.LEFT: 'left', align.HCENTER: 'center',
                 align.RIGHT: 'right', align.TOP: 'top',
                 align.VCENTER: 'middle', align.BOTTOM: 'bottom'}
        offsets = align.align_offsets(self.layout_boxes(), edge)
        self.move_by(offsets, 'Align {}'.format(names[edge]))

    def distribute(self, axis):
        """Space the selected nodes and points out evenly, as one undo.

        :param axis: nxt_editor.align.HORIZONTAL or VERTICAL
        """
        offsets = align.distribute_offsets(self.layout_boxes(), axis)
        self.move_by(offsets, 'Distribute {}'.format(axis))

    def move_by(self, offsets, text):
        """Move nodes and points by the given amounts, as one undo.

        :param offsets: {box key from layout_boxes: (dx, dy)}
        :param text: the undo's name
        """
        if not offsets:
            return
        node_positions = {}
        by_line = {}
        for (kind, ref), (dx, dy) in offsets.items():
            if kind == 'node':
                graphic = self.get_node_graphic(ref)
                node_positions[ref] = [graphic.pos().x() + dx,
                                       graphic.pos().y() + dy]
            else:
                by_line.setdefault(ref[0], {})[ref[1]] = (dx, dy)
        stack = self.model.undo_stack
        stack.beginMacro(text)
        if node_positions:
            self.model.set_nodes_pos(node_positions,
                                     layer=self._position_layer())
        for key, moves in by_line.items():
            points = [list(p) for p in self.model.get_line_points(key)]
            for index, (dx, dy) in moves.items():
                if index < len(points):
                    points[index] = [points[index][0] + dx,
                                     points[index][1] + dy]
            self.model.set_line_points(key, points, text=text)
        stack.endMacro()

    def update_pan_cursor(self):
        """A closed hand while panning, an open one while the pan key is
        held ready to, and otherwise the usual arrow."""
        if self.panning:
            self.viewport().setCursor(QtCore.Qt.ClosedHandCursor)
        elif self._pan_key_held:
            self.viewport().setCursor(QtCore.Qt.OpenHandCursor)
        else:
            self.viewport().unsetCursor()

    def start_panning(self):
        self.panning = True
        self._previous_mouse_pos = None
        self.update_pan_cursor()

    def stop_panning(self):
        self._previous_mouse_pos = None
        self.panning = False
        self._pan_key_panning = False
        self._current_pan_distance = 0.0
        self.update_pan_cursor()

    def layout_nodes(self):
        """Lay out the selected top level nodes, or every one when none are
        selected, by the order they run in, as one undo: each exec chain
        left to right and its branches stacked below, see
        nxt_editor.auto_layout. The nodes stay where they were as a group,
        starting from the top left of where they were.

        A backdrop with nodes being laid out in it is fitted around them
        again afterwards, so they stay in it.

        Nodes hidden with their layers are left where they are, and so
        are backdrops only hidden layers draw.
        """
        # Here rather than at the top: the dock widgets import a lot.
        from nxt_editor.dockwidgets.outliner import root_exec_order
        selected = set(nxt_path.get_root_path(p)
                       for p in self.model.get_selected_nodes()
                       if p != nxt_path.WORLD)
        paths = [path for path in root_exec_order(self.model)
                 if (not selected or path in selected) and
                 self.get_node_graphic(path) and
                 not self.node_hidden(path) and
                 not self.model.get_node_locked(path)]
        if not paths:
            return
        rects = {}
        for path in paths:
            rects[path] = self._nodes_rect([self.get_node_graphic(path)])
        exec_in = dict((p, self.model.get_node_exec_in(p)) for p in paths)
        sizes = dict((p, (r.width(), r.height())) for p, r in rects.items())
        places = auto_layout.arrange(paths, exec_in, sizes)
        origin = QtCore.QRectF()
        for rect in rects.values():
            origin = origin.united(rect)
        origin = origin.topLeft()
        snap = self.alignment_actions.snap_action.isChecked()
        positions = {}
        moves = {}
        for path in paths:
            graphic = self.get_node_graphic(path)
            # Where the node is drawn from, which its plugs reach past.
            inset = graphic.pos() - rects[path].topLeft()
            x, y = places[path]
            pos = QtCore.QPointF(origin.x() + x, origin.y() + y) + inset
            if snap:
                pos = QtCore.QPointF(*self.model.snap_pos_to_grid(
                    (pos.x(), pos.y())))
            positions[path] = [pos.x(), pos.y()]
            moves[path] = pos - graphic.pos()
        # Which backdrop each node is in, before anything moves.
        fits = {}
        for backdrop_id, graphic in self._backdrop_graphics.items():
            if not graphic.isVisible():
                continue
            nodes, _ = self.backdrop_contents(graphic)
            inside = [g.node_path for g in nodes
                      if not self.node_hidden(g.node_path)]
            if any(path in moves for path in inside):
                fits[backdrop_id] = (graphic, inside)
        changes = {}
        pad = self.BACKDROP_PADDING
        for backdrop_id, (graphic, inside) in fits.items():
            rect = QtCore.QRectF()
            for path in inside:
                node_rect = rects.get(path)
                if node_rect is None:
                    node_rect = self._nodes_rect(
                        [self.get_node_graphic(path)])
                rect = rect.united(node_rect.translated(
                    moves.get(path, QtCore.QPointF())))
            header = graphic.header_rect().height()
            record = copy.deepcopy(graphic.record)
            record[backdrops.POS] = [rect.left() - pad,
                                     rect.top() - pad - header]
            record[backdrops.SIZE] = [rect.width() + (pad * 2),
                                      rect.height() + (pad * 2) + header]
            changes[backdrop_id] = record
        if len(positions) > 1:
            text = 'Layout {} nodes'.format(len(positions))
        else:
            text = 'Layout {}'.format(paths[0])
        stack = self.model.undo_stack
        stack.beginMacro(text)
        self.model.set_nodes_pos(positions, layer=self._position_layer())
        if changes:
            self.model.set_backdrops(changes, text=text)
        stack.endMacro()

    def keyPressEvent(self, event):
        key = event.key()
        if key == self.PAN_KEY and self.scene().focusItem() is None:
            # Held down, a key repeats, so it is only taken the first time.
            if not event.isAutoRepeat():
                self._pan_key_held = True
                self.update_pan_cursor()
            event.accept()
            return
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
        if key == self.PAN_KEY and self._pan_key_held:
            if not event.isAutoRepeat():
                self._pan_key_held = False
                self.update_pan_cursor()
            event.accept()
            return
        if key in self._held_keys:
            self._held_keys.remove(key)
        self.zooming = False
        if self._parent.zoom_keys_down:
            if self.zoom_button_down:
                self._previous_mouse_pos = self.mouse_scene_pos
                self.zooming = True
        super(StageView, self).keyReleaseEvent(event)

    def mousePressEvent(self, event):
        if self.mini_map.handle_mouse_press(event):
            return
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
        if event.buttons() == QtCore.Qt.LeftButton | QtCore.Qt.MiddleButton:
            self.zooming = True
            self.zoom_start_pos = event.pos()
            self._previous_mouse_pos = event.pos()
            event.accept()

        if (event.button() == QtCore.Qt.LeftButton and self._pan_key_held
                and not self.zooming):
            # The pan key held turns a left drag into panning, and keeps
            # it from selecting or moving anything.
            self._pan_key_panning = True
            self.start_panning()
            event.accept()
            return

        # left button event
        if event.button() == QtCore.Qt.LeftButton:
            if not self.zooming and (self.point_press(event) or
                                     self.backdrop_press(event)):
                event.accept()
                return
            # get item under event. A line is no more than open space to a
            # left press, so a box can start on or between lines.
            item = next((i for i in self.items(event.pos())
                         if not isinstance(i, AttrConnectionGraphic)), None)

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
            self.start_panning()
            event.accept()
            return

        super(StageView, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.mini_map.handle_mouse_move(event):
            return
        if self._point_drag is not None:
            self.mouse_scene_pos = self.mapToScene(event.pos())
            self.point_drag_move(event)
            event.accept()
            return
        if self._backdrop_drag is not None:
            self.mouse_scene_pos = self.mapToScene(event.pos())
            self.backdrop_drag_move(event)
            event.accept()
            return
        # rubber band action
        if self._rubber_band_origin is not None:
            self.rubber_band.show()
            rect = QtCore.QRect(self._rubber_band_origin, event.pos()).normalized().translated(4, 4)
            self.rubber_band.setGeometry(rect)

        # connection action
        self.mouse_scene_pos = self.mapToScene(event.pos())
        if self.potential_connection:
            self.set_snap_plug(self.snap_plug_near(self.mouse_scene_pos))
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
            scale = self.scale_factor or 1.0
            self.make_room(self.view_rect().translated(offset / scale))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + offset.y())
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + offset.x())
            self._current_pan_distance += math.sqrt(abs(offset.x()) ** 2 + abs(offset.y()) ** 2)
            self._previous_mouse_pos = event.pos()
            event.accept()
            return
        super(StageView, self).mouseMoveEvent(event)
        item = self.itemAt(event.pos())
        app = QtWidgets.QApplication
        if self._pan_key_held:
            # Ready to pan, not to click anything.
            app.restoreOverrideCursor()
        elif item and hasattr(item, 'locked') and item.locked:
            if not app.overrideCursor():
                app.setOverrideCursor(QtCore.Qt.ForbiddenCursor)
        else:
            app.restoreOverrideCursor()

    def mouseReleaseEvent(self, event):
        if self.mini_map.handle_mouse_release(event):
            return
        if (self._pan_key_panning and
                event.button() == QtCore.Qt.LeftButton):
            self.stop_panning()
            event.accept()
            return
        if (self._point_drag is not None and
                event.button() == QtCore.Qt.LeftButton):
            self.point_release()
            event.accept()
            return
        if (self._backdrop_drag is not None and
                event.button() == QtCore.Qt.LeftButton):
            self.backdrop_release()
            event.accept()
            return
        was_just_zooming = self.zooming
        self.zooming = False
        if event.button() is self.zoom_button:
            self.zoom_button_down = False
        if self._parent.zoom_keys_down and self.zoom_button_down:
            self.zooming = True
            event.accept()

        if self.zooming:
            if event.buttons() == QtCore.Qt.LeftButton | QtCore.Qt.MiddleButton:
                self.zooming = False
            elif event.buttons() == QtCore.Qt.LeftButton:
                self.zooming = False
            elif event.buttons() == QtCore.Qt.MiddleButton:
                self.zooming = False
        if (self._rubber_band_origin is not None and
           event.button() is QtCore.Qt.LeftButton):
            # complete rubber band action
            self._rubber_band_origin = None
            rubber_band_geo = self.mapToScene(self.rubber_band.geometry())
            selection_area_rect = rubber_band_geo.boundingRect()
            self.finish_drawing()
            # end rubber band action
            self.rubber_band.hide()
            # get items under selection area
            node_paths = []
            for item in self.scene().items(selection_area_rect):
                if (isinstance(item, NodeGraphicsItem) and
                        not self.node_hidden(item.node_path)):
                    node_paths.append(item.node_path)
            self.box_select_points(self.points_in(selection_area_rect),
                                   event.modifiers())
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
            # The plug nearest the drop that takes the line, not only one
            # right under the mouse, see snap_plug_near.
            dropped_plug = self.snap_plug_near(self.mapToScene(event.pos()))
            self.set_snap_plug(None)
            if dropped_plug is not None:
                dropped_node_path = dropped_plug.node_path
                locked = self.model.get_node_locked(dropped_node_path)
                dropped_attr_name = dropped_plug.attr_name
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
            self.stop_panning()
            event.accept()
            return
        super(StageView, self).mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        event.pos()
        if event.button() == QtCore.Qt.LeftButton:
            # Double click a point to remove it, or a line to add one.
            point = self.point_at(event.pos())
            if point is not None:
                self._point_drag = None
                self.remove_line_point(point)
                return
            item = self.itemAt(event.pos())
            if item is None or isinstance(item, (AttrConnectionGraphic,
                                                 BackdropGraphicsItem)):
                scene_pos = self.mapToScene(event.pos())
                connection = self.connection_at(scene_pos)
                if connection is not None:
                    self._backdrop_drag = None
                    self.add_line_point(connection, scene_pos)
                    return
            if isinstance(item, BackdropGraphicsItem):
                self._backdrop_drag = None
                self.edit_backdrop(item.backdrop_id)
                return
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
        self._view_pos = event.position().toPoint()
        self._scene_pos = self.mapToScene(self._view_pos)

        try:
            new_scale = event.angleDelta().y() * .001 + 1.0
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

    def snap_plug_near(self, scene_pos):
        """Where the line being dragged connects if dropped at scene_pos:
        the nearest plug that can take it, within PLUG_SNAP_PIXELS on
        screen of its edge, so a plug is as easy to drop on zoomed out as
        in. Zoomed out far enough that plugs are not drawn, they are still
        where they would be.

        An input takes a line from an output and the other way round, an
        exec plug only an exec line between top level nodes, and a
        property plug only a property line. Locked nodes take nothing.

        :return: PlugTarget or None
        """
        line = self.potential_connection
        if line is None:
            return None
        from_input = not line.src_path
        dragged = line.tgt_path if from_input else line.src_path
        exec_attr = nxt_node.INTERNAL_ATTRS.EXECUTE_IN
        is_exec = nxt_path.attr_name_from_attr_path(dragged) == exec_attr
        room = self.PLUG_SNAP_PIXELS / (self.scale_factor or 1.0)
        # Wide enough to find a node whose plug sticks out past its edge.
        reach = room + NodeGraphicsItem.EXEC_PLUG_RADIUS
        area = QtCore.QRectF(scene_pos.x() - reach, scene_pos.y() - reach,
                             reach * 2, reach * 2)
        nearest, best = None, None
        for item in self.scene().items(area):
            if not isinstance(item, NodeGraphicsItem) or not item.isVisible():
                continue
            node_path = item.node_path
            if self.model.get_node_locked(node_path):
                continue
            if is_exec:
                if nxt_path.get_root_path(node_path) != node_path:
                    continue
                if node_path == nxt_path.node_path_from_attr_path(dragged):
                    # A node's exec cannot come from itself.
                    continue
                attrs = [exec_attr]
                radius = NodeGraphicsItem.EXEC_PLUG_RADIUS
            else:
                attrs = item.user_attr_names
                radius = NodeGraphicsItem.ATTR_PLUG_RADIUS
            for attr in attrs:
                # Dragged out of an input, it is dropped on an output.
                if from_input:
                    pos = item.get_attr_out_pos(attr, scene=True)
                else:
                    pos = item.get_attr_in_pos(attr, scene=True)
                if pos is None:
                    continue
                gap = math.hypot(pos.x() - scene_pos.x(),
                                 pos.y() - scene_pos.y()) - radius
                if gap <= room and (best is None or gap < best):
                    nearest = PlugTarget(node_path, attr, not from_input,
                                         pos, radius)
                    best = gap
        return nearest

    def set_snap_plug(self, target):
        """Mark the plug the line being dragged would connect to."""
        if target == self.snap_plug:
            return
        self.snap_plug = target
        self.viewport().update()

    def connection_drag_pos(self):
        """Where the loose end of the line being dragged is drawn to: the
        plug it snaps to, or else the mouse."""
        if self.snap_plug is not None:
            return QtCore.QPointF(self.snap_plug.pos)
        return self.mouse_scene_pos

    def draw_snap_plug(self, painter):
        """Ring the plug the line being dragged would connect to, the way a
        plug under the mouse is."""
        target = self.snap_plug
        if target is None or self.potential_connection is None:
            return
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(QtGui.QPen(QtCore.Qt.white, 1.0))
        painter.setBrush(QtCore.Qt.NoBrush)
        radius = target.radius + 2
        painter.drawEllipse(target.pos, radius, radius)
        painter.restore()

    def lines_at(self, view_pos):
        """The lines a right click at view_pos is about.

        On a plug, every line into or out of it. On a line, or a point on
        one, that line. Only lines that are shown. Lines into a node's code
        can be gone to but not broken, see StageModel.break_connections.

        :return: list of AttrConnectionGraphic
        """
        point = self.point_at(view_pos)
        if point is not None:
            found = [point.connection]
        else:
            plug = None
            for item in self.items(view_pos):
                if isinstance(item, NodeGraphicsPlug):
                    plug = item
                    break
            if plug is not None:
                found = self.plug_lines(plug)
            else:
                line = self.connection_at(self.mapToScene(view_pos))
                found = [line] if line else []
        return [line for line in found if line.isVisible()]

    def plug_lines(self, plug):
        node_path = plug.parentItem().node_path
        attr = plug.attr_name_represented
        exec_attr = nxt_node.INTERNAL_ATTRS.EXECUTE_IN
        if plug.is_input:
            path = nxt_path.make_attr_path(node_path, attr)
            return [line for line in self._connection_graphics
                    if line.tgt_path == path]
        if attr == exec_attr:
            # An exec line starts at the node itself.
            path = node_path
        else:
            path = nxt_path.make_attr_path(node_path, attr)
        return [line for line in self._connection_graphics
                if line.src_path == path]

    def lines_menu(self, lines):
        """Show the right click menu for lines."""
        menu = self.make_lines_menu(lines)
        menu.exec_(self.mapToGlobal(self._initial_click_pos))

    def make_lines_menu(self, lines):
        """The right click menu for lines: break them, or go to either end
        of one."""
        menu = QtWidgets.QMenu(self)
        pairs = [(line.src_path, line.tgt_path) for line in lines
                 if self.model._breakable(line.tgt_path)]
        if pairs:
            if len(pairs) == 1:
                text = 'Break Connection'
            else:
                text = 'Break {} Connections'.format(len(pairs))
            action = menu.addAction(text)
            action.triggered.connect(
                lambda: self.model.break_connections(pairs))
        if len(lines) == 1:
            line = lines[0]
            if pairs:
                menu.addSeparator()
            for text, path in (('Go to Source', line.src_node_path),
                               ('Go to Target', line.tgt_node_path)):
                go = menu.addAction('{}: {}'.format(text, path))
                go.triggered.connect(partial(self.go_to_node, path))
        return menu

    def point_menu(self, point=None):
        """Show the right click menu for a point on a line, or with none,
        for the selected points."""
        menu = self.make_point_menu(point)
        menu.exec_(self.mapToGlobal(self._initial_click_pos))

    def make_point_menu(self, point=None):
        """The right click menu for points on lines: line them up with each
        other and the selected nodes, or remove them.

        A point right clicked that is not selected is selected first,
        alongside any selected nodes. With no point, it is for the points
        already selected, as a right click off them is, the way the node
        menu is for the selected nodes.
        """
        if point is not None:
            ref = self._point_ref(point)
            if ref not in self._selected_points:
                self.select_points([ref])
        menu = QtWidgets.QMenu(self)
        self.add_align_menu(menu)
        menu.addSeparator()
        count = len(self._selected_points)
        text = 'Remove Point' if count == 1 else             'Remove {} Points'.format(count)
        remove = menu.addAction(text)
        remove.triggered.connect(self.delete_selected_points)
        return menu

    def contextMenuEvent(self, event):
        if self.block_context_menu:  # Check if we shouldn't spawn the menu
            return
        item = self.itemAt(self._initial_click_pos)
        point = self.point_at(self._initial_click_pos)
        if point is not None:
            self.point_menu(point)
            return
        lines = self.lines_at(self._initial_click_pos)
        if lines:
            self.lines_menu(lines)
            return
        if isinstance(item, BackdropGraphicsItem):
            self.backdrop_menu(item)
            self.block_context_menu = True
            return
        if (self._selected_points and
                not isinstance(item, NodeGraphicsItem) and
                not self.model.get_selected_nodes()):
            # Off the selected points, still about them. With nodes
            # selected too, the node menu's Align takes in the points.
            self.point_menu()
            return
        hov_path = None
        if isinstance(item, NodeGraphicsItem):
            hov_path = item.node_path
        menu = self.node_menu(hov_path)
        menu.exec_(self.mapToGlobal(self._initial_click_pos))
        self.block_context_menu = True  # Set the block var to true again

    def node_menu(self, hov_path=None, parent=None):
        """The right click menu for nodes: running them, and editing the
        selected ones. The Outliner shows the same one for its rows.

        :param hov_path: the node right clicked on, if any
        :param parent: the widget to parent the menu to, this view if None
        :rtype: QtWidgets.QMenu
        """
        menu = QtWidgets.QMenu(parent or self)
        if hov_path:
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
        menu.addAction(self.authoring_actions.add_backdrop_action)
        if selected_nodes_count == 0:
            # With nothing selected it lays out the whole graph.
            menu.addAction(self.alignment_actions.layout_action)
        if selected_nodes_count == 1:
            menu.addAction(self.authoring_actions.rename_node_action)
            if sub_graphs.graph_path(self.model, selected_nodes[0]):
                menu.addAction(self.authoring_actions.open_sub_graph_action)
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
            self.add_align_menu(menu)
            menu.addAction(self.alignment_actions.layout_action)
            menu.addSeparator()
            menu.addAction(self.authoring_actions.localize_node_action)
            if nodes_only_on_tgt:
                menu.addAction(self.authoring_actions.revert_node_action)
            # Positions are written to the top layer, so there is only
            # somewhere else to push them with a lower layer the target.
            push = self.authoring_actions.push_positions_action
            push.setEnabled(self.model.target_layer is not
                            self.model.top_layer)
            menu.addAction(push)
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
        if selected_nodes_count > 0:
            menu.addSeparator()
            menu.addAction(self.exec_actions.toggle_start_action)
            menu.addAction(self.exec_actions.toggle_break_action)
            menu.addAction(self.exec_actions.toggle_skip_action)
        return menu

    def add_align_menu(self, menu):
        """Add the Align submenu, greyed out until there are two things
        selected to line up."""
        align_menu = self.alignment_actions.align_menu(menu)
        align_menu.setEnabled(len(self.layout_boxes()) > 1)
        menu.addMenu(align_menu)

    @staticmethod
    def get_sel_path_for_graphic(graphic):
        # NOTE maybe this can be a subclass for graphics items?
        if isinstance(graphic, NodeGraphicsItem):
            return graphic.node_path
        # if isinstance(graphic, AttrConnectionGraphic):
        #     return graphic.tgt_path
        return None

    def on_model_selection_changed(self, new_selection):
        if self.defer_update():
            # Nothing drawn to keep up with, see defer_update.
            return
        # The map draws selection live, outside its cached node blocks, so
        # it needs its corner repainted. Selection changes otherwise only
        # repaint the nodes involved.
        self.mini_map.request_repaint()
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
            # Draws a node still waiting to be, see _draw_later.
            graphic = self.get_node_graphic(path)
            if graphic:
                graphic.setSelected(True)
                continue
            # TODO Track connections by target path to allow attr connections
            #  to be added here.
            if path == nxt_path.WORLD:
                continue
            if self.model.get_collapsed_ancestor(path):
                # Stays selected while a node above it is collapsed, and
                # is shown selected again when it is expanded.
                continue
            logger.error("Cannot find item to select: " + str(path))

    #: An expand drawing more nodes than this shows them as it goes, see
    #: handle_nodes_changed.
    PROGRESSIVE_DRAW = 300
    #: Seconds before the first of the nodes drawn so far are shown, and
    #: between showing more.
    FIRST_SHOW = 0.15
    SHOW_EVERY = 0.75

    def handle_nodes_changed(self, node_paths, progressive=False):
        """Draw, update or remove the graphics of node_paths.

        :param progressive: show the nodes drawn so far every so often, so
            a big expand is seen to be happening rather than leaving the
            window frozen until it is done. Input waits until the end, so
            nothing can change the graph part way through.
        """
        if self.defer_update():
            # Nothing drawn to keep up with, see defer_update.
            return
        with user_dir.holding_prefs():
            self._handle_nodes_changed(node_paths, progressive)

    def _handle_nodes_changed(self, node_paths, progressive=False):
        updated_paths = []
        roots_hit = set()
        new_nodes = []
        progressive = progressive and len(node_paths) > self.PROGRESSIVE_DRAW
        show_at = time.time() + self.FIRST_SHOW
        for path in node_paths:
            if progressive and time.time() > show_at:
                for root in roots_hit:
                    graphic = self.get_node_graphic(root)
                    if graphic:
                        graphic.arrange_descendants()
                QtWidgets.QApplication.processEvents(
                    QtCore.QEventLoop.ExcludeUserInputEvents)
                show_at = time.time() + self.SHOW_EVERY
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
                    # The node keeps a picture of itself, see its cache
                    # mode, which a change of color or text leaves stale.
                    graphic.update()
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
        # Lines start and end at a node's attribute plugs, which move or
        # come and go as its attributes are shown and hidden.
        # Each once: a line between two updated nodes is found from both.
        to_rebuild = {}
        for node_path in updated_paths:
            for line in self.get_node_connection_graphics(node_path):
                to_rebuild[line] = None
        for line in to_rebuild:
            line.rebuild_line()
        self.apply_layer_visibility()

    def handle_attrs_changed(self, attr_paths):
        """Handler for the model signal 'attrs_changes'.
        :param attr_paths: Tuple of attr paths /node.attr
        :return: None
        """
        if self.defer_update():
            # Nothing drawn to keep up with, see defer_update.
            return
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
        if self.defer_update():
            # Nothing drawn to keep up with, see defer_update.
            return
        node_item = self.get_node_graphic(node_path)
        if node_item:
            node_item.setPos(pos[0], pos[1])

    def set_animations(self, state):
        """Turn node open and close animations on or off for this view.

        :param state: True to animate
        :type state: bool
        """
        self._do_anim_pref = state
        self.do_animations = state

    def handle_collapse_changed(self, node_paths):
        if self.defer_update():
            # Nothing drawn to keep up with, see defer_update.
            return
        while self._animating:
            QtWidgets.QApplication.processEvents()
        og_do_anims = self.do_animations
        self.do_animations = self._do_anim_pref
        comp_layer = self.model.comp_layer
        roots_hit = set()
        # Everything an expand shows, gathered and drawn once at the end.
        # Expanding a hierarchy as a whole names every node in it, and
        # drawing each one's descendants as it came laid out and lined up
        # the whole tree again for every node, which took minutes on a big
        # one.
        shown = []
        shown_set = set()
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
            elif path not in shown_set:
                # A node under one already gathered came with it.
                descendants = self.model.get_descendants(path,
                                                         include_implied=True)
                for child_path in descendants:
                    if child_path not in shown_set:
                        shown_set.add(child_path)
                        shown.append(child_path)
        if shown:
            big = len(shown) > self.PROGRESSIVE_DRAW
            if big:
                QtWidgets.QApplication.setOverrideCursor(
                    QtCore.Qt.WaitCursor)
            try:
                self.handle_nodes_changed(shown, progressive=True)
            finally:
                if big:
                    QtWidgets.QApplication.restoreOverrideCursor()
        for root_path in roots_hit:
            root_graphic = self.get_node_graphic(root_path)
            if not root_graphic:
                continue
            root_graphic.arrange_descendants()
        self.do_animations = og_do_anims

    def remove_node_graphic(self, node_path):
        root = self._pending_root_of.pop(node_path, None)
        if root is not None:
            waiting = self._pending_draw.get(root, [])
            if node_path in waiting:
                waiting.remove(node_path)
            if not waiting:
                self._pending_draw.pop(root, None)
        if node_path not in self._node_graphics:
            return
        graphic = self._node_graphics.pop(node_path)
        if not graphic:
            return
        self.remove_node_connection_graphics(node_path)

        def handle_del():
            if graphic.scene():
                self.scene().removeItem(graphic)

        graphic.out_anim_group.finished.connect(handle_del)
        graphic.anim_out()

    def get_node_graphic(self, name):
        """The node's graphic, drawing it now if it is still waiting to be,
        see _draw_later."""
        graphic = self._node_graphics.get(name, None)
        if graphic is None and name in self._pending_root_of:
            self._draw_pending_roots([self._pending_root_of[name]])
            graphic = self._node_graphics.get(name, None)
        return graphic

    def _build_focus_changed(self, *signal_args):
        """Redraw the node a build left and the one it is now running."""
        focus = self.model.get_build_focus() if self.model.executing else ''
        previous, self._build_focus_path = self._build_focus_path, focus
        for path in {previous, focus}:
            item = self._node_graphics.get(path) if path else None
            if item is not None:
                item.update_build_focus()


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
