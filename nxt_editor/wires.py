"""How the lines between nodes are drawn: straight or curved, and the points
a line is routed through.

Both are only pictures. They are saved in the layer's meta data, next to
the node positions and backdrops::

    "meta_data": {
        "connection_style": "curved",
        "connection_points": {
            "/setup>/build._execute_in": [[220.0, 40.0], [220.0, 180.0]],
            "/rig.out>/export.rig": [[600.0, 90.0]]
        }
    }

A line is known by its source and target, joined by ``>``. The source is a
node path for an exec connection and an attribute path otherwise; the
target is always an attribute path. Points are scene positions, in the
order the line passes through them, and they stay where they are put when
the nodes move.

The style belongs to the graph, so everyone who opens it sees the same
lines. Like backdrops, both are authored on the top layer and every
layer's are shown, a higher layer's winning. Removing a lower layer's
points writes ``null`` over them on the top layer.

Any version of nxt keeps meta data it does not know about when it saves a
layer, so a graph with these opens and saves in an older editor without
losing them.
"""
# Built-in
import copy

#: Keys in a layer's meta data.
STYLE_KEY = 'connection_style'
POINTS_KEY = 'connection_points'

STRAIGHT = 'straight'
CURVED = 'curved'
STYLES = (STRAIGHT, CURVED)
DEFAULT_STYLE = STRAIGHT


class _Absent(object):
    """Not on the layer at all, as opposed to None which hides one."""

    def __repr__(self):
        return 'ABSENT'

    def __deepcopy__(self, memo):
        return self


ABSENT = _Absent()


def line_key(src_path, tgt_path):
    """The name a line's points are saved under."""
    return '{}>{}'.format(src_path, tgt_path)


def clean_points(points):
    """A copy of a list of points with each one a pair of floats.

    A layer can be edited by hand, so nothing read from one is trusted.
    Anything that is not a point is dropped. Returns None for something
    that is not a list at all.
    """
    if not isinstance(points, (list, tuple)):
        return None
    cleaned = []
    for point in points:
        try:
            cleaned.append([float(point[0]), float(point[1])])
        except (IndexError, TypeError, ValueError):
            continue
    return cleaned


def _meta(layer, create=False):
    meta = getattr(layer, '_input_metadata', None)
    if not isinstance(meta, dict):
        if not create:
            return {}
        meta = {}
        layer._input_metadata = meta
    return meta


def layer_style(layer):
    """The style one layer itself saves, or ABSENT."""
    style = _meta(layer).get(STYLE_KEY, ABSENT)
    if style in STYLES:
        return style
    return ABSENT


def layer_points(layer):
    """The points one layer itself saves, as stored. Do not edit it.

    :return: {line key: [[x, y], ...] or None}
    """
    found = _meta(layer).get(POINTS_KEY)
    if not isinstance(found, dict):
        return {}
    return found


def write_style(layer, style):
    """Set one layer's style, or take it off the layer with ABSENT."""
    meta = _meta(layer, create=True)
    if style is ABSENT:
        meta.pop(STYLE_KEY, None)
    else:
        meta[STYLE_KEY] = style


def write_points(layer, changes):
    """Write points onto one layer.

    :param changes: {line key: points, None (hide a lower layer's) or
        ABSENT}
    """
    meta = _meta(layer, create=True)
    stored = dict(layer_points(layer))
    for key, points in changes.items():
        if points is ABSENT:
            stored.pop(key, None)
        else:
            stored[key] = copy.deepcopy(points)
    if stored:
        meta[POINTS_KEY] = dict(sorted(stored.items()))
    else:
        meta.pop(POINTS_KEY, None)


def merged_style(layers, default=DEFAULT_STYLE):
    """The style the graph shows: the highest layer that saves one.

    :param layers: top layer first, as a stage holds them
    :param default: the style when no layer saves one
    """
    for layer in layers:
        style = layer_style(layer)
        if style is not ABSENT:
            return style
    return default


def merged_points(layers):
    """Every line's points the layers show, a higher layer's winning.

    :param layers: top layer first, as a stage holds them
    :return: {line key: [[x, y], ...]}
    """
    shown = {}
    for layer in reversed(list(layers)):
        for key, points in layer_points(layer).items():
            if points is None:
                shown.pop(key, None)
                continue
            points = clean_points(points)
            if points:
                shown[key] = points
            else:
                shown.pop(key, None)
    return shown


def insert_index(start, points, end, pos):
    """Where a new point at ``pos`` goes in a line's points: in the segment
    it is nearest to, so the line keeps its shape.

    :param start: (x, y) where the line leaves its source
    :param points: the line's points
    :param end: (x, y) where the line meets its target
    :param pos: (x, y) of the new point
    :return: index to insert at
    """
    anchors = [tuple(start)] + [tuple(p) for p in points] + [tuple(end)]
    best_index = len(points)
    best_dist = None
    for index in range(len(anchors) - 1):
        dist = _segment_distance(anchors[index], anchors[index + 1], pos)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_index = index
    return best_index


def _segment_distance(a, b, p):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    if not length:
        t = 0.0
    else:
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    cx, cy = ax + t * dx, ay + t * dy
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5
