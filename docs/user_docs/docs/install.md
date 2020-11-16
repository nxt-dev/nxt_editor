# Release Installation

##### Maya plugin install

This is a maya module folder for nxt.

###### Manual

- Edit with your paths and place the module definition (.mod) file into a directory of the MAYA_MODULE_PATH.

- By default, the possible locations are:
  
    - Windows: `C:\Users\<username>\Documents\maya\modules`
    - Linux:   `~/maya/modules`
    - Mac:     `~/Library/Preferences/Autodesk/maya/modules`

- You can edit your maya.env file to point to any module location. `MAYA_MODULE_PATH=<path to module file>`

###### Automated

1. Place this nxt module folder somewhere you'd like to keep it, and will be easy to find when you're ready to install a newer version.
2. When your folder is in place, drag the file `drag_into_maya.py` into maya.
   * A file browser will appear. Please select the folder you'd like the nxt module file to go in. Ensure the location you choose is in your maya modules path. This will replace any existing nxt.mod in that directory. If you are unsure where your modules folder is, the default/suggested location should work.
3. Restart maya
4. Now `nxt_maya.py` should be available for you to activate in the plugin browser.

!!! warning
    Remember not to delete this folder after installing in maya. This is where maya loads nxt from. When there is an update to nxt, you can replace this folder, and your nxt plugin will continue to work with the updated code.

###### Usage

* When the nxt plugin is loaded, there is an "nxt" menu at the top of maya where you can select "Open Editor" and get started.

##### Houdini plugin install

##### Nuke plugin install

##### UE4 plugin install

---

# Developer Installation

