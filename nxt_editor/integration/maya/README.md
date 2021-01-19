# Installation
This is a maya module folder for nxt.

### By hand(if you're familiar with module folders.)
* There is an example mod file here that you can populate and place

### Automated
1. Place this nxt module folder somewhere you'd like to keep it, and will be easy to find when you're ready to install a newer version.
2. When your folder is in place, drag the file `drag_into_maya.py` into maya.
    * A file browser will appear. Please select the folder you'd like the nxt module file to go in. Ensure the location you choose is in your maya modules path. This will replace any existing nxt.mod in that directory. If you're confused, the default should work."
3. Restart maya
4. Now `nxt_maya.py` should be available for you to activate in the plugin browser.

    **Remember** not to delete this folder after installing in maya. This is where maya loads nxt from. When there is an update to nxt, you can replace this folder, and your nxt plugin will continue to work with the updated code.

# Usage
* When the nxt plugin is loaded, there is an "nxt" menu at the top of maya where you can select "Open Editor" and get started.

# Update
Copy the contents of `nxt_maya/scripts` and `nxt_maya/plug-ins` and replace the existing contents of your NXT Maya installation.  
Restart Maya