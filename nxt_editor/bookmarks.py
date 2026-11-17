"""Camera bookmarks: named places in the graph to jump back to.

A bookmark is only a part of the graph to show, the rectangle the view
had when it was made. It is saved in the top layer's meta data, next to
the node positions and backdrops, under ``bookmarks``, as a list so they
keep the order they were made in::

    "meta_data": {
        "bookmarks": [
            {"name": "Rig build", "rect": [-200.0, -150.0, 1600.0, 900.0]}
        ]
    }

Any version of nxt keeps meta data it does not know about when it saves a
layer, so a graph with bookmarks opens and saves in an older editor
without losing them. Only the top layer's are shown: they belong to the
graph being worked on, not to the layers it references.
"""
# Built-in
import copy

#: Key in a layer's meta data.
META_KEY = 'bookmarks'

NAME = 'name'
RECT = 'rect'

#: How many bookmarks have a shortcut to go to them, Ctrl+1 and on.
SHORTCUT_COUNT = 4


def make(name, rect):
    """A new bookmark.

    :param name: what it is called
    :param rect: (x, y, width, height) in the scene
    """
    return {NAME: str(name),
            RECT: [float(rect[0]), float(rect[1]), float(rect[2]),
                   float(rect[3])]}


def clean(record):
    """A copy of a bookmark with every field present and of the right type,
    or None for something that is not one. A layer can be edited by hand,
    so nothing read from one is trusted."""
    if not isinstance(record, dict):
        return None
    try:
        rect = [float(v) for v in record[RECT]][:4]
    except (KeyError, TypeError, ValueError):
        return None
    if len(rect) != 4 or rect[2] <= 0 or rect[3] <= 0:
        return None
    name = record.get(NAME)
    if not isinstance(name, str) or not name.strip():
        name = 'Bookmark'
    return {NAME: name, RECT: rect}


def layer_bookmarks(layer):
    """The bookmarks a layer saves, cleaned, in order.

    :rtype: list
    """
    meta = getattr(layer, '_input_metadata', None)
    if not isinstance(meta, dict):
        return []
    found = meta.get(META_KEY)
    if not isinstance(found, list):
        return []
    return [r for r in (clean(record) for record in found) if r is not None]


def write(layer, records):
    """Save a layer's bookmarks, all of them, in order. None or an empty
    list takes the key away."""
    meta = getattr(layer, '_input_metadata', None)
    if meta is None:
        meta = {}
        layer._input_metadata = meta
    if records:
        meta[META_KEY] = copy.deepcopy(list(records))
    else:
        meta.pop(META_KEY, None)


def unique_name(records, base='Bookmark'):
    """The first of "Bookmark 1", "Bookmark 2" and so on not yet used."""
    names = set(r[NAME] for r in records)
    number = len(records) + 1
    while '{} {}'.format(base, number) in names:
        number += 1
    return '{} {}'.format(base, number)
