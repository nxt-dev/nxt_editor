# What's New

This page summarises what is new in recent releases of **nxt_editor**, and
in **nxt_core 0.21**.
Each item links to the part of the docs that explains it in full.

## Unreleased

**New**
- `NXT_NO_MENU=1` leaves nxt's own menu out of Maya, Blender and Unreal, for
  pipelines that open the editor from their own menu. See
  [Leaving the nxt menu out](install.md#leaving-the-nxt-menu-out).
- [Env files](extensions.md#env-files) set environment variables when nxt
  starts, in the editor, in a host and in a headless run, from your own
  file, the site's, and project files kept under version control.
  **Options > Environment Variables...** edits them as a table.
- A file picked to reference that sits under one of your `NXT_FILE_ROOTS`
  is stored relative to that root, and one in a folder an env file variable
  names is stored from that variable, so the graph loads on other machines.
  This changes what is stored for anyone with `NXT_FILE_ROOTS` set. See
  [How references are found](reference.md#how-references-are-found).
- An eye at the end of each row in the Layer Manager, and **Hide In
  Graph** on a layer's menu, hide that layer's nodes, lines and backdrops
  in the graph while it still composites and runs, for example a library
  layer of nodes that are only there to be instanced. See
  [Hiding a layer in the graph](reference.md#hiding-a-layer-in-the-graph).

**Fixed**
- The code editor's completion list opens under the line, with its names
  starting where the word being completed starts. It was drawn to the left
  by the width of the line numbers, and over the bottom of the line.

## nxt_editor 4.12.0

**New**
- **Align and distribute** nodes and the points on their lines: Align
  Left, Center, Right, Top, Middle and Bottom, and Distribute
  Horizontally and Vertically, from **Align** in the right click menu, a
  new Align button on the toolbar, or `Shift+W`/`A`/`S`/`D` and
  `Alt+Shift+W`/`S`/`A`/`D`. See
  [Aligning nodes and points](reference.md#aligning-nodes-and-points).
- **Points turn with the line**: a curved line runs smoothly through each
  point in the direction it is going, instead of looping back round it.
  See [Lines between nodes](reference.md#lines-between-nodes).
- **Select All** has an icon on the toolbar, and its tooltip shows its
  shortcut.

**Fixes**
- Docked panel tabs no longer shift over and cut their names short when
  hovered; only their outline changes color.

## nxt_editor 4.11.0

**New**
- The Instance View marks the node it is drawn from with a target at the end
  of its name, the same target as on **Follow Selection**. It moves to
  whichever node you show, from the graph, the Outliner, **Show Selected** or
  a double click in the view.

## nxt_editor 4.10.1

**Fixed**
- Only proxy nodes are striped again, as before 4.10.0: nodes made by an
  instance that have nothing of their own yet. An instance, or a node that
  overrides anything its instance gives it, looks like any other node, in the
  graph and the Outliner.

## nxt_editor 4.10.0

**New**
- **Instance View.** **Window > Instance View** shows a node's instance
  connections and nothing else: what it instances from, back to the first
  source, and every node that instances it. Nodes are grey cards with their
  layer colors along the top. **Follow Selection** shows whichever node you
  select, **Show Selected** shows it on demand, and **Sync Selection**
  selects and frames the nodes you pick in it in the graph and the Outliner.
- **Find nodes by name.** The Outliner's search and **Find Node** (`/`) work
  like the filters in mix: `*` for anything, commas between names, and a `/`
  to match the whole path. Find Node opens empty, lists the nodes it finds,
  and Enter selects and frames all of them. Searches run once you stop
  typing, or on Enter.
- **Any layer color, shown your way.** **Change Color** picks from the full
  spectrum, and the layer keeps exactly the color you pick. **View > Options
  > Layer Color View** sets how colors are shown to you: as they are (the
  default), darker where too light for the white names on them, or every
  hue at one lightness and chroma that you set. It is saved as your
  preference and never changes anyone's colors.
- **Instanced nodes are striped** in the graph and the Outliner.
- **Run buttons with icons.** Execute Selected, Execute From Selected and
  Execute Hierarchy have their own icons and tooltips on the toolbar.
- Shift click a build group's arrow in the Outliner, or Shift double click
  its heading, to collapse or expand every node in it.

**Fixed**
- The Property Editor could crash the editor with **Neutral Property Text**
  turned on.

## nxt_editor 4.9.0

**New**
- **Colors white text reads on.** Layer and backdrop colors are kept dark
  enough for their white names to read. **Change Color** has a new picker
  that only offers those colors: the layer palette, a field of hues, and a
  shade bar that stops before a color gets too light. Brighter colors
  saved in older graphs show as the nearest readable color, keeping their
  hue.
- **The Outliner works like the graph.** The node hotkeys work in it
  (**D**, **N**, **Del**, **S**, **B**, **X** and so on), double click or
  the arrow collapses a node, Shift does everything below it, and Ctrl
  double click or **F2** renames it in its row. Start, skip and break
  points show on their rows, and right clicking below the rows adds or
  pastes a node. Rows are larger, and hovering or selecting one outlines
  it, as in the graph.
- **The Build View outlines too.** The selected node has an amber edge and
  the one under the mouse a white edge, and the node that runs next stays
  red.
- **Neutral Property Text.** Turn on **View > Options > Neutral Property
  Text** to show the Property Editor's attributes in text that reads on
  any layer color: bright and bold for a value set on the node,
  and a softer grey for one it inherits. Each row's header is filled with
  its layer's color, and stays in view as you scroll. Off by default.
- **Faster on big graphs.** Opening a large graph takes about half as long,
  mostly from building the Workflow Tools faster. Moving and panning are
  smoother, toggling a break or skip point is immediate, and a hidden graph
  or Outliner does no work until it is shown again.

**Changed**
- Node names are always white, on every layer color.
- The layer chips on a node are wider and sit side by side.

**Fixed**
- Break and skip points work on a graph that has not been saved yet.
- Collapsing a node in the Outliner and the graph always agree. Selecting a
  node inside a collapsed one no longer opens its row, which made the next
  click expand it instead.
- A node collapsed by a lower layer expands on the first click.
- Renaming a node opens the box over the node rather than above it.
- The checkboxes in the list of layers to save on close always show.

## nxt_editor 4.8.0

**New**
- **A new look.** Neutral dark greys, so the only color on screen is your
  layers'. Nodes are rounded cards in their layer's color with a soft
  shadow and a clearer font, and a selected node has an amber outline.
  Panels, menus, tabs and the toolbar are restyled to match. Text is the
  same size on every platform and in every host.
- **Outliner.** **Window > Outliner** lists the graph's nodes as a tree,
  grouped by the start point whose build runs them, with a section for
  the nodes in no build. Rows are colored like their nodes, with a chip
  for each other layer the node is on. A search box finds a node at any
  depth by typing its name (regular expressions work too), and a right
  click gives the same menu as the node in the graph.
- **Hide the graph.** **Window > Stage View** hides the node graph to give
  the space to the docks, and shows it again. The editor remembers your
  choice.
- **Curved lines.** **View > Curved Connections** draws the lines between
  nodes as curves. It is saved with the graph, and remembered as your
  preference for graphs that have not saved a choice.
- **Points on lines.** Double click a line to add a point, then drag it to
  route the line around other nodes. Points can be box selected, stay
  visible at any zoom, and are saved with the layer.
- **Break a connection.** Right click a line, a point on it, or a plug and
  pick **Break Connection**. The exec input or attribute is left empty
  rather than keeping the connected value.

**Fixed**
- Making a layer under a new, unsaved layer no longer fails to draw the
  graph with `'NoneType' object has no attribute '_source_layer'`.
- Layers show their colors again in the list of layers to save on close.

## nxt_editor 4.6.1

**New**
- **Backdrops.** Press **C**, or pick **Add Backdrop** in the graph's right
  click menu, to put a colored box behind a group of nodes. With nodes
  selected it fits around them. Drag its header to move it and everything
  inside it, or Ctrl+drag to move just the backdrop. Double click the header
  to give it a title, a note in its top left corner, and a color. Backdrops
  can sit inside each other, show on the mini map, and are saved with the
  layer.
- **Sign in with Codex.** The AI Assistant can use your ChatGPT account
  through Codex, the same way it uses Claude Code. Install Codex, then press
  **Sign in with Codex** in **Options > AI Assistant**.
- **More than one ChatGPT account.** Each account and workspace keeps its
  own sign in. **Switch Account** lists the ones used before, plus
  **Another Account or Workspace...**

**Fixed**
- **Sign in with ChatGPT finishes.** It could fail with `invalid_grant`, or
  turn away an account in an organization's workspace as "only available to
  members of its workspace". Errors now say what went wrong and what to do.
- **API keys save on Linux without a keyring.** With no system keyring,
  keys and sign ins are kept in `~/nxt/ai_sign_ins.json`, readable only by
  you.
- **Child nodes move with their parent** again when it is dragged.
- **Closing the editor no longer crashes** on the way out.

**Notes**
- Carries nxt_core 0.21.2.

## nxt_editor 4.5.3

**New**
- **AI Assistant.** A panel to chat with Claude, OpenAI, Grok or a local
  model about the open graph. Turn it on in **Options > AI Assistant**, then
  open it from **Window > AI Assistant**. It looks over, searches, changes
  and runs the graph, and lists each step it takes. All of its changes in
  one reply are one undo. Chats are kept, to go back to, pin or delete. It
  can read code on your computer (it asks first outside the graph's folder),
  look into the modules a graph imports without running them, and remember
  notes. Nothing is sent anywhere until you ask it something.
- **Show a layer's file.** Right click a layer and pick **Show in Explorer**
  (Windows), **Reveal in Finder** (Mac) or **Show in File Manager** (Linux).

**Fixed**
- **The editor looks the same in Maya as it does on its own.** The workflow
  buttons, tabs and panels lost their styling in a host.
- **Every change to a layer shows on it as it happens.** Taking something
  off a node now marks the layer as changed straight away.
- **Stop puts the build back.** Stopping no longer empties the build list or
  looks like it is still running, and in Maya the next node no longer runs
  after Stop.
- **Saving a layer no longer fails on a damaged editor cache** ("Ran out of
  input").
- **Turning a node on or off shows straight away**, without a recomp.

**Notes**
- Carries nxt_core 0.21.2.

## nxt_editor 4.4.3

**New**
- **Code completion knows your graph.** While typing in the code editor you
  get node attributes, `${}` tokens and the modules a compute can import.
  With jedi installed it also knows what a call returns.
- **Reference Editor.** See and change the layers a graph references, in one
  place.
- **Hover a `${}` token to see its value, Ctrl+click it to go to its node.**
- **Brackets and quotes close themselves** in the code editor.
- **Double click a dock tab to float it.** **View > Reset Layout** puts every
  dock back where it started.
- **Save As into a new tab writes a copy** and leaves the original open and
  unchanged.
- **The Code Editor Data State Overlay is under View > Options**, and the
  editor remembers whether it is on.

**Fixed**
- **Maya's own windows keep their fonts.** Opening the editor no longer
  changes the font of Maya's windows, such as the node editor's tab search.
- **References keep working after Save As to another folder.** A reference
  relative to the graph is rewritten so it still points at the same file.

**Notes**
- Carries nxt_core 0.21.1.

## nxt_editor 4.4.1

- **Maya's fonts are left alone again.** Opening the editor in Maya no
  longer changes the font of Maya's own windows, such as the node editor's
  tab search.
- **Code Editor Data State Overlay** is now under **View > Options**, and
  the editor remembers whether you turned it on or off.

![The nxt editor with the mini map in the corner of the graph](images/editor_overview.png)

## Editor

### A code editor that works like a code editor

The code editor picked up the tools you would expect from a text editor. All
of them only apply while the code editor has focus, and all of them can be
rebound in the [Hotkey Editor](hotkeys.md#code-editor).

- **Find and replace** (`Ctrl+F` / `Ctrl+H`) floats over the top right of the
  code, with a match count, next and previous (`F3` / `Shift+F3`) and toggles
  for match case, whole word and regular expressions.
- **Go to line** (`Ctrl+G`) previews the line as you type, and `Esc` puts the
  cursor back where it was.
- **Line editing**: duplicate (`Ctrl+Shift+D`), move (`Alt+Up` / `Alt+Down`)
  and delete (`Ctrl+Shift+K`) lines, and expand the selection from word to
  line to everything (`Ctrl+D`).
- **Highlighting** of every use of the word under the cursor, and of the
  bracket next to the cursor and its partner.
- **Completion** (`Ctrl+Space`) offers python builtins, names from the modules
  the compute imports, the node's attributes and `${}` tokens, and words
  already in the compute. Each source can be switched on or off under
  **Options > Autocomplete**, along with suggestions while you type.
- **Auto-pairing**: typing `(`, `[`, `{`, `"` or `'` adds the closing
  character, typing a closer that is already there steps over it, and
  typing an opener with text selected wraps the selection.
- **Syntax highlighting** colours every match on a line. Before, a line
  with two tokens or two strings only had the first one coloured.

See [Code Editor](reference.md#code-editor).

### Tokens you can hover and follow

![Hovering a token shows its value](images/code_editor_token_hover.png)

In Raw View (`Q`), hover a `${}` token in the code editor to see what it
resolves to, and `Ctrl+click` a token that reads another node's attribute to
select and frame that node in the graph. See
[Following tokens](reference.md#following-tokens).

### Completion that knows what a compute can use

![Completing another node's attributes](images/completion_node_attrs.png)

- What the world node imports completes in every node, because every
  compute can use it.
- The names nxt gives every compute complete without an import: `STAGE`,
  `self`, `w`, `execute`, `nxt_path`, `ExitNode`, `ExitGraph` and `types`.
- Inside `${/` the node paths in the graph complete, and after a node path's
  dot its attributes, each as a whole token.
- **Host Modules**, a new source: in Maya, `cmds`, `om`, `pm` and the other
  usual short names complete before any import line is written, and so do
  `unreal` in Unreal and `bpy` in Blender. Only modules the host has
  already loaded are offered, so nothing is imported to complete them.
- **Python Analysis (jedi)**, a new optional source: with
  `pip install nxt-editor[completion]`, completion after a dot knows what a
  call returns or a variable holds.

See [Completion](reference.md#completion).

### Docks

- Double click a dock's tab, where docks are tabbed together, to float it.
  Drag a floating dock back in, or double click its title bar to dock it
  again.
- **View > Reset Layout** puts every dock back where a fresh install has it.

See [Docks and layout](reference.md#docks-and-layout).

### Editing layer references

Right click a layer in the Layer Manager and choose **Edit References...** to
add, remove, retype and reorder what that layer references, without opening
the file in a text editor. Paths can be typed exactly as you want them
stored (for example with an environment variable in them), or picked with a
file browser. A **resolved** toggle shows where each reference lands on this
machine, and references that cannot be found are kept and marked rather than
dropped. See [Reference Editor](reference.md#reference-editor).

### Reload Source

Somebody else saved a file your graph is built on? **Reload Source...** (on a
layer's right click menu and in the **File** menu) re-reads that layer, and
as many of the layers it references as you choose, from disk, and
composites the graph again. It can be undone. See
[Reload Source](reference.md#reload-source).

### Mini map

A mini map in the bottom right of the graph shows the whole graph and where
the view is inside it. Click or drag in it to move the view. Toggle it with
**View > Toggle Mini Map** or `Ctrl+M`. See [Stage](reference.md#stage-view).

### Build view

- A **find** button next to the play button scrolls the build to the node
  selected in the graph, and tells you when the selected node is not part of
  the build.
- The build stays current as the graph changes: disabling, deleting,
  renaming, re-parenting or reconnecting a node updates it straight away.

See [Build View](reference.md#build-view).

### Smaller changes

- Deleting a node no longer leaves a "ghost" of it in the graph and the
  build view.
- Pasting several nodes is a single undo.
- Nodes no longer animate open by default, which makes opening a node with
  many children noticeably faster. The **Animate Nodes** action turns the
  animation back on (see [Stage](reference.md#stage-view)).
- A graph is only composited and drawn when its tab is first selected, so
  opening many files at once is faster.
- Renaming a node no longer rebuilds the whole graph when it does not need
  to, and a renamed node keeps its position.
- When a build is set up, a cached runtime that no longer matches the graph
  is rebuilt automatically instead of stopping the build part way through.
- An uncaught error from nxt only opens a dialog when an editor window is
  visible. In batch or headless sessions it is printed instead, so a host
  running a graph in the background never stops on a dialog nobody can see.
- The editor no longer needs `pyside6-rcc` (or any other compiled step) to
  build its icons and styles, so the same release works on every platform
  and host.

## Host integrations

- **Maya**: Maya 2025, 2026 and 2027 are supported. The `nxt_ui` command
  takes `-path` to open graphs, `-close` and `-reload`, and reuses the editor
  that is already open. Graphs can be run in Maya standalone from the
  command line with `run_maya_graph.py`, including a start node and
  parameters, and the builtin `_maya_standalone_graph` node now passes its
  `_start_node` on. See [Maya](install.md#maya).
- **Unreal**: a plugin for Unreal 5.4 to 5.8 that carries its own copy of nxt,
  nxt_editor and Qt.py, with an **nxt** menu and a one click
  **Install Qt (PySide6)**. See [Unreal](install.md#unreal).
- **Blender**: an add-on for Blender 4.2 and newer with an **NXT** menu:
  Open Editor, Close Editor, Run Graph, Run Last Graph, Reload Code and
  Install Qt. See [Blender](install.md#blender).
- Hosts that do not ship Qt install PySide6 once into `~/nxt/deps`, or into a
  shared folder named by `NXT_QT_DEPS`. See
  [Qt for Blender and Unreal](install.md#qt-for-blender-and-unreal).

## Python versions

| Package | Python |
| :------ | :----- |
| nxt-core | 3.7 to 3.14 |
| nxt-editor | 3.9 to 3.14 (PySide6 6.x, below 6.12) |

PySide6 is held below 6.12 until the editor has been tested on it.

## Core (nxt_core 0.21)

- **Faster compositing and execution.** Large graphs composite and build
  substantially faster, with identical results.
- **One order for finding a reference, everywhere.** A reference written
  as an absolute path is used as it is. Any other reference is looked for
  under the folders in `NXT_FILE_ROOTS` first, and then relative to the
  layer that holds it, never relative to wherever the editor was started.
  A file under a root therefore wins over a file of the same name beside
  the layer, which is what lets a working copy listed in `NXT_FILE_ROOTS`
  stand in for the published one. Adding a reference in the editor now
  finds the same file that opening the graph does. See
  [How references are found](reference.md#how-references-are-found).
- **References that cannot be resolved are kept.** Previously a reference to
  a file that could not be found was dropped from the layer, and saving the
  layer wrote it out without the reference. Now it is kept exactly as
  written, so a graph opened on a machine that cannot see a share no longer
  loses its references when saved.
- **Reloading layers from disk** (`Stage.reload_layers`), which is what
  [Reload Source](reference.md#reload-source) is built on. A reference added,
  removed or reordered in the file since the graph was opened is picked up.
- **Removing a layer removes everything it brought in**, including all of its
  references, and only the reference that pointed at it.
- **Targeted renames**: renaming a node that nothing else composites against
  updates it in place instead of recompositing the stage.
- Graph parameters can enable or disable nodes for a run, for example
  `{"/node._enabled": false}`. See
  [Running a graph in Maya standalone](install.md#running-a-graph-in-maya-standalone).
