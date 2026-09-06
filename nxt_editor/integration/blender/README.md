# NXT Blender

`nxt_blender.py` is a single-file Blender add-on. It puts an **NXT** menu in
the top bar, the same place [nxt_maya](../maya/README.md) puts its `nxt`
menu.

If you want the upstream project instead, there is
[nxt-blender](https://github.com/nxt-dev/nxt-blender).

# Installation

1. Edit > Preferences > Add-ons > Install, and pick `nxt_blender.py`.
2. Tick it.

The **NXT** menu appears next to Help. Enabling the add-on does not open
anything on its own.

The add-on finds the repos at `C:/Users/walte/Documents/dev/squarebit`, or
wherever `SB_DEV_ROOT` points.

# Usage

* **Open Editor** — an nxt editor window inside Blender.
* **Close Editor** — closes the windows this session opened.
* **Run Graph...** — pick a `.nxt` and execute it in the current scene.
* **Run Last Graph** — the same graph again.
* **Reload Code** — forget the cached `core` modules.

## Qt

Blender ships no Qt and the editor is a Qt application, so **Open Editor**
needs PySide6. Without it, the console prints the exact `pip` command to
install it beside the repos, and nothing is installed into Blender itself.

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
