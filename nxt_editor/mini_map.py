# Built-in
import logging
import time

# External
from Qt import QtGui
from Qt import QtCore

# Internal
import nxt_editor
from nxt_editor import colors

logger = logging.getLogger(nxt_editor.LOGGER_NAME)


class MiniMap(object):
    """Overlay showing the whole graph and where the view is inside it.

    Drawn straight into the view's foreground rather than as a child widget.
    A child widget over a QGraphicsView cannot repaint without dragging the
    view into repainting with it, which on a large graph costs far more than
    everything the mini map does put together. Painting in the foreground
    means the map rides along with repaints the view was doing anyway.

    The node blocks are rendered once into a pixmap and re-used, so a frame
    costs a blit plus a stroked rectangle. That pixmap is only rebuilt when
    the graph itself changes, and not until something actually paints, so a
    hidden mini map does no work at all.
    """

    # Size of the map, in viewport pixels.
    WIDTH = 220
    HEIGHT = 150
    # Gap between the map and the viewport corner.
    MARGIN = 10
    # Space between the node blocks and the map edge.
    PADDING = 6
    # Smallest a node block is allowed to get, so nodes stay visible when the
    # whole graph is squeezed into the map.
    MIN_BLOCK_SIZE = 2.0
    # Graph edits are coalesced for at least this long before the pixmap is
    # rebuilt. Dragging nodes emits a change per mouse move, this keeps that
    # from turning into a rebuild per mouse move.
    REBUILD_DELAY_MS = 80
    # On a big graph a rebuild is not free, so the delay grows to this
    # multiple of the last rebuild. Small graphs stay at the floor above,
    # large ones back off instead of eating the frame budget.
    REBUILD_DELAY_FACTOR = 4
    MAX_REBUILD_DELAY_MS = 1000

    BG_COLOR = QtGui.QColor(24, 24, 24, 235)
    BORDER_COLOR = QtGui.QColor(90, 90, 90, 220)
    VIEWPORT_COLOR = QtGui.QColor(230, 230, 230, 190)
    VIEWPORT_FILL = QtGui.QColor(255, 255, 255, 20)

    def __init__(self, view):
        """
        :param view: view this mini map is drawn over
        :type view: nxt_editor.stage_view.StageView
        """
        self.view = view
        self.visible = False

        # Cached node blocks.
        self._pixmap = None
        self._dirty = True
        # Scene rectangle the cached pixmap covers.
        self._mapped_rect = QtCore.QRectF()
        # Scene to map transform, derived from _mapped_rect on rebuild. The
        # offset is relative to the map's own top left, not the viewport.
        self._scale = 1.0
        self._offset = QtCore.QPointF(0.0, 0.0)
        # Last viewport rectangle drawn, used to skip no-op repaints.
        self._last_view_rect = QtCore.QRectF()
        # How long the last rebuild took, used to pace the next one.
        self._last_rebuild_ms = 0.0
        # Set while the user is dragging inside the map.
        self._dragging = False

        self._rebuild_timer = QtCore.QTimer(view)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.timeout.connect(self.request_repaint)

    # Placement ------------------------------------------------------------

    def viewport_rect(self):
        """Where the map sits, in viewport pixels.

        Read off the viewport every time rather than stored, so the map
        stays in the corner through window resizes for free.
        """
        viewport = self.view.viewport().rect()
        return QtCore.QRect(viewport.right() - self.WIDTH - self.MARGIN + 1,
                            viewport.bottom() - self.HEIGHT - self.MARGIN + 1,
                            self.WIDTH, self.HEIGHT)

    def contains(self, viewport_pos):
        """Whether a viewport position is over the map."""
        if not self.visible or self._pixmap is None:
            return False
        return self.viewport_rect().contains(viewport_pos)

    # Repaint control ------------------------------------------------------

    def request_repaint(self):
        """Ask the view to repaint the corner the map occupies.

        Limited to the map's own rectangle so the rest of the graph is left
        alone.
        """
        if not self.visible:
            return
        self.view.viewport().update(self.viewport_rect())

    def mark_dirty(self, *args, **kwargs):
        """Flag the cached node blocks as out of date.

        Takes and ignores arbitrary arguments so it can be wired straight to
        the model signals, which carry payloads the map does not need. The
        rebuild itself waits for the next paint, so this stays cheap when
        the map is hidden and when edits arrive in bursts.
        """
        self._dirty = True
        if self.visible and not self._rebuild_timer.isActive():
            delay = self._last_rebuild_ms * self.REBUILD_DELAY_FACTOR
            delay = min(max(delay, self.REBUILD_DELAY_MS),
                        self.MAX_REBUILD_DELAY_MS)
            self._rebuild_timer.start(int(delay))

    def sync_viewport(self):
        """Repaint the map only if the view is looking somewhere new.

        The map is drawn in the view's foreground, so a pan or zoom already
        redraws it. This is only here to catch the case where the view
        repaints a region that does not include the map's corner.
        """
        if not self.visible or self._pixmap is None:
            return
        if self._viewport_scene_rect() != self._last_view_rect:
            self.request_repaint()

    def set_visible(self, state):
        self.visible = bool(state)
        if self.visible and self._dirty:
            self.mark_dirty()
        # Repaint the whole viewport, the map has either appeared or needs
        # erasing from the corner.
        self.view.viewport().update()

    # Cache ----------------------------------------------------------------

    def _viewport_scene_rect(self):
        """Rectangle of the scene the view is currently showing."""
        return self.view.mapToScene(self.view.viewport().rect()).boundingRect()

    def _node_blocks(self):
        """Scene rectangle and color of every node currently drawn.

        :return: list of (QRectF, QColor)
        """
        blocks = []
        for graphic in self.view._node_graphics.values():
            if graphic.scene() is None or not graphic.isVisible():
                continue
            node_colors = getattr(graphic, 'colors', None)
            if node_colors:
                color = QtGui.QColor(node_colors[-1])
            else:
                color = QtGui.QColor(QtCore.Qt.darkGray)
            alpha = getattr(graphic, 'color_alpha', 1.0)
            if alpha != 1.0:
                color.setAlphaF(alpha)
            blocks += [(graphic.sceneBoundingRect(), color)]
        return blocks

    def _rebuild_cache(self):
        """Render every node block into the cached pixmap.

        The only expensive thing the map does, and it runs once per graph
        change rather than once per frame.
        """
        build_start = time.time()
        self._dirty = False
        blocks = self._node_blocks()
        bounds = QtCore.QRectF()
        for rect, _ in blocks:
            bounds = bounds.united(rect)
        # An empty graph has nothing to map, and zero sized bounds would make
        # the scale below divide by zero.
        if bounds.isEmpty():
            self._pixmap = None
            self._mapped_rect = QtCore.QRectF()
            return
        self._mapped_rect = bounds

        draw_w = float(self.WIDTH - (self.PADDING * 2))
        draw_h = float(self.HEIGHT - (self.PADDING * 2))
        scale = min(draw_w / bounds.width(), draw_h / bounds.height())
        self._scale = scale
        # Center whichever axis does not fill the map.
        off_x = self.PADDING + ((draw_w - (bounds.width() * scale)) * 0.5)
        off_y = self.PADDING + ((draw_h - (bounds.height() * scale)) * 0.5)
        self._offset = QtCore.QPointF(off_x, off_y)

        ratio = self._device_pixel_ratio()
        pixmap = QtGui.QPixmap(int(self.WIDTH * ratio),
                               int(self.HEIGHT * ratio))
        if ratio != 1.0:
            pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(self.BG_COLOR)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        painter.setPen(QtCore.Qt.NoPen)
        # Mapping is inlined below, it runs once per node and the helper
        # calls it replaces are most of what a rebuild costs.
        left = bounds.left()
        top = bounds.top()
        min_size = self.MIN_BLOCK_SIZE
        fill_rect = painter.fillRect
        make_rect = QtCore.QRectF
        for rect, color in blocks:
            fill_rect(make_rect((rect.left() - left) * scale + off_x,
                                (rect.top() - top) * scale + off_y,
                                max(rect.width() * scale, min_size),
                                max(rect.height() * scale, min_size)),
                      color)
        painter.end()
        self._pixmap = pixmap
        self._last_rebuild_ms = (time.time() - build_start) * 1000.0

    def _device_pixel_ratio(self):
        try:
            return float(self.view.devicePixelRatioF())
        except AttributeError:
            # Qt4 and older Qt5 bindings.
            return float(self.view.devicePixelRatio())

    # Coordinate mapping ---------------------------------------------------
    # Map space is the map's own pixels, origin at its top left corner.

    def _scene_to_map(self, scene_point):
        x = ((scene_point.x() - self._mapped_rect.left()) * self._scale
             + self._offset.x())
        y = ((scene_point.y() - self._mapped_rect.top()) * self._scale
             + self._offset.y())
        return QtCore.QPointF(x, y)

    def _map_to_scene(self, map_point):
        x = ((map_point.x() - self._offset.x()) / self._scale
             + self._mapped_rect.left())
        y = ((map_point.y() - self._offset.y()) / self._scale
             + self._mapped_rect.top())
        return QtCore.QPointF(x, y)

    def _scene_rect_to_map(self, scene_rect):
        """Blocks are clamped to a minimum size, a node squeezed below a
        pixel would otherwise vanish from the map entirely.
        """
        top_left = self._scene_to_map(scene_rect.topLeft())
        return QtCore.QRectF(top_left.x(), top_left.y(),
                             max(scene_rect.width() * self._scale,
                                 self.MIN_BLOCK_SIZE),
                             max(scene_rect.height() * self._scale,
                                 self.MIN_BLOCK_SIZE))

    # Painting -------------------------------------------------------------

    def draw(self, painter):
        """Draw the map. Called from the view's foreground pass.

        :param painter: painter the view is drawing its foreground with
        :type painter: QtGui.QPainter
        """
        if not self.visible:
            return
        if self._dirty:
            self._rebuild_cache()
        if self._pixmap is None:
            return
        painter.save()
        # The foreground painter is in scene space. Drop the view transform
        # so the map is drawn in viewport pixels and stays a fixed size no
        # matter how far the graph is zoomed.
        painter.resetTransform()
        origin = self.viewport_rect().topLeft()
        painter.translate(origin)
        painter.drawPixmap(0, 0, self._pixmap)
        self._draw_selection(painter)
        self._draw_viewport(painter)
        painter.setPen(QtGui.QPen(self.BORDER_COLOR, 1.0))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(QtCore.QRectF(0.5, 0.5,
                                       self.WIDTH - 1.0, self.HEIGHT - 1.0))
        painter.restore()

    def _draw_selection(self, painter):
        """Draw selected nodes over the cached blocks.

        Kept out of the pixmap so that changing selection, which happens far
        more often than the graph changes, does not invalidate the cache.
        """
        selection = self.view.model.selection
        if not selection:
            return
        painter.setPen(QtCore.Qt.NoPen)
        for node_path in selection:
            graphic = self.view.get_node_graphic(node_path)
            if not graphic or graphic.scene() is None:
                continue
            painter.fillRect(
                self._scene_rect_to_map(graphic.sceneBoundingRect()),
                colors.SELECTED)

    def _draw_viewport(self, painter):
        """Draw where the view is looking."""
        view_rect = self._viewport_scene_rect()
        self._last_view_rect = view_rect
        mapped = QtCore.QRectF(self._scene_to_map(view_rect.topLeft()),
                               self._scene_to_map(view_rect.bottomRight()))
        # Zoomed out past the graph the rectangle covers the whole map,
        # clipping keeps the outline on screen instead of off the edge.
        mapped = mapped.intersected(QtCore.QRectF(0, 0,
                                                  self.WIDTH, self.HEIGHT))
        if mapped.isEmpty():
            return
        painter.fillRect(mapped, self.VIEWPORT_FILL)
        painter.setPen(QtGui.QPen(self.VIEWPORT_COLOR, 1.0))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(mapped.adjusted(0.5, 0.5, -0.5, -0.5))

    # Interaction ----------------------------------------------------------

    def handle_mouse_press(self, event):
        """Center the view on a clicked spot in the map.

        :return: whether the event was for the mini map
        :rtype: bool
        """
        if event.button() != QtCore.Qt.LeftButton:
            return False
        if not self.contains(event.pos()):
            return False
        self._dragging = True
        self._center_view_on(event.pos())
        event.accept()
        return True

    def handle_mouse_move(self, event):
        """Keep centering the view while dragging inside the map.

        :return: whether the event was for the mini map
        :rtype: bool
        """
        if not self._dragging:
            return False
        if not event.buttons() & QtCore.Qt.LeftButton:
            self._dragging = False
            return False
        self._center_view_on(event.pos())
        event.accept()
        return True

    def handle_mouse_release(self, event):
        """
        :return: whether the event was for the mini map
        :rtype: bool
        """
        if not self._dragging:
            return False
        self._dragging = False
        event.accept()
        return True

    def _center_view_on(self, viewport_pos):
        origin = self.viewport_rect().topLeft()
        map_pos = QtCore.QPointF(viewport_pos.x() - origin.x(),
                                 viewport_pos.y() - origin.y())
        self.view.centerOn(self._map_to_scene(map_pos))
