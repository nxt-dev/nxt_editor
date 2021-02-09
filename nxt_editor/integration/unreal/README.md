# Installation
**This is an experimental version of nxt_unreal. Save early, save often.**  
This is an Unreal plugin to connect to the nxt python package. The nxt python package will be downloaded from the internet as part of this installation.

1. Move this plugin either into your project or engine's plugin directory.
2. Ensure that the python editor scripting plugin is activated.
3. Activate the plugin in the engine plugin browser. Exit the engine.
4. Install the nxt python package
    - __automated -__ From unreal editor top menu option "nxt", select "Install nxt package to active python"
    - __by hand -__ Locate engine python(`sys.prefix`) in commmand prompt or terminal and run: `python -m pip install nxt-editor` (Note on windows this will be `python.exe`)
4. Restart Editor

# Launch
From the top menu "nxt", select "Open Editor" to start the nxt editor.

# Update
- __automated -__ From nxt menu select "Update nxt package"
- __by hand -__ From command line of engine python run `python -m pip install --upgrade nxt-editor`
