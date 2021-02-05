# Installation
**This is an experimental version of nxt_blender. Save early, save often.**  
This is a Blender addon for nxt. Note that it will access the internet to install.  

### By hand (if you're familiar with pip)
1. Locate the path to blenders Python interpreter
    - In Blender, you can run `sys.exec_prefix` to find the folder containing the Python executable
2. Open Terminal or CMD (If you're using Windows)
3. Run: `/path/to/blender/python.exe -m pip install nxt-editor`
4. Start Blender
5. Open the addon manager (Edit > Preferences > Add-ons)
6. Click "Install" and select the `nxt_blender.py` file provided with this addon zip
7. To launch NXT navigate the newly created `NXT` menu and select `Open Editor`


### Automated
1. Open the addon manager (Edit > Preferences > Add-ons)
2. Click "Install" and select the `nxt_blender.py` file provided with this addon zip
3. Enable the `NXT Blender` and twirl down the addon preferences
3. Click `Install NXT dependencies`
   - The installation may take a minute or two, during this time Blender will be unresponsive
   - Optionally open the console window before running the script, so you can see what's happening
4. Restart Blender
 
# Usage
- Ensure the `NXT Blender` addon is enabled
- To launch NXT navigate the newly created `NXT` menu and select `Open Editor`

# Updating
### By hand (if you're familiar with pip)
1. In terminal or cmd run: `/path/to/blender/python.exe -m pip install -U nxt-editor nxt`
2. Restart Blender

### Automated
1. Open the addon manager (Edit > Preferences > Add-ons)
3. Locate the `NXT Blender` and twirl down the addon preferences
3. Click `Update NXT dependencies`
4. Restart Blender

_or_

1. Navigate to the NXT menu
2. Click `Update NXT`
3. Restart Blender

# Uninstall
### By hand (if you're familiar with pip)
1. Open the addon manager (Edit > Preferences > Add-ons)
2. Locate the `NXT Blender` and twirl down the addon preferences
3. Click 'Remove'
1. In terminal or cmd run: `/path/to/blender/python.exe -m pip uninstall nxt-editor nxt -y`

### Automated
1. Open the addon manager (Edit > Preferences > Add-ons)
3. Locate the `NXT Blender` and twirl down the addon preferences
3. Click `Uninstall NXT dependencies`
3. When that finishes, click the 'Remove' button