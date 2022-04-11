# Model/View Changes

I don't hate that model has properties instead of getters/setters. Not sure it matters, but I'd prefer a consistent pattern one way or the other.

Do signals need a "model" argument? if not several places may end up trying to parse for it to know if they ought to update.

Should most signals send lists instead of singles? this would allow batches to be handled in 1 redraw rather than several.

Confirmed Signals:

- node_added

- node_removed

- node_renamed

- node_inst_changed
  
  - Whether it was added, removed, or changed implies the same potential for change to a view.

- node_moved
  
  - tends to be cycly, so it will be important to teach everyone recieving to mute, update, un-mute

- selection_changed
  
  - should definitely include a list(not single) for what is now selected, should it report what was previously selected?

- attrs_changed
  
  - attr_value_changed
  
  - attr_added?
  
  - attr_removed?
    
    - This and added both make me think the layer argument would be useful

- node_compute_changed

Signals

- New layer

- Node
  
  - Added
    
    - Duplicated
    
    - Instanced
  
  - Deleted
    
    - Un-instanced
  
  - Renamed
  
  - Set Compute
  
  - Set Comment
  
  - Set Exec Source
  
  - Enabled
  
  - Collapsed
  
  - Set Breakpoint
  
  - Set Startopint
  
  - Set Childorder

- SetNodeInstance?

- Localize
  
  - Nodes
  
  - Attrs
  
  - Computes

- Revert
  
  - Nodes
  
  - Attrs
  
  - Computes

- Parent Nodes

- Attr
  
  - Added
  
  - Deleted
  
  - Renamed
  
  - Value Changed
  
  - Runtime Changed
  
  - Type Changed
  
  - Comment Changed

# Before sunrise release

* remove/hide everything that doesn't work.

* At least a small amount of usability docs

* settle hotkeys

* Backwards compatible saves.

* installer/vendoring

* startpoints
  
  * like position, top layer with opinion controls all start points
  * can we put a single and double play button on node graphics items, where single is "execute this node(and descendants)" and double is "execute from here forward"

* breakpoints
  
  * Part of installation-specific data(inside user dir), stored relative to file path.

* list view of build order
  
  * Can contain an "Execution cursor" that indicates what node will be executed next if step is pressed
  
  * Let's scope execution buttons here
    
    * Execute Selected
    
    * Execute From Selected
      
      * Transforms into "continue"(from cursor) when build is stepping
    
    * Step Forward
  
  * "Sync with selection" button that if selected will always sync your startpoint with your selection. Otherwise a specific start point must be selected for each build order.
  
  * Drop down
    
    * "Selection->"
    
    * "+ Start point at /node/path"
    
    * "+ Start point at /other/node/path"
    
    * "Execution root at /exec/root"
  
  * "Execution root"s are nodes with no in-exec

* general usability pass
  
  * comments
  * click/type node path to travel to node.
  * completers
  * recent files on save
    * `recents_fix` branch
  * layer creation
  * find and replace
  * validated file attrs

* position

* a way for formal feedback(github issues)

* Fix log file(probably and visual log) to include stdout/stderr

* High res icons

### regex/string subs

regex is too welcoming, interprets too manay characters(whitespace, operators

### logging

get sys.stdout/err into log file, useless without.

### QOL

Code editor should start 80 characters wide.

### comp button

`mute` `solo`

### application interface

* Part of choosing interpreter
  
  * "Python Interpreter"
    
    - "Local-Live" - Runs in editor, halts visual process. Currently only option.
    
    - "Built-in Background" - Runs in background with builtin python
    
    - "Application-Live"
      
      - This is wher application interface fits
    
    - "Maya-Background"
      
      - I'm not convinced this is essentail, but the idea is to boot up a batch maya instance, connect via commandport same as live, do work, exit.
      - Interesting in terms of a rig build, could sequence a batch build followed by a file-open on your maya session.
        - I think this idea indicates that maybe being able to select a specific interpreter for each node in a graph would be interesting, because this idea only works if you can select maya-background for 90% of your nodes, and then maya-live for your final open scene node.
        - This is futher complicated to know when a batch session can/should be killed. I think any background interpreters selected by nodes in the graph should have the lifetime of the graph execution.

# Maya

### Module

* Plugins
  
  * nxt listener - Recieves commands from standalone nxt instance
    
    * Go time sequence
      
      1. "Server" nxt instance sends message "time to start a whole fresh execution"
         
         1. listener dumps cached values
      
      2. Server sends initial values of entire tree, in save format likely
      
      3. listener hydrates a stage object from initial(editor) values
      
      4. Server starts execute along execute order
         
         1. Sends "execute /node/path" to listener
         
         2. listener resolves and executes given graph
         
         3. listener sends success/failure response back
    
    * at any time "listener" application will respond to requests for cached values over a different socket
    
    * "listener" side is the session layer, it's the in-progress execution that is actively happening.
    
    * **Cached View/Debugger**
      
      * Server side will need to be able to send updated "initial values" of given node, and listener will need to incorporate those into it's existing tree.
        
        * must be able to be hyper targeted: I want to replace one attribute of one node and leave everything else as cached.
      
      * I think there's a concept of "running with it live" that can be visible in the editor, like a "ON AIR" button that in our case essentially indicates that you are modifying an in-progress build that may create cached values that would not possibly exist during a fresh run.
  
  * nxt local - Runs an nxt application instance locally in maya
  
  * nxt core- shared functionalty of the other two, the `nxt` python package.

when running inside an application we need to be aware of our side-effects on the system, and clean up after ourselves.

### python3

prints, relative imports, and execs are the first needed fixes
