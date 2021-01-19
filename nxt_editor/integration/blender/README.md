# Installation
**This is an experimental version of nxt_blender. Save early, save often.**  
This is a Blender addon for nxt. Note that it will access the internet to install.  

### By hand (if you're familiar with pip)
1. Locate the path to blenders Python interpreter
    - In Blender, you can run `sys.exec_prefix` to find the folder containing the Python executable.
2. Open Terminal or CMD (If you're using Windows)
3. Run: `/path/to/python.exe -m pip install nxt-editor`
4. Start Blender
5. Open the addon manager (Edit > Preferences > Add-ons)
6. Click "Install" and select the `nxt_blender.py` file provided with this addon zip.
7. To launch NXT navigate the newly created `NXT` menu and select `Open Editor`.

_Note: If you install NXT Blender this way the "Update" button may not work in the NXT menu._

### Automated
1. Open Blender's script editor.
2. Drag and drop `blender_installer.py` into the script editor and click the play button or press `Alt+P` (default run script hotkey)
3. The installation may take a minute or two, during this time Blender will be unresponsive.
    - Optionally open the System Console window before running the script, so you can see what's happening.
 
# Usage
- Ensure the `NXT Blender` addon is enabled.
- To launch NXT navigate the newly created `NXT` menu and select `Open Editor`.