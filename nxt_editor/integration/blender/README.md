# NXT Blender

An **NXT** menu in Blender's top bar, the same place
[nxt_maya](../maya/README.md) puts its `nxt` menu.

There is also the separate
[nxt-blender](https://github.com/nxt-dev/nxt-blender) project.

# Installation

1. Edit > Preferences > Add-ons > Install from Disk, and pick
   `nxt_blender.zip` from the release.
2. Tick it.
3. The first time, choose **NXT > Install Qt (PySide6)**. See [Qt](#qt).

The **NXT** menu appears next to Help. Enabling the add-on does not open
anything on its own.

The add-on carries its own nxt, nxt_editor and Qt.py, so nothing else has
to be installed or put on a path.

## Developing it

Installed on its own, as `nxt_blender.py`, it has nothing bundled and uses
whatever `nxt` and `nxt_editor` Blender's python can already import, such as
a `pip install nxt-editor` into it. Without one it has nothing to run, and
says so. `build/make_blender_addon.py` builds the release zip.

# Usage

* **Open Editor** — an nxt editor window inside Blender.
* **Close Editor** — closes the windows this session opened.
* **Run Graph...** — pick a `.nxt` and execute it in the current scene.
* **Run Last Graph** — the same graph again.
* **Reload Code** — forget the cached `nxt` modules.

## Qt

Blender ships no Qt and the editor is a Qt application, so **Open Editor**
needs PySide6. **Install Qt (PySide6)** downloads it with Blender's own pip,
once, into `~/nxt/deps/py<version>` rather than into Blender, so it survives
Blender updates and needs no write access to Blender's folder. Blender
pauses while it downloads.

For machines without internet access, install it once somewhere shared and
point `NXT_QT_DEPS` at it:

    <blender 5 python> -m pip install --target <shared>/py313 "pyside6-essentials>=6,<6.12"
    <blender 4 python> -m pip install --target <shared>/py311-crt14.29 "pyside6-essentials>=6,<6.11"

The folder is named for the python version, because PySide6 only loads in
the python it was installed for: `py313` for Blender 5. Blender 4.2 to 4.5
on Windows also ship an older Microsoft C++ runtime, which PySide6 6.11
crashes on as soon as Qt loads, so they get PySide6 6.10 in a folder of
their own, `py311-crt14.29`. Install Qt picks the right one by itself; the
names only matter when installing by hand.

Graphs still run without Qt. Only the editor window needs it, so
**Run Graph** works in any Blender.

## Reload Code is not a convenience

Blender caches imported modules for the life of the session. Updating nxt
and running a graph again re-runs the nxt that was already imported, which
looks like a graph problem rather than a stale import. **Run Graph** reloads
first by default.

## Editing graphs

The editor edits; it does not have to be open to run anything. Editing can
also be done outside Blender entirely, with the standalone editor under a
Python that has PySide6.
Graphs whose nodes call `bpy` can only be *executed* in Blender.
