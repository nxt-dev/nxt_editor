# Hotkeys

Every action below can be given a new shortcut in the Hotkey Editor (**Window > Hotkey Editor**).

## Application Actions
|        Name         |                   What's this                   |      Tool tip       |   Shortcut   |
| :------------------ | :---------------------------------------------: | :------------------ | :----------: |
| Find Node           | Find nodes by name (`*` for anything, commas between names), then select and frame them | Find Node           |      /       |
| New Graph           |                New empty graph.                 | New Graph           |    Ctrl+N    |
| Open Graph          |                 Open nxt file.                  | Open Graph          |    Ctrl+O    |
| Undo                |               Undo last command.                | Undo                |    Ctrl+Z    |
| Redo                |               Redo last command.                | Redo                | Ctrl+Shift+Z |
| Layer Manager       |        Toggle the layer manager widget.         | Layer Manager       |              |
| Property Editor     |       Toggle the property editor widget.        | Property Editor     |              |
| Code Editor         |         Toggle the code editor widget.          | Code Editor         |              |
| History View        |         Toggle the history view widget.         | History View        |              |
| Build View          |          Toggle the build view widget.          | Build View          |              |
| Output Log          |          Toggle the output log widget.          | Output Log          |              |
| Hotkey Editor       |        Toggle the hotkey editor widget.         | Hotkey Editor       |              |
| Workflow Tools      |           Workflow tools dock widget.           | Workflow Tools      |              |
| Exit                |                   Close nxt.                    | Exit                |    Alt+F4    |
| Open Last Closed    |         Open previously closed file(s)          | Open Last Closed    | Ctrl+Shift+T |
| Close Tab           |                Close active tab                 | Close Tab           |    Ctrl+W    |
| Find and Open Graph |                                                 | Find and Open Graph |    Ctrl+P    |
| Update Tokens on Attr Rename | When on, renaming an attribute also renames the tokens in its layer that use it, such as ${attr} and ${/node.attr}, so they keep working. Attributes of the same name on other nodes are left alone. | Update Tokens on Attr Rename |  |
| Update Instance Paths on Parent | When on, parenting nodes also updates the instance paths in the layer that point at them, or at anything under them, so their instances follow. Relative paths stay relative. | Update Instance Paths on Parent |  |

