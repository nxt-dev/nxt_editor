# Running Graphs Headless

A graph doesn't need the editor to run. It can run from a shell, a render
farm, a CI job or another graph, with no window open: in plain Python, or
inside Maya, Blender or Unreal without their UI.

| Where | Run it with | Needs Qt |
| :---- | :---------- | :------- |
| Python | `python -m nxt.cli exec` | No |
| Maya | `mayapy run_maya_graph.py` | No |
| Blender | `blender --background --python run_blender_graph.py` | No |
| Unreal | `UnrealEditor-Cmd -run=pythonscript -script=run_unreal_graph.py` | No |

The Maya, Blender and Unreal runners all take the same arguments:

| Argument | Meaning |
| :------- | :------ |
| `-g`, `--graph_path` | The graph to run. Required. |
| `-s`, `--start_node` | The node to start from, such as `/build_rig`. Without it the graph's start point is used. |
| `-p`, `--parameters` | Values to set before the graph runs, as a JSON dictionary or the path to a JSON file. Keys are attribute paths such as `/node.attr`. A `/node._enabled` key set to `true` or `false` enables or disables that node for this run. |

Each runner exits with **0** when the graph ran and with an error code when
it failed, with the error printed, so a script or a farm can tell. A graph
that runs in a host can use that host's API, such as `maya.cmds` or `bpy`,
in its nodes. Graphs that do can only be *run* in that host, but they can be
*edited* anywhere, including the standalone editor.

!!! tip "Passing parameters"
    A JSON file is the easiest way to pass parameters, as it needs no
    quoting: `-p C:/jobs/shot_010.json`. Inline JSON needs its quotes
    escaped for your shell, for example `-p "{\"/.name\": \"test\"}"` in
    `cmd` or PowerShell.

## Python

The nxt core command line runs a graph in the Python it is installed in.
Use it for graphs that need no host.

```
python -m nxt.cli exec path/to/graph.nxt
python -m nxt.cli exec path/to/graph.nxt -s /start_node
python -m nxt.cli exec path/to/graph.nxt -p /node.attr 5 /node.name test
python -m nxt.cli exec path/to/graph.nxt -p path/to/parameters.json
```

Here `-p` takes attribute and value pairs, or a single JSON file.

## Maya

`run_maya_graph.py` runs a graph in a headless Maya session
(`maya.standalone`). It is at `nxt_editor/integration/maya/run_maya_graph.py`,
both in the Maya module and in a pip install of nxt-editor. Run it with Maya's
own python, `mayapy`, from Maya's `bin` folder:

```
mayapy run_maya_graph.py -g path/to/graph.nxt
mayapy run_maya_graph.py -g path/to/graph.nxt -s /start_node
mayapy run_maya_graph.py -g path/to/graph.nxt -p path/to/parameters.json
```

nxt has to be importable from `mayapy`, which it is when the nxt Maya module
is installed. The session starts with an empty scene; open or save files in
the graph's nodes.

## Blender

`run_blender_graph.py` runs a graph in Blender in the background. Blender's
own arguments come first, then the runner's after `--`:

```
blender --background --python run_blender_graph.py -- -g path/to/graph.nxt
blender --background scene.blend --python run_blender_graph.py -- -g graph.nxt -s /start_node
blender --background --python run_blender_graph.py -- -g graph.nxt -p params.json
```

Give a `.blend` file before `--python` to run the graph with it open. Nothing
is saved for you; save in the graph's nodes if you need to.

The runner is inside the installed add-on, at
`nxt_blender/lib/nxt_editor/integration/blender/run_blender_graph.py`. On
Windows, an add-on installed from disk is under
`%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons`. The runner
finds nxt from there itself, so the add-on doesn't have to be enabled for a
background run, and no Qt is needed. It is also at
`nxt_editor/integration/blender/` in a pip install of nxt-editor.

## Unreal

`run_unreal_graph.py` runs a graph in Unreal's command line editor, as a
Python commandlet. Run it in a project that has the nxt plugin and the
**Python Editor Script Plugin** enabled:

