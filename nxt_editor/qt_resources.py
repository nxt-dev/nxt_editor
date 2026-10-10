"""Registers nxt_editor's icons, fonts and styles with Qt, from Python.

Everything the editor refers to as ``:icons/...``, ``:fonts/...`` and so on
is listed in resources/resources.qrc. That used to be compiled into
qresources.py by rcc, either while packaging or on first launch. rcc is a
per-platform binary most hosts don't put on PATH, the file it made was not
in the repository, and a package that went out without it could not load
in Maya at all.

This reads the qrc and the files it lists when nxt_editor is imported, lays
them out in the same format rcc writes, and hands that to Qt, which is all
the compiled module did. Nothing is generated or written, it is the same on
every platform, and a file added to the qrc is picked up on the next
launch.

The format is Qt's resource tree, version 2 (src/corelib/io/qresource.cpp):

    names  per name: uint16 length, uint32 qt_hash, UTF-16BE characters
    data   per file: uint32 length, the bytes
    tree   per node, 22 bytes:
             uint32 name offset, uint16 flags,
             directory: uint32 child count, uint32 first child index
             file:      uint16 territory, uint16 language,
                        uint32 data offset
             uint64 last modified (0 here)

A directory's children sit next to each other in the tree, sorted by the
hash of their names, because Qt binary searches them.
"""
import os
import struct
import sys
import xml.etree.ElementTree as ElementTree

from Qt import QtCore

THIS_DIR = os.path.dirname(os.path.realpath(__file__))
QRC_PATH = os.path.join(THIS_DIR, 'resources', 'resources.qrc')

FORMAT_VERSION = 2
_DIRECTORY = 0x02
_LANGUAGE_C = 1

#: Where what was handed to Qt is kept. Qt reads from those bytes rather
#: than copying them, so they must live as long as they are registered, and
#: that has to survive this module being dropped and imported again, which
#: Blender's Reload Code and a Maya plugin reload both do. A module global
#: would be collected with the old module while Qt still pointed at it.
_KEEP_ON = sys
_KEEP_AS = '_nxt_editor_qt_resources'


def qt_hash(name):
    """The hash Qt stores beside each name, from qHash's qt_hash."""
    h = 0
    for unit in _utf16_units(name):
        h = ((h << 4) + unit) & 0xffffffff
        h ^= (h & 0xf0000000) >> 23
        h &= 0x0fffffff
    return h


def _utf16_units(text):
    raw = text.encode('utf-16-be')
    return struct.unpack('>{}H'.format(len(raw) // 2), raw)


def read_qrc(qrc_path=QRC_PATH):
    """{resource path: file on disk} for every file the qrc lists.

    The resource path is the prefix and the file's path joined, without a
    leading slash: ``icons/icons/nxt.png``.
    """
    base = os.path.dirname(os.path.abspath(qrc_path))
    files = {}
    for resource in ElementTree.parse(qrc_path).getroot().iter('qresource'):
        prefix = resource.get('prefix', '').strip('/')
        for entry in resource.iter('file'):
            rel = entry.text.strip()
            name = entry.get('alias') or rel
            path = '/'.join(p for p in (prefix, name.strip('/')) if p)
            files[path] = os.path.join(base, *rel.split('/'))
    return files


def build(files):
    """Lay files out as Qt's resource tree.

    :param files: {resource path: file on disk}
    :return: (tree, names, data) bytes, as qRegisterResourceData takes them
    """
    root = {}
    for path, source in files.items():
        node = root
        parts = path.split('/')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise ValueError('{} is both a file and a folder'.format(
                    path))
        node[parts[-1]] = source

    names = bytearray()
    name_offsets = {}
    data = bytearray()

    def name_offset(name):
        if name not in name_offsets:
            name_offsets[name] = len(names)
            units = _utf16_units(name)
            names.extend(struct.pack('>HI', len(units), qt_hash(name)))
            names.extend(name.encode('utf-16-be'))
        return name_offsets[name]

    def sorted_children(folder):
        return sorted(folder.items(), key=lambda item: qt_hash(item[0]))

    # Breadth first, so each folder's children are contiguous.
    nodes = [('', root)]
    first_child = {}
    index = 0
    while index < len(nodes):
        name, value = nodes[index]
        if isinstance(value, dict):
            first_child[index] = len(nodes)
            nodes.extend(sorted_children(value))
        index += 1

    tree = bytearray()
    for index, (name, value) in enumerate(nodes):
        offset = name_offset(name) if index else 0
        if isinstance(value, dict):
            tree.extend(struct.pack('>IHII', offset, _DIRECTORY,
                                    len(value), first_child[index]))
        else:
            with open(value, 'rb') as fp:
                content = fp.read()
            data_offset = len(data)
            data.extend(struct.pack('>I', len(content)))
            data.extend(content)
            tree.extend(struct.pack('>IHHHI', offset, 0, 0, _LANGUAGE_C,
                                    data_offset))
        tree.extend(struct.pack('>Q', 0))
    return bytes(tree), bytes(names), bytes(data)


def register(qrc_path=QRC_PATH):
    """Make everything the qrc lists readable through Qt's ``:`` paths.

    Registering again, after a reload, swaps the old resources for new
    ones read from disk.
    """
    built = build(read_qrc(qrc_path))
    unregister()
    if not QtCore.qRegisterResourceData(FORMAT_VERSION, *built):
        raise RuntimeError('Qt refused the resources built from {}'.format(
            qrc_path))
    setattr(_KEEP_ON, _KEEP_AS, built)


def unregister():
    built = getattr(_KEEP_ON, _KEEP_AS, None)
    if built is not None:
        QtCore.qUnregisterResourceData(FORMAT_VERSION, *built)
        delattr(_KEEP_ON, _KEEP_AS)
