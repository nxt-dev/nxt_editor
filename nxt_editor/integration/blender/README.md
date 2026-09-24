# NXT Blender

An **NXT** menu in Blender's top bar, the same place
[nxt_maya](../maya/README.md) puts its `nxt` menu.

If you want the upstream project instead, there is
[nxt-blender](https://github.com/nxt-dev/nxt-blender).

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
the repos under `SB_DEV_ROOT` instead (`C:/Users/walte/Documents/dev/squarebit`
if that is not set), with Qt.py and PySide6 from `nxt_dev_deps` beside them.
`build/make_blender_addon.py` builds the release zip.

# Usage

* **Open Editor** — an nxt editor window inside Blender.
* **Close Editor** — closes the windows this session opened.
* **Run Graph...** — pick a `.nxt` and execute it in the current scene.
* **Run Last Graph** — the same graph again.
* **Reload Code** — forget the cached `core` modules.

## Qt

Blender ships no Qt and the editor is a Qt application, so **Open Editor**
needs PySide6. **Install Qt (PySide6)** downloads it with Blender's own pip,
once, into `~/nxt/deps/py<version>` rather than into Blender, so it survives
Blender updates and needs no write access to Blender's folder. Blender
pauses while it downloads.

For machines without internet access, install it once somewhere shared and
point `NXT_QT_DEPS` at it:

    <blender python> -m pip install --target <shared>/py311 "pyside6-essentials>=6,<6.12"

The folder name is the python version (`py311` for Blender 4.2 to 4.5,
`py313` for 5.x), because PySide6 only loads in the python it was
installed for.

Graphs still run without Qt. Only the editor window needs it, so
**Run Graph** works in any Blender.

## Reload Code is not a convenience

Blender caches imported modules for the life of the session. Editing
`core/blender/*.py` and running a graph again re-runs what was already
imported, which looks exactly like the edit having had no effect. **Run
Graph** reloads first by default, and the menu marks the loaded code
`STALE` when it stops matching the files on disk.

## Editing graphs

The editor edits; it does not have to be open to run anything. Editing can
also be done outside Blender entirely, with the standalone editor under a
Python that has PySide6 — see `templates/templates/blender/launch_nxt.py`.
Graphs whose nodes call `bpy` can only be *executed* in Blender.