1. Install git. ([https://git-scm.com/downloads](https://git-scm.com/downloads))

2. Install an IDE 
   
   - [Pycharm community](https://www.jetbrains.com/pycharm/download/)
   - [VS Code](https://www.jetbrains.com/pycharm/download/)
   - GITGUI

3. Install [miniconda](https://docs.conda.io/en/latest/miniconda.html) standard install no env, no system python.

4. Download the repository:   
   
       - Clone in your IDE, docs below for [Pycharm ](#pycharm)and [VScode](#vscode)
       - `https://github.com/SunriseProductions/nxt.git`

5. Launch **Anaconda Prompt** powershell folder and install dependencies by pointing conda to the conda manifest in the repo `nxt.yml`. `conda env create -f PATH_TO_NXT_CLONE/nxt/nxt_env.yml`

6. Launch    
   
   - `app.py` in your IDE   
   - Maya/Nuke/Houdini via [Bootstrap](#bootstrap)

##### CLI integration

- **On Mac/Linux**, update the paths and add the following line to your `.bashrc` or `.zshrc` if you're using zshell.

- `alias nxt='PATH_TO_CONDA/envs/nxt/bin/python2 PATH_TO_NXT_CLONE/cli.py'`

- **On Windows**
  
  - Create `%USERPROFILE%/alias.bat` and add the following line to it

- `DOSKEY nxt=C:\Users\USER_NAME\Miniconda2\envs\nxt\python.exe PATH_TO_NXT_CLONE\nxt\cli.py $*`
  
  - Add the follow key and string value to `Computer\HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Command Processo` in the registery editor.

- `AutoRun`

- `%USERPROFILE%/alias.bat`

## Dependencies

- Python 2.7
- [Qt.py](https://github.com/mottosso/Qt.py)
- PySide2 5.6
- pyyaml 

## Usage

App's entry point is **app.py**. 

## Bootstrap

Tested with Maya2018/19/20, Houdini18, Nuke11,12

!!! warning
    This setup is temporary, and will eventually be replaced with RPC/command port connections with host plugins.  There is also lack of support in apps like photoshop, ue(qt library issues)

Find your conda env with this command in the Anaconda Prompt: `conda info --envs` 
Copy the following code into Maya and edit  `NXT_PATH` and `ENV_PATH` to reflect your environment. You can then drag it to your shelf or save it to a file, up to you.

    import sys
    import os
    # path to your nxt clone
    NXT_PATH = '~/Projects/Sun/nxt'
    # path to conda env
    ENV_PATH = 'C:/ProgramData/Miniconda2/envs/nxt/Lib/site-packages'
    # Default file to open, can be None
    LAUNCH_FILE = '~/Projects/SomeGraph.nxt'
    if ENV_PATH not in sys.path:
        sys.path.append(os.path.expanduser(ENV_PATH))
    if NXT_PATH not in sys.path:
        sys.path.append(os.path.expanduser(NXT_PATH))
    from Qt import QtCore
    import nxt.ui.main_window
    reload(nxt.ui.main_window)
    instance = nxt.ui.main_window.MainWindow(filepath=LAUNCH_FILE)
    if sys.platform == 'win32':
        instance.setWindowFlags(QtCore.Qt.Window)
    instance.show()
    # To force close the instance run this line:
    # instance.close()

##### Optional window attach

To attach to the main window in Nuke

    def _nuke_main_window():
        """Returns Nuke's main window"""
        for obj in QtWidgets.QApplication.topLevelWidgets():
            if (obj.inherits('QMainWindow') and
                    obj.metaObject().className() == 'Foundry::UI::DockMainWindow'):
                return obj
        else:
            raise RuntimeError('Could not find DockMainWindow instance')
    parent = _nuke_main_window()
    instance = nxt.ui.main_window.MainWindow(parent = parent, filepath=LAUNCH_FILE)

To Attach to the main window in Houdini

    from hutil.Qt import QtCore
    #print QtWidgets.QApplication.instance()
    instance = nxt.ui.main_window.MainWindow()
    # parent = hou.qt.mainWindow()
    # instance = nxt.ui.main_window.MainWindow(parent = parent)
    instance.setParent(hou.qt.mainWindow(), QtCore.Qt.Window)

To Attach to the main window in Maya

    import maya.OpenMayaUI as mui
    pointer = mui.MQtUtil.mainWindow()
    maya_window = QtCompat.wrapInstance(long(pointer), QtWidgets.QWidget)

## Pycharm

Launch via pycharm configuration

- Star the `master` branch under VCS>Git>Branches
- Set your interpreter File>Settings>Project:nxt>+Interpreter>Conda Environment>Existing environment
- Python version 2.7
- Find the path using `conda info --envs`
- point to python.exe in the conda env
- confirm by looking at Project>nxt>External Libraries
- Add a new configuration Run > Edit Configurations
- Set the script path to: `PATH_TO_NXT_CLONE/nxt/app.py`
- Set the environment to point to the conda env rather than the basic pycharm venv

## VScode

- Ctrl+shift+p to open the command palette
- type 'install', select install extension, select python

##### Remote debug

Under the Debug icon and then > menu, select 'Add configuration' or Debug>open configurations. Paste this in or add the keys, confirm your port matches the maya session. https://code.visualstudio.com/docs/python/debugging

    {
        // comment
        "version": "0.2.0",
        "configurations": [
            {
                "name": "Python: Current File",
                "type": "python",
                "request": "launch",
                "program": "${file}",
                "console": "integratedTerminal",
                "pathMappings": [
                    {
                        "localRoot": "${workspaceFolder}",
                        "remoteRoot": "."
                    }
                ]
            },
            {
                "name": "Python: Remote Attach Maya",
                "type": "python",
                "request": "attach",
                "port": 3000,
                "host": "localhost",
    
                "pathMappings": [
                    {
                        "localRoot": "Z:/vscode/nxt",
                        "remoteRoot": "Z:/vscode/nxt"
                    }
                ]
            }
    
        ]
    
    }

##### Maya Remote Setup

Ptvsd should be installed by miniconda. If you need to add it, do so with pip. Run the following lines in Maya. It should already be added to your conda env and the  system path should already be updated via the bootstrap

    import ptvsd
    ptvsd.enable_attach(address=('0.0.0.0', 3000), redirect_output=True)

The port used here can be changed, but the VScode launch configuration needs to have a matching port. 
Multiple debug sessions can be available at once on separate ports. These sessions can be changed between by changing your existing launch configuration or via creating addtional launch configurations.

##### Notes

You don't need to hook to Maya to enable breakpoints. The `current file` config will work directly inside VScode.

Once you establish a breakpoint, you can debug using `Python: Remote Attach Maya`

You can then step through into the code execution using the play controls at the top of the screen.

You can also use the debug console to interact directly with the code. For example, you can type `self` to see what the current context is. Code completion should work if you got your `path mappings` key correct in your `launch.json`