"""Lining up nodes and the points lines are routed through.

Everything is a box here: a node is the box it is drawn in, and a point is
a box with no size, at the point. Boxes are (left, top, right, bottom) in
scene positions, and each function says how far to move each one.

Aligning moves every box to the same edge, or the same middle, as the
others: the left most left, the top most top, and so on, and the middle of
them all for the middles. Distributing keeps the boxes at either end where
they are and spaces the rest between them, with the same gap between each.
"""

LEFT = 'left'
HCENTER = 'hcenter'
RIGHT = 'right'
TOP = 'top'
VCENTER = 'vcenter'
BOTTOM = 'bottom'
EDGES = (LEFT, HCENTER, RIGHT, TOP, VCENTER, BOTTOM)

HORIZONTAL = 'horizontal'
VERTICAL = 'vertical'


def align_offsets(boxes, edge):
    """How far to move each box so they all line up on an edge.

    :param boxes: {key: (left, top, right, bottom)}
    :param edge: one of EDGES
    :return: {key: (dx, dy)} for the boxes that move
    """
    if len(boxes) < 2:
        return {}
    lefts = [b[0] for b in boxes.values()]
    tops = [b[1] for b in boxes.values()]
    rights = [b[2] for b in boxes.values()]
    bottoms = [b[3] for b in boxes.values()]
    if edge == LEFT:
        target, side = min(lefts), lambda b: b[0]
    elif edge == RIGHT:
        target, side = max(rights), lambda b: b[2]
    elif edge == HCENTER:
        target = (min(lefts) + max(rights)) / 2.0
        side = lambda b: (b[0] + b[2]) / 2.0  # noqa: E731
    elif edge == TOP:
        target, side = min(tops), lambda b: b[1]
    elif edge == BOTTOM:
        target, side = max(bottoms), lambda b: b[3]
    elif edge == VCENTER:
        target = (min(tops) + max(bottoms)) / 2.0
        side = lambda b: (b[1] + b[3]) / 2.0  # noqa: E731
    else:
        raise ValueError('Unknown edge: {}'.format(edge))
    across = edge in (LEFT, HCENTER, RIGHT)
    offsets = {}
    for key, box in boxes.items():
        move = target - side(box)
        if not move:
            continue
        offsets[key] = (move, 0.0) if across else (0.0, move)
    return offsets


def distribute_offsets(boxes, axis):
    """How far to move each box so there is the same gap between each one
    and the next along an axis. The first and last stay where they are.

    :param boxes: {key: (left, top, right, bottom)}
    :param axis: HORIZONTAL or VERTICAL
    :return: {key: (dx, dy)} for the boxes that move
    """
    if len(boxes) < 3:
        return {}
    if axis == HORIZONTAL:
        start, end = 0, 2
    elif axis == VERTICAL:
        start, end = 1, 3
    else:
        raise ValueError('Unknown axis: {}'.format(axis))

    def middle(key):
        box = boxes[key]
        return (box[start] + box[end]) / 2.0
    order = sorted(boxes, key=lambda k: (middle(k), str(k)))
    first, last = boxes[order[0]], boxes[order[-1]]
    sizes = sum(boxes[k][end] - boxes[k][start] for k in order[1:-1])
    room = last[start] - first[end] - sizes
    gap = room / (len(order) - 1)
    offsets = {}
    at = first[end] + gap
    for key in order[1:-1]:
        box = boxes[key]
        move = at - box[start]
        if move:
            offsets[key] = (move, 0.0) if axis == HORIZONTAL else (0.0, move)
        at += box[end] - box[start] + gap
    return offsets