!!! note "New Graph from the tabs"
    The **+** after the open graphs' tabs, or a double click on the empty
    bar beside them, does the same as New Graph, with whatever shortcut
    New Graph has. See [Tabs](reference.md#tabs).

## Alignment
|         Name         |                What's this                |      Tool tip       | Shortcut |
| :------------------- | :---------------------------------------: | :------------------ | :------: |
| Toggle Grid Snapping | Toggles grid snapping while moving nodes. | Toggle snap to grid |  Ctrl+G  |
| Align Left | Line the selected nodes and points up on the left most one. | Align Left | Shift+A |
| Align Center | Line the selected nodes and points up on a line down the middle of them. | Align Center | Alt+Shift+S |
| Align Right | Line the selected nodes and points up on the right most one. | Align Right | Shift+D |
| Align Top | Line the selected nodes and points up on the top most one. | Align Top | Shift+W |
| Align Middle | Line the selected nodes and points up on a line across the middle of them. | Align Middle | Alt+Shift+W |
| Align Bottom | Line the selected nodes and points up on the bottom most one. | Align Bottom | Shift+S |
| Distribute Horizontally | Space the selected nodes and points out evenly from left to right, leaving the ends where they are. | Distribute Horizontally | Alt+Shift+A |
| Distribute Vertically | Space the selected nodes and points out evenly from top to bottom, leaving the ends where they are. | Distribute Vertically | Alt+Shift+D |
| Layout Nodes | Arrange the selected top level nodes, or every one when none are selected, by the order they run in: each exec chain left to right, with its branches stacked below. | Layout Nodes | Shift+L |

## Display
|     Name      |               What's this                |       Tool tip       | Shortcut |
| :------------ | :--------------------------------------: | :------------------- | :------: |
| Raw View      | Displays raw editor values for this tab. | Toggle editor view   |    Q     |
| Resolved View |  Displays resolved values for this tab.  | Toggle resolved view |    W     |
| Cached View   |   Displays cached values for this tab.   | Toggle cached view   |    E     |

!!! note "Typing in a list finds rows"
    Q, W and E work from anywhere in the window, except while you are
    typing. In a text field, the Property Editor's attribute table or the
    Hotkey Editor's table, letters go to what has focus: in a table, typing
    jumps to the row starting with what you typed. Shortcuts with `Ctrl` or
    `Alt`, and any you give the Property Editor's own actions, still work
    there.

## Graph
|            Name             |                      What's this                      |             Tool tip             |  Shortcut   |
| :-------------------------- | :---------------------------------------------------: | :------------------------------- | :---------: |
| Display Node Tooltips       |                                                       | Display Node Tooltips            |             |
| Frame All                   |         Frames all nodes so they are visible.         | Frame all nodes                  |      A      |
| Frame Selection             |               Frames the selected node.               | Frame selected node              |      F      |
| Add Bookmark...             | Save the part of the graph in view under a name, to go back to from the Bookmarks menu. Saved with the graph. | Bookmark this view of the graph | Ctrl+B |
| Go to Bookmark 1            | Show the part of the graph saved as the graph's bookmark number 1. | Go to Bookmark 1 | Ctrl+1 |
| Go to Bookmark 2            | Show the part of the graph saved as the graph's bookmark number 2. | Go to Bookmark 2 | Ctrl+2 |
| Go to Bookmark 3            | Show the part of the graph saved as the graph's bookmark number 3. | Go to Bookmark 3 | Ctrl+3 |
| Go to Bookmark 4            | Show the part of the graph saved as the graph's bookmark number 4. | Go to Bookmark 4 | Ctrl+4 |
| Frame All on Open           | When on, a graph is framed to show all of its nodes when it is first shown, never zoomed in past 100%. When off, it is shown at the origin. On by default. | Frame all nodes when a graph is opened | |
| Display No Attrs            |                 Display no attributes                 | Display No Attrs                 |      0      |
| Display Local Attrs         |             Display local attributes only             | Display Local Attrs              |      1      |
| Display Local+Inst Attrs    |        Display local and instanced attributes         | Display Local+Inst Attrs         |      2      |
| Display All Attrs           |  Display local, instanced, and inherited attributes   | Display All Attrs                |      3      |
| Toggle Grid                 |         Shows or hides the grid for all tabs.         | Show / Hide the Grid             |   Ctrl+;    |
| Toggle Implicit Connections | Shows or hides the implicit connections for this tab. | Show / Hide Implicit Connections |   Ctrl+L    |
| Toggle Mini Map             | Shows or hides the mini map in the bottom right of the graph for all tabs. | Show / Hide the Mini Map |   Ctrl+M    |
| Animate Nodes               | When on, nodes slide and fade as they open and close. Off by default. | Animate nodes opening and closing |             |
| Pick walk up                |                                                       | Pick walk up                     |     Up      |
| Pick walk down              |                                                       | Pick walk down                   |    Down     |
| Pick walk left              |                                                       | Pick walk left                   |    Left     |
| Pick walk right             |                                                       | Pick walk right                  |    Right    |
| Nudge up                    |                                                       | Nudge up                         |  Shift+Up   |
| Nudge down                  |                                                       | Nudge down                       | Shift+Down  |
| Nudge up                    |                                                       | Nudge up                         |  Shift+Up   |
| Nudge left                  |                                                       | Nudge left                       | Shift+Left  |
| Nudge right                 |                                                       | Nudge right                      | Shift+Right |

Hold `Space` and drag with the left mouse button to pan the graph, as a
middle button drag does. It is a mouse action rather than a shortcut, so it
is not in the Hotkey Editor; see [Moving around](reference.md#moving-around).

## Layers
|          Name          |           What's this           |        Tool tip        |   Shortcut   |
| :--------------------- | :-----------------------------: | :--------------------- | :----------: |
| Save Layer             | Saves the current layer to disc | Save Layer             |    Ctrl+S    |
| Save Layer As          |                                 | Save Layer As          | Ctrl+Shift+S |
| Save All Layers        |                                 | Save All Layers        |              |
| Open Source            |  Open target layer in new tab.  | Open Source            | Ctrl+Shift+O |
| Reload Source...       | Re-read a layer, and as much of what it references as you choose, from disk, and composite the graph again. | Re-read this layer and what it references from disk | |
| Edit References...     | Change what a layer references. Applying reloads the referenced layers and recomposites; the layer is written when you save it. | Edit which layers this layer references | |
| Toggle Layer Mute      |                                 | Toggle Layer Mute      |      M       |
| Toggle Layer Solo      |                                 | Toggle Layer Solo      |      S       |
| Change Color           |                                 | Change Color           |              |
| Change Alias           |                                 | Change Alias           |              |
| Create Layer Above     |                                 | Create Layer Above     |              |
| Create Layer Below     |                                 | Create Layer Below     |              |
| Reference Layer Above  |                                 | Reference Layer Above  |              |
| Reference Layer Below  |                                 | Reference Layer Below  |              |
| Remove Layer           |                                 | Remove Layer           |              |
| Layer Manager as Table |                                 | Layer Manager as Table |      V       |

## Nodes
|              Name              |                                 What's this                                 |            Tool tip            |   Shortcut   |
| :----------------------------- | :-------------------------------------------------------------------------: | :----------------------------- | :----------: |
| Select All Nodes               |                                                                             | Select All Nodes               |    Ctrl+A    |
| Add Node                       |                     Add a new node to the current graph                     | Add Node                       |      N       |
| Add Backdrop                   |   Add a backdrop around the selected nodes, or an empty one when none are selected.   | Add Backdrop                   |      C       |
| Delete Node                    |                        Delete the selected node(s).                         | Delete Node                    |     Del      |
| Recursive Delete Node          |        Delete selected node and all of its descendants recursively.         | Recursive Delete Node          |  Shift+Del   |
| Cut                            |                                                                             | Cut                            |    Ctrl+X    |
| Copy                           |                                                                             | Copy                           |    Ctrl+C    |
| Paste                          |                                                                             | Paste                          |    Ctrl+V    |
| Duplicate Node                 |                                                                             | Duplicate Node                 |    Ctrl+D    |
| Instance Node                  |                                                                             | Instance Node                  |    Ctrl+I    |
| Remove Instance                | Removes instance path from node overloading weaker layer instance opinions. | Removes Instance               | Ctrl+Shift+I |
| Localize Node                  |                                                                             | Localize Node                  |              |
| Revert Node                    |                                                                             | Revert Node                    |              |
| Open Sub-graph | Open the graph the selected sub-graph node runs, named in its _graph_path, in a new tab. | Open Sub-graph | Ctrl+Shift+G |
| Push Positions to Target Layer | Write where the selected nodes are now onto the target layer, so it keeps this layout without the layers above it. | Push Positions to Target Layer | |
| Enable/Disable Node            |                                                                             | Enable/Disable Node            |      D       |
| Parent                         |                               Parent node(s).                               | Parent                         |      P       |
| Un-Parent                      |                             Un-parent node(s).                              | Un-Parent                      |   Shift+P    |
| Move up in child order         |                                                                             | Move up in child order         |   Ctrl+Up    |
| Move down in child order       |                                                                             | Move down in child order       |  Ctrl+Down   |
| Toggle Node Collapse           |             Toggle the collapse state for the selected node(s).             | Toggle Node Collapse           |    Alt+C     |
| Recursive Toggle Node Collapse |  Collapse or expand the selected node(s) and everything below, together.  | Recursive Toggle Node Collapse | Alt+Shift+C  |
| Rename Node                    |               Rename the selected node, where you are working.              | Rename Node                    |      F2      |
| Revert child order             |                                                                             | Revert child order             |              |

## Property Editor
|          Name          | What's this |        Tool tip        | Shortcut |
| :--------------------- | :---------: | :--------------------- | :------: |
| Localize Instance Path |             | Localize Instance Path |          |
| Revert Instance Path   |             | Revert Instance Path   |          |
| Localize Exec Path     |             | Localize Exec Path     |          |
| Revert Exec Path       |             | Revert Exec Path       |          |
| Add Attribute          |             | Add Attribute          |  Ctrl+A  |
| Remove Attribute       |             | Remove Attribute       |          |
| Localize Attribute     |             | Localize Attribute     |          |
| Revert Attribute       |             | Revert Attribute       |          |
| Copy Attributes        | Copy the selected attributes, with their values, types and comments, to paste onto other nodes. | Copy Attributes | Ctrl+C |
| Paste Attributes       | Add the copied attributes to the selected node(s) on the target layer, or set them where a node already has them. | Paste Attributes | Ctrl+V |

!!! note "Property Editor shortcuts apply while it has focus"
    `Ctrl+C` and `Ctrl+V` copy and paste attributes while the Property
    Editor has focus, and copy and paste nodes in the graph. In a text
    field they copy and paste text as usual.

## Node Comment
|        Name         |                           What's this                            |      Tool tip       |  Shortcut   |
| :------------------ | :--------------------------------------------------------------: | :------------------ | :---------: |
| Accept Node Comment | Accepts the current text in the comment box as the node comment. | Accept Node Comment | Ctrl+Return |
| Cancel Node Comment |              Cancels the edit of the node comment.               | Cancel Node Comment |     Esc     |

## Graph Execution
|             Name             |                                What's this                                 |           Tool tip           | Shortcut |
| :--------------------------- | :------------------------------------------------------------------------: | :--------------------------- | :------: |
| Run Build                    |          Runs build specified by the current value of build view.          | Run Build                    |          |
| Execute Graph                |                                                                            | Execute Graph                |          |
| Execute Selected             | Run only the selected nodes.                                               | Execute Selected             |  Enter   |
| Execute From Selected        | Execute from the currently selected node and continue down the exec chain. | Execute From Selected        |          |
| Execute Hierarchy            | Run the selected node and every node under it.                             | Execute Hierarchy            |          |
| Add Start Point              |                                                                            | Add Start Point              |          |
| Remove Start Point           |                                                                            | Remove Start Point           |          |
| Revert Start Point           |                                                                            | Revert Start Point           |          |
| Find Startpoint              |              Cycles the node focus through all start points.               | Find Startpoint(s)           |          |
| Add Breakpoint               |                Adds the breakpoint on the selected node(s).                | Add Breakpoint               |          |
| Remove Breakpoint            |              Removes the breakpoint on the selected node(s).               | Remove Breakpoint            |          |
| Clear All Breakpoints        |                                                                            | Clear All Breakpoints        |          |
| Ignore Breakpoints           | Runs go straight through every breakpoint while this is on. The breakpoints are kept. | Ignore Breakpoints |          |
| Clear Cache                  |               Clears the Python interpreter and cached data.               | Clear Cache Now              |          |
| Workflow Tools Always Recomp |                                                                            | Workflow Tools Always Recomp |          |
| Toggle Start Point           |                 Toggles a startpoint on the selected node.                 | Toggle Start Point           |    S     |
| Toggle Breakpoint            |               Toggles a breakpoint on the selected node(s).                | Toggle Breakpoint            |    B     |
| Stop Execution               |                                                                            | Stop Execution               |   Esc    |
| Pause Execution              |                                                                            | Pause Execution              |          |
| Step Build                   |                                                                            | Step Build                   |          |

## Code Editor
|            Name            |                                      What's this                                       |          Tool tip          |     Shortcut      |
| :------------------------- | :------------------------------------------------------------------------------------: | :------------------------- | :---------------: |
| Copy Resolved Code         |                Copy the entire (resolved) contents of the code editor.                 | Copy Resolved Code         |   Ctrl+Shift+C    |
| Localize Code              |                     Localize the code to the target layer's node.                      | Localize Code              |                   |
| Revert Code                |                     Revert the code to the next strongest opinion.                     | Revert Code                |                   |
| Increase Font Size         |                          Increase the code editor font size.                           | Increase Font Size         |      Ctrl+=       |
| Decrease Font Size         |                          Decrease the code editor font size.                           | Decrease Font Size         |      Ctrl+-       |
| Revert Font Size           |                      Revert the code editor font size to default.                      | Revert Font Size           |      Ctrl+0       |
| New Line                   |                                   Insert a new line.                                   | New Line                   |      Return       |
| Indent Line                |                                Indent selected line(s).                                | Indent Line                |        Tab        |
| Un-Indent Line             |                              Un-indent selected line(s).                               | Un-Indent Line             |     Shift+Tab     |
| Execute Selection Globally |       Execute selected line(s)All declared variable will be globally available.        | Execute Selection Globally | Ctrl+Shift+Return |
| Execute Selection Locally  | Execute selected line(s) Locally declared variables fall out of scope after execution. | Execute Selection Locally  |   Shift+Return    |
| Comment Line               |                             Comment the selected line(s).                              | Comment Line               |      Ctrl+/       |
| Accept Code Edit           |                      Accept changes and commit them to the node.                       | Accept Code Edit           |       Enter       |
| Cancel Code Edit           |                              Discard changes to the code.                              | Cancel Code Edit           |        Esc        |
| Find In Code               | Search the code in this editor. | Find In Code | Ctrl+F |
| Replace In Code            | Search and replace in the code in this editor. | Replace In Code | Ctrl+H |
| Find Next                  | Jump to the next match. | Find Next | F3 |
| Find Previous              | Jump to the previous match. | Find Previous | Shift+F3 |
| Go To Line                 | Jump to a line number. | Go To Line | Ctrl+G |
| Duplicate Line             | Copy the selected line(s) below. | Duplicate Line | Ctrl+Shift+D |
| Move Line Up               | Swap the selected line(s) with the line above. | Move Line Up | Alt+Up |
| Move Line Down             | Swap the selected line(s) with the line below. | Move Line Down | Alt+Down |
| Delete Line                | Delete the selected line(s). | Delete Line | Ctrl+Shift+K |
| Expand Selection           | Grow the selection from the word under the cursor, to the line, to everything. | Expand Selection | Ctrl+D |
| Fold Block                 | Fold away the indented block the cursor is in. | Fold Block | Ctrl+Shift+[ |
| Unfold Block               | Show the block folded away behind the line the cursor is on. | Unfold Block | Ctrl+Shift+] |
| Fold All                   | Fold away every indented block. | Fold All | Ctrl+K, Ctrl+0 |
| Unfold All                 | Show every folded block. | Unfold All | Ctrl+K, Ctrl+J |
| Complete Word              | Offer completions for the word being typed. | Complete Word | Ctrl+Space |
| Code Editor Autocomplete   | When on, completions are offered as you type. Ctrl+Space always offers them either way. | Code Editor Autocomplete | |

!!! note "Code editor shortcuts win while it has focus"
    The code editor's shortcuts only apply while the code editor has focus, and while it does they take
    precedence: `Ctrl+F`, `Ctrl+G` and `Ctrl+D` find in code, go to a line and expand the selection there,
    and open the graph wide find, toggle grid snapping and duplicate nodes everywhere else.
    The completion sources are toggled from **Options > Autocomplete**; see
    [Completion](reference.md#completion).

    `Ctrl+click` on a `${}` token, which selects the node the token reads
    from, is a mouse action rather than a shortcut, so it is not listed here;
    see [Following tokens](reference.md#following-tokens).