```
UnrealEditor-Cmd.exe MyProject.uproject -run=pythonscript -script="run_unreal_graph.py -g C:/graphs/build.nxt" -unattended -nosplash -nullrhi
```

`UnrealEditor-Cmd.exe` is in the engine's `Engine/Binaries/Win64` folder.
Unreal finds the runner by name in the plugin's `Content/Python` folder.
`-nullrhi` runs without a GPU, which most graphs don't need; leave it out if
yours renders.

!!! warning "Paths with spaces"
    Unreal splits `-script` at every space and keeps any quotes, so a path
    or parameter with a space in it can't go there. Leave the arguments out
    of `-script` and put them in the `NXT_RUN_GRAPH_ARGS` environment
    variable as a JSON list instead:

    ```
    set NXT_RUN_GRAPH_ARGS=["-g", "C:/my graphs/build.nxt", "-s", "/build"]
    UnrealEditor-Cmd.exe MyProject.uproject -run=pythonscript -script=run_unreal_graph.py -unattended -nosplash -nullrhi
    ```

    The `/_unreal_headless_graph` node always passes its arguments this way.

## From another graph

To start a headless run from inside a graph, reference the builtin
`sub_graphs.nxt` graph (**File > Reference Builtin Graph**) and instance one
of its nodes. Each starts the host as a separate process and runs the graph
in `_graph_path`.

| Node | Runs the graph in |
| :--- | :---------------- |
| `/_maya_standalone_graph` | Maya standalone |
| `/_blender_background_graph` | Blender, in the background |
| `/_unreal_headless_graph` | Unreal's command line editor |

All three share these attributes:

| Attribute | Meaning |
| :-------- | :------ |
| `_graph_path` | The graph to run. |
| `_parameters` | A dictionary of values to set before it runs, keyed by attribute path. |
| `_start_node` | The node to start from, written as a string, such as `'/build_rig'`. Leave it as `None` to use the graph's own start point. |
| `_wait` | Turn it on to make the build wait for the host to finish before it continues. |

And each has its own for finding the host:

| Node | Attributes |
| :--- | :--------- |
| `/_maya_standalone_graph` | `_maya_version`, or `_MAYA_LOCATION` or `_mayapy_exe` when Maya isn't in the default Windows location. |
| `/_blender_background_graph` | `_blender_version`, or `_BLENDER_LOCATION` or `_blender_exe` when Blender isn't in the default Windows location. `_blend_file` opens a `.blend` first. |
| `/_unreal_headless_graph` | `_project`, the `.uproject` to run in. `_unreal_version`, or `_UNREAL_LOCATION` or `_unreal_cmd_exe` when the engine isn't in the default Windows location. `_unreal_args` holds Unreal's own arguments. |

`_graph_path` and `_start_node` are used as python, so write them as strings,
for example `'C:/graphs/build.nxt'`.

## Troubleshooting

- **The graph can't find nxt.** Maya needs the nxt Maya module installed.
  Blender's runner finds nxt from the add-on folder it is in, so run the copy
  inside the add-on. Unreal needs the nxt plugin enabled in the project you
  pass.
- **A start node isn't found in Git Bash.** Git Bash turns arguments that
  start with `/` into Windows paths, so `/build` arrives as
  `C:/Program Files/Git/build`. Run the command with `MSYS_NO_PATHCONV=1`
  in front, or from `cmd` or PowerShell.
- **A path in Chinese, Cyrillic or another script turns into `?`.**
  `mayapy` passes its arguments in the system's code page, so on a Western
  Windows any character that code page lacks arrives as `?`. Put the
  arguments in the `NXT_RUN_GRAPH_ARGS` environment variable as a JSON list
  instead, as for Unreal; every runner reads it when its own command line
  has no arguments. The graph itself can be in any language either way.
- **The exit code is 0 but nothing happened.** Check the graph's start
  point, or pass `-s`. Nodes that aren't reached from where the run starts
  don't run.
