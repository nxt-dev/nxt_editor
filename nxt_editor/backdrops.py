"""Backdrops: colored, titled boxes drawn behind groups of nodes.

A backdrop is only a picture. It is not a node, it never runs, and nothing
in it is part of the graph. It is saved in the layer's meta data, next to
the node positions, under ``backdrops``::

    "meta_data": {
        "backdrops": {
            "bd_3f2a9c": {
                "pos": [-40.0, -120.0],
                "size": [620.0, 380.0],
                "title": "Load the rig",
                "note": "Everything that has to run before the rig exists.",
                "color": "#3e5a78"
            }
        }
    }

Any version of nxt keeps meta data it does not know about when it saves a
layer, so a graph with backdrops opens and saves in an older editor
without losing them.

Which nodes a backdrop holds is not saved. It is whatever sits inside it
when it is moved, the way Nuke does it, so renaming, deleting or pasting
nodes never leaves a backdrop holding paths that are gone.

Like node positions, backdrops are authored on the top layer and every
layer's are shown, a higher layer's taking the place of a lower one's with
the same id. Deleting a backdrop a lower layer made writes ``null`` over
it on the top layer, which hides it.
"""
# Built-in
import copy
import uuid

#: Key in a layer's meta data.
META_KEY = 'backdrops'

POS = 'pos'
SIZE = 'size'
TITLE = 'title'
NOTE = 'note'
COLOR = 'color'

DEFAULT_TITLE = 'Backdrop'
DEFAULT_COLOR = '#4b5468'
DEFAULT_SIZE = (480.0, 320.0)
MIN_SIZE = (160.0, 80.0)

#: (name, hex) offered in the color menu.
PRESET_COLORS = (
    ('Slate', DEFAULT_COLOR),
    ('Steel', '#55595e'),
    ('Ocean', '#2f5578'),
    ('Teal', '#2d6464'),
    ('Forest', '#365e40'),
    ('Olive', '#5a6230'),
    ('Amber', '#7a6024'),
    ('Rust', '#7a4428'),
    ('Berry', '#6e2d4b'),
    ('Plum', '#5a3866'),
)


def new_id():
    return 'bd_' + uuid.uuid4().hex[:8]


def make(pos, size=DEFAULT_SIZE, title=DEFAULT_TITLE, note='', color=None):
    """A new backdrop record."""
    return {POS: [float(pos[0]), float(pos[1])],
            SIZE: [max(float(size[0]), MIN_SIZE[0]),
                   max(float(size[1]), MIN_SIZE[1])],
            TITLE: title,
            NOTE: note,
            COLOR: color or DEFAULT_COLOR}


def clean(record):
    """A copy of a record with every field present and of the right type.

    A layer can be edited by hand, so nothing read from one is trusted.
    Returns None for something that is not a backdrop at all.
    """
    if not isinstance(record, dict):
        return None
    try:
        pos = [float(record[POS][0]), float(record[POS][1])]
    except (KeyError, IndexError, TypeError, ValueError):
        pos = [0.0, 0.0]
    try:
        size = [float(record[SIZE][0]), float(record[SIZE][1])]
    except (KeyError, IndexError, TypeError, ValueError):
        size = list(DEFAULT_SIZE)
    size = [max(size[0], MIN_SIZE[0]), max(size[1], MIN_SIZE[1])]
    title = record.get(TITLE)
    note = record.get(NOTE)
    color = record.get(COLOR)
    return {POS: pos, SIZE: size,
            TITLE: title if isinstance(title, str) else DEFAULT_TITLE,
            NOTE: note if isinstance(note, str) else '',
            COLOR: color if isinstance(color, str) and color
            else DEFAULT_COLOR}


def layer_backdrops(layer):
    """The backdrops one layer itself saves, as stored. Do not edit it.

    :return: {id: record or None}
    """
    meta = getattr(layer, '_input_metadata', None)
    if not isinstance(meta, dict):
        return {}
    found = meta.get(META_KEY)
    if not isinstance(found, dict):
        return {}
    return found


def write(layer, changes):
    """Write records onto one layer.

    :param changes: {id: record, None (hide a lower layer's) or ABSENT}
    """
    meta = getattr(layer, '_input_metadata', None)
    if meta is None:
        meta = {}
        layer._input_metadata = meta
    stored = meta.get(META_KEY)
    if not isinstance(stored, dict):
        stored = {}
    stored = dict(stored)
    for backdrop_id, record in changes.items():
        if record is ABSENT:
            stored.pop(backdrop_id, None)
        else:
            stored[backdrop_id] = copy.deepcopy(record)
    if stored:
        meta[META_KEY] = dict(sorted(stored.items()))
    else:
        meta.pop(META_KEY, None)


class _Absent(object):
    """Not on the layer at all, as opposed to None which hides one."""

    def __repr__(self):
        return 'ABSENT'

    def __deepcopy__(self, memo):
        return self


ABSENT = _Absent()


def merged(layers):
    """Every backdrop the layers show, a higher layer's winning.

    :param layers: top layer first, as a stage holds them
    :return: {id: record}
    """
    shown = {}
    for layer in reversed(list(layers)):
        for backdrop_id, record in layer_backdrops(layer).items():
            if record is None:
                shown.pop(backdrop_id, None)
                continue
            record = clean(record)
            if record is not None:
                shown[backdrop_id] = record
    return shown
