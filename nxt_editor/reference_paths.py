"""How a chosen file is written into a layer as a reference.

Shared by everything that adds a reference from a file someone picked: the
Reference Editor, and the Reference Layer and Create Layer menus. They used
to differ, so the same file came out relative from one and absolute from
the other, and only the relative one survived the graph being moved.
"""
# Builtin
import os


def stored_reference_path(path, layer_dir):
    """The path to store for a file chosen to be referenced.

    Relative to the layer when it sits alongside it, which is what keeps a
    graph portable. Anything else is stored whole: making a path relative
    across drives or out of the layer's folder would be worse than being
    explicit, and would get in the way of NXT_FILE_ROOTS.

    :param path: the file as the file picker handed it back
    :type path: str
    :param layer_dir: folder of the layer that will hold the reference, or
        None when that layer has never been saved
    :type layer_dir: str | None
    :return: forward slashed path, relative when the file is beside the layer
    :rtype: str
    """
    path = path.replace(os.path.sep, '/')
    if not layer_dir:
        return path
    try:
        # Through the symlinks first. A file picker hands back the path the
        # user walked, which can reach the same directory as the layer by
        # another name: /var against /private/var on macOS is the everyday
        # one. Compared as written they look like different places, so a
        # file sitting right beside the layer was stored as an absolute
        # path, which pins the graph to the machine it was added on.
        relative = os.path.relpath(os.path.realpath(path),
                                   os.path.realpath(layer_dir))
    except ValueError:
        # Different drive on Windows.
        return path
    relative = relative.replace(os.path.sep, '/')
    if relative.startswith('..'):
        return path
    return relative
