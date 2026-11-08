# Requirements

nxt comes in two packages:

| Package | What it is | Python |
| :------ | :--------- | :----- |
| [nxt-core](https://pypi.org/project/nxt-core/) | The graph engine. Loads, composites and executes graphs, with no UI. | 3.7 to 3.14 |
| [nxt-editor](https://pypi.org/project/nxt-editor/) | The visual editor. Installs nxt-core with it. | 3.9 to 3.14, with PySide6 6.x below 6.12 |

The editor uses [Qt.py](https://github.com/mottosso/Qt.py) on top of
PySide6, both of which pip installs for you. The same release runs on
Windows, macOS and Linux; nothing is compiled per platform.

!!! note "PySide6 6.12"
    nxt-editor asks pip for a PySide6 below 6.12, because the editor has not
    been tested on 6.12 yet. If another package
    in the same environment needs PySide6 6.12 or newer, give nxt an
    environment of its own.

We strongly recommend installing into a Python
[virtual environment](https://docs.python.org/3/library/venv.html).

# Standalone Installation

To install the latest release from [PyPI](https://pypi.org/project/nxt-editor/):

- Install
    - `pip install nxt-editor`
    - Optionally, for richer code completion:
      `pip install nxt-editor[completion]`. This adds
      [jedi](https://github.com/davidhalter/jedi), which the
      [Python Analysis](reference.md#python-analysis-with-jedi) completion
      source uses. The editor works the same without it.
- Launch the editor
    - `nxt ui`, or `nxt ui path/to/graph.nxt` to open a graph
- Update
    - `pip install -U nxt-editor`

If you only need to run graphs, without the editor, install the core on its
own with `pip install nxt-core`. Graphs can then be run from the command
line with `nxt exec path/to/graph.nxt`, optionally with `-s /start/node`.

To install a specific version, or the latest code, directly from GitHub:

```
pip install git+https://github.com/nxt-dev/nxt.git@{ tag name }
pip install git+https://github.com/nxt-dev/nxt_editor.git@{ tag name }
```

Omit `@{ tag name }` to get the latest from the `release` branch.

---

# Host Applications

Each supported host gets a zip on the
[latest nxt_editor release](https://github.com/nxt-dev/nxt_editor/releases/latest).
Each zip also contains a `README.md` with these same steps.

| Host | Versions | Qt |
| :--- | :------- | :- |
| [Maya](#maya) | 2025, 2026, 2027 | Ships with Maya |
| [Unreal](#unreal) | 5.4 to 5.8 | Installed once from the nxt menu |
| [Blender](#blender) | 4.2 and newer | Installed once from the NXT menu |

## Maya

The Maya plugin is a Maya module folder that carries nxt, nxt_editor and
Qt.py. Maya ships its own PySide6, so there is nothing else to install.

### Automated install

1. Place the nxt module folder somewhere you would like to keep it, and that
   will be easy to find when you are ready to install a newer version.
2. Drag the file `drag_into_maya.py` from that folder into the Maya viewport.
    - A file browser appears. Select the folder you would like the nxt module
      file (`nxt.mod`) to go in. Make sure the location you choose is on your
      Maya modules path. This replaces any existing `nxt.mod` in that folder.
      If you are not sure, the default should work.
3. Restart Maya.
4. `nxt_maya.py` is now available to load in the Plug-in Manager.

!!! warning "Keep the folder"
    Do not delete the module folder after installing. Maya loads nxt from it.
    To update nxt, replace the folder's contents with the newer release and
    restart Maya.

### By hand

If you are familiar with Maya modules: the module folder contains an example
`nxt.mod`. Fill in the module path with the path to the extracted module
folder and put the `nxt.mod` somewhere on your Maya modules path.

### Usage

When the plugin is loaded there is an **nxt** menu in Maya's main menu bar.
Choose **Open Editor** to get started.

The plugin also adds an `nxt_ui` command, for shelf buttons and scripts.
There is one editor at a time: when an editor is already open, `nxt_ui`
uses it rather than opening a second one.

| Flag | What it does |
| :--- | :----------- |
| *(none)* | Opens the editor, or, when one is already open, brings it to the front, restoring it if it was minimised. |
| `-path`, `-p` | Opens a graph, as a new tab of the open editor or in a new editor. Can be given more than once. |
| `-reload`, `-r` | Closes the editor and opens a fresh one. Closing asks about unsaved changes as usual; if you cancel, the reload stops with a warning and the editor stays open. |
| `-close`, `-c` | Closes the editor. |

In Python:

```python
from maya import cmds

cmds.nxt_ui()
cmds.nxt_ui(path=['C:/graphs/build.nxt', 'C:/graphs/publish.nxt'])
cmds.nxt_ui(reload=True)
cmds.nxt_ui(close=True)
```

In MEL:

```
nxt_ui;
nxt_ui -p "C:/graphs/build.nxt" -p "C:/graphs/publish.nxt";
nxt_ui -reload;
nxt_ui -close;
```

!!! note "Older scripts"
    Before these flags, `nxt_ui` took `close` (and `reload`) as a plain
    argument: `cmds.nxt_ui('close')`. That still works, but prints a warning
    that it is deprecated. Use `cmds.nxt_ui(close=True)` and
    `cmds.nxt_ui(reload=True)` instead.

### Running a graph in Maya standalone

nxt_editor ships a small command line script, `run_maya_graph.py`, that runs
a graph inside a headless Maya session (`maya.standalone`). It lives at
`nxt_editor/integration/maya/run_maya_graph.py`, both in the Maya module
and in a pip install of nxt-editor. Run it with Maya's own python,
`mayapy`, which is in Maya's `bin` folder:

```
mayapy run_maya_graph.py -g path/to/graph.nxt
mayapy run_maya_graph.py -g path/to/graph.nxt -s /start_node
mayapy run_maya_graph.py -g path/to/graph.nxt -p "{\"/.name\": \"test\"}"
mayapy run_maya_graph.py -g path/to/graph.nxt -p path/to/parameters.json
```

| Argument | Meaning |
| :------- | :------ |
| `-g`, `--graph_path` | The graph to run. Required. |
| `-s`, `--start_node` | The node to start from. Without it the graph's start point is used. |
| `-p`, `--parameters` | Values to set before the graph runs, as a JSON dictionary or the path to a JSON file. Keys are attribute paths such as `/node.attr`. A `/node._enabled` key set to `true` or `false` enables or disables that node for this run. |

The script needs nxt importable from `mayapy`, which it is when the nxt
Maya module is installed.

To launch it from inside another graph, reference the builtin
`sub_graphs.nxt` graph (**File > Reference Builtin Graph**) and instance its
`/_maya_standalone_graph` node. Set `_graph_path` to the graph to run,
`_maya_version` (or `_MAYA_LOCATION` / `_mayapy_exe` if Maya is not installed
in the default Windows location) and, if needed, `_parameters` and
`_start_node`. Turn on `_wait` to make the build wait for Maya to finish
before it continues.

`_start_node` is passed to `run_maya_graph.py` as `-s`. Its value is used as
python, so write the node path as a string, for example `'/build_rig'`
(`_graph_path` is written the same way). Leave it as `None` to run from the
graph's own start point.

## Unreal

The Unreal plugin carries nxt, nxt_editor and Qt.py in its `Content/Python`
folder, so it runs the nxt it was released with and does not install nxt
from PyPI. It is experimental: save early, save often.

1. Move the plugin folder into either your project's or the engine's
   `Plugins` folder.
2. Make sure the **Python Editor Script Plugin** is enabled.
3. Enable the nxt plugin in the plugin browser and restart the editor.
4. The first time, choose **nxt > Install Qt (PySide6)**. Unreal ships no Qt,
   so this downloads PySide6 with the engine's own pip. See
   [Qt for Blender and Unreal](#qt-for-blender-and-unreal).

After that, the **nxt** menu in the main menu bar has **Open Editor**. The
editor window is parented to the Unreal editor and stays responsive while
Unreal runs. If a menu command fails, the error is logged and shown rather
than taking the Unreal editor down.

To update, replace the plugin folder with the one from a newer release. If
an older version of the plugin pip installed `nxt-editor` into the engine,
the bundled copy is used ahead of it; you can remove the old one with
`<engine python> -m pip uninstall nxt-editor nxt-core`. The engine's python
is under `Engine/Binaries/ThirdParty/Python3`.

## Blender

The Blender add-on carries nxt, nxt_editor and Qt.py, so nothing else has to
be installed or put on a path.

1. In Blender, open **Edit > Preferences > Add-ons**, choose
   **Install from Disk**, and pick `nxt_blender.zip` from the release.
2. Tick the add-on to enable it.
3. The first time, choose **NXT > Install Qt (PySide6)**. See
   [Qt for Blender and Unreal](#qt-for-blender-and-unreal).

The **NXT** menu appears in Blender's top bar, next to **Help**. Enabling the
add-on does not open anything on its own.

| Menu item | What it does |
| :-------- | :----------- |
| Open Editor | Opens an nxt editor window inside Blender. |
| Close Editor | Closes the editor windows this session opened. |
| Install Qt (PySide6) | Only shown while Qt is missing. Installs PySide6 for this Blender. |
| Run Graph... | Picks a `.nxt` file and runs it in the current scene, without opening the editor. |
| Run Last Graph | Runs the same graph again. |
| Reload Code | Forgets the nxt modules Blender has already imported, so the next run uses the files on disk. |

Only the editor window needs Qt. **Run Graph** works in any Blender, even
before Qt is installed, and in background (`--background`) sessions an error
from a graph is printed rather than shown in a dialog.

!!! note "Why Reload Code matters"
    Blender keeps imported modules for the whole session. If you update nxt,
    or code your graph imports, and run a graph again, Blender runs what it
    had already imported, which looks like your change had no effect.
    **Run Graph** reloads first by default (the **Reload code first** option
    in its file browser), and **Run Last Graph** always does.

Graphs whose nodes use `bpy` can only be *run* in Blender, but they can be
*edited* anywhere, including the standalone editor.

## Qt for Blender and Unreal

Blender and Unreal ship no Qt, and the nxt editor is a Qt application, so
both menus offer **Install Qt (PySide6)**. It uses the host's own pip to
install PySide6 once, into a folder outside the host:

```
~/nxt/deps/py<python version>
```

for example `~/nxt/deps/py311` for Unreal and `~/nxt/deps/py313` for
Blender 5. The folder is named for the python version because PySide6 only
loads in the python it was installed for. Keeping it outside the host means
it survives host updates and needs no write access to the host's install
folder. The host pauses while PySide6 downloads.

On Windows, Blender 4.2 to 4.5 ship an older Microsoft C++ runtime that the
newest PySide6 crashes on, so they get PySide6 6.10 in a folder of its own,
`py311-crt14.29`. Install Qt picks the right one by itself; the folder names
only matter when installing by hand.

!!! note "Studio installs and machines without internet access"
    Set the `NXT_QT_DEPS` environment variable to a shared folder, and nxt
    looks for (and installs) PySide6 under it instead of `~/nxt/deps`.
    Install it there once with each host's python:

        <unreal python>    -m pip install --target <shared>/py311 "pyside6-essentials>=6,<6.12"
        <blender 5 python> -m pip install --target <shared>/py313 "pyside6-essentials>=6,<6.12"
        <blender 4 python> -m pip install --target <shared>/py311-crt14.29 "pyside6-essentials>=6,<6.11"

    If `NXT_USER_DIR` is set, the default folder is `$NXT_USER_DIR/deps`
    rather than `~/nxt/deps`.

## Other hosts

nxt can run inside any host with a Python 3 interpreter that nxt-core
supports. The editor additionally needs PySide6. Planned host plugins
include Houdini and Nuke.

---

# Developer Installation

See our [contributing documentation](https://github.com/nxt-dev/nxt_editor/blob/release/CONTRIBUTING.md).

### Bootstrapping nxt in another host

For a host without a plugin, you can open the editor from the host's own
python, as long as nxt, nxt_editor and Qt.py are importable there and the
host provides PySide6.

    import sys
    import os
    # Path to the folder containing the nxt and nxt_editor packages,
    # for example a virtual environment's site-packages.
    NXT_PATH = os.path.expanduser('~/nxt_env/Lib/site-packages')
    # Default file to open, can be None
    LAUNCH_FILE = None
    if NXT_PATH not in sys.path:
        sys.path.append(NXT_PATH)
    from Qt import QtCore
    import nxt_editor.main_window
    instance = nxt_editor.main_window.MainWindow(filepath=LAUNCH_FILE)
    if sys.platform == 'win32':
        instance.setWindowFlags(QtCore.Qt.Window)
    instance.show()
    # To force close the instance run this line:
    # instance.close()

!!! warning
    The packages must have been installed for the same Python version as the
    host's python (for example 3.11), or compiled dependencies will fail to
    import.

##### Optional window attach

To attach to the main window in Nuke

    from Qt import QtWidgets

    def _nuke_main_window():
        """Returns Nuke's main window"""
        for obj in QtWidgets.QApplication.topLevelWidgets():
            if (obj.inherits('QMainWindow') and
                    obj.metaObject().className() == 'Foundry::UI::DockMainWindow'):
                return obj
        else:
            raise RuntimeError('Could not find DockMainWindow instance')
    nuke_window = _nuke_main_window()
    instance = nxt_editor.main_window.MainWindow(parent=nuke_window, filepath=LAUNCH_FILE)

To attach to the main window in Houdini

    from Qt import QtCore
    instance = nxt_editor.main_window.MainWindow()
    instance.setParent(hou.qt.mainWindow(), QtCore.Qt.Window)
