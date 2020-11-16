# Installation
1. Install [miniconda](https://docs.conda.io/en/latest/miniconda.html) standard install no env, no system python.
2. Install [vscode](https://code.visualstudio.com/download) (use the system installer to install for everyone)
3. Install the python extension
    - Ctrl+shift+p to open the command palette
    - type 'install', select install extension, select python
4. Download repository: [Github](https://github.com/svadanimation/nxt/)
   - Ctrl+shift+p to open the command palette
   - type 'clone'
   - Paste https://github.com/svadanimation/nxt/ , authenticate

5. Launch **Anaconda Prompt** powershell folder and install dependencies by pointing conda to the conda manifest in the repo `nxt.yml`

   `conda env create -f Z:\vscode\nxt\nxt_env.yml
	`
6. Launch via [Maya bootstrap](#maya) or
7. Launch via vscode configuration
   - vscode will automatically detect the conda install
   - Either select in the lower left of the app, or edit the settings.json to point to your conda env.
   - Find the path using  `conda info --envs`
   - Set the environment to point to the conda env rather than the default python

# Usage
App's entry point is **Standalone.py**. 

# Maya bootstrap
Find your conda env with this command in the Anaconda Prompt: `conda info --envs` 
Edit the two paths to reflect your environment.

    import sys
    NXT_PATH = 'Z:/vscode/nxt' #path to your nxt repo
    ENV_PATH = 'C:/ProgramData/Miniconda2/envs/nxt\Lib/site-packages' #path to conda env
    LAUNCH_FILE = 'Z:/vscode/nxt/templates/face/face_variant_x.json'
    sys.path.append(NXT_PATH)
    sys.path.append(ENV_PATH)
    from Qt import QtCompat
    from Qt import QtWidgets
    import nxt.ui.main_window
    reload(nxt.ui.main_window)
    import maya.OpenMayaUI as mui
    pointer = mui.MQtUtil.mainWindow()
    maya_window = QtCompat.wrapInstance(long(pointer), QtWidgets.QWidget)
    instance = nxt.ui.main_window.MainWindow(filepath=LAUNCH_FILE)
    #instance = nxt.ui.main_window.MainWindow()
    instance.show()

# Remote debug
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

# Maya Remote Setup
Ptvsd should be installed by miniconda. If you need to add it, do so with pip. Run the following lines in maya. It should already be added to your conda env and the  system path should already be updated via (#maya)

    import ptvsd
    ptvsd.enable_attach(address=('0.0.0.0', 3000), redirect_output=True)

The port used here can be changed, but the vscdone [launch configuration](https://github.com/svadanimation/nxt/blob/master/vs_code_remote_debug.md#remote-debug) needs to have a matching port. 
Multiple debug sessions can be available at once on seperate ports. These sessions can be changed between by changing your existing launch configuration or via creating addtional launch configurations.


# Notes
You don't need to hook to maya to enable breakpoints. The `current file` config will work directly inside vscode.

Once you establish a breakpoint, you can debug using `Python: Remote Attach Maya`

You can then step through into the code execution using the play controls at the top of the screen.

You can also use the debug console to interact directly with the code. For example, you can type `self` to see what the current context is. Code completion should work if you got your `path mappings` key correct in your `launch.json`
