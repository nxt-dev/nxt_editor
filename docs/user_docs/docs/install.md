# Standalone Installation

### Linux/OSX

*The following also works for Windows Python 3.7, if you're trying to install on Windows in a Python 2 environment see [here](#windows-python-27)*

To install the latest release directly from [PyPi](https://pypi.org/project/nxt-editor/) follow the following steps.

- First time install
    - `pip install nxt-core`
    - `pip install nxt-editor`
- Update
    - `pip install -U nxt-core`
    - `pip install -U nxt-editor`

If you would like to install directly from GitHub use the following command. 

```
pip install git+https://github.com/nxt-dev/nxt.git@{ tag name }
``` 

Assuming you wanted to install API version `0.7.1` the command would look like:
```
pip install git+https://github.com/nxt-dev/nxt.git@api_v0.7.1
``` 

Omit `@{ tag name}` if you want the latest from the `release` branch.


- First time install
    - `pip install git+https://github.com/nxt-dev/nxt.git`
- Update
    - `pip install -U git+https://github.com/nxt-dev/nxt.git`


### Windows (Python 2.7)
*If you're installing into a Python 3.7.x environment you can use the above [steps](#linuxosx)*

Due to the limited availability of PySide2 on Windows for Python 2.7 the steps to install on Windows are slightly more involved.
The following steps are a simplified version of those found in our
 [contributing documentation](https://github.com/SunriseProductions/nxt/blob/master/CONTRIBUTING.md).
If you're comfortable working in and IDE and using git we suggest you follow 
the contributing documentation.

!!! Note
    These steps are only necessary if you want to use the nxt **editor** outside
     of Maya. The core will pip install on Windows without issue.

#### Python Environment (Miniconda)
To get the correct Python environment setup on your Windows machine you will 
need to follow these steps. 
The nxt environment is specified in our `nxt_env.yml`.
 
- Conda is best installed via [miniconda](https://docs.conda.io/en/latest/miniconda.html). 
We recommend **not** adding conda python to your system path and **not** making it your system python.
- You can either clone the nxt source from [our repo](https://github.com/SunriseProductions/nxt) or download the desired
 [release](https://github.com/SunriseProductions/nxt/releases) source code zip and extract it.
- Lets assume you place the source code at `C:/Projects/nxt`
- Launch the **Anaconda Prompt** and install dependencies:
    `conda env create -f C:/Projects/nxt/nxt_env.yml`
#### Launching the nxt editor
- From Anaconda Prompt
    - `conda activate nxt`
    - `cd C:/Projects/nxt`
    - `python -m nxt.cli ui`

---

# Maya Plugin

Install the editor and core for Maya.

### Automated

- Place this nxt module folder somewhere you'd like to keep it, and will be
 easy to find when you're ready to install a newer version.
- When your folder is in place, drag the file `drag_into_maya.py` into maya.
    - A file browser will appear. Please select the folder you'd like the nxt
     module file to go in. Ensure the location you choose is in your maya modules path. This will replace any existing nxt.mod in that directory. If you're confused, the default should work."
- Restart maya
- Now `nxt_maya.py` should be available for you to activate in the plugin
 browser.

**Remember** not to delete this folder after installing in maya. This is where maya loads nxt from. When there is an update to nxt, you can replace this folder, and your nxt plugin will continue to work with the updated code.

### By hand (if you're familiar with Maya modules)
We provide an example `nxt.mod` file with the `nxt_maya` plugin. Simply
populate the mod path with the path to your extracted `nxt_maya.zip` and
 place the `nxt.mod` where Maya can find it.

### Maya plugin usage

* When the nxt plugin is loaded, there is an "nxt" menu at the top of maya where you can select "Open Editor" and get started.
* 

#### Planned plugins:
- Houdini 
- Nuke

---

# Developer Installation
See our [contributing documentation](https://github.com/SunriseProductions/nxt/blob/master/CONTRIBUTING.md)

#### Bootstrapping nxt

Tested with Maya2018/19/20, Houdini18, Nuke11,12

!!! warning
    This setup is temporary, and will eventually be replaced with a command
     port connections with host plugins. There is also lack of support in
      apps like photoshop, UE4 (qt library issues).

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
    import nxt_editor.main_window
    instance = nxt_editor.main_window.main_window.MainWindow(filepath=LAUNCH_FILE)
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
    nuke_window = _nuke_main_window()
    instance = nxt_editor.main_window.MainWindow(parent=nuke_window, filepath=LAUNCH_FILE)

To Attach to the main window in Houdini

    from hutil.Qt import QtCore
    instance = nxt_editor.main_window.MainWindow()
    instance.setParent(hou.qt.mainWindow(), QtCore.Qt.Window)

To Attach to the main window in Maya

    import maya.OpenMayaUI as mui
    pointer = mui.MQtUtil.mainWindow()
    maya_window = QtCompat.wrapInstance(long(pointer), QtWidgets.QWidget)
    instance = nxt_editor.main_window.MainWindow(parent=maya_window)