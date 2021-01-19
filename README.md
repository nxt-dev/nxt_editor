# NXT Editor

**nxt** (**/ɛn·ɛks·ti/**) is a general purpose code compositor designed for rigging, scene assembly, and automation. (node execution tree)  
[Installation/Usage](#installationusage) | [Docs](https://nxt-dev.github.io/) | [Contributing](CONTRIBUTING.md) | [Licensing](LICENSE)

# Installation/Usage
**To Use NXT please use the [NXT Standalone](#nxt-standalone) or [DCC plugin zip.](#maya-plugin)**  
Only clone this repo if you're [contributing](CONTRIBUTING.md) to the NXT codebase.

<br>

#### Requirements
- Python >= [2.7.*](https://www.python.org/download/releases/2.7) <= [3.7.*](https://www.python.org/download/releases/3.7)
- We strongly recommend using a Python [virtual environment](https://docs.python.org/3.7/tutorial/venv.html)

*[Requirements for contributors](CONTRIBUTING.md#python-environment)*  

### NXT Standalone
Our releases are hosted on [PyPi](https://pypi.org/project/nxt-editor/).
- Install:
    - `pip install nxt-editor`
- Launch:
    - `nxt ui`
- Update:
    - `pip install -U nxt-editor`

### Blender addon:
- Install:
    1. Download Blender addon (nxt_blender.zip) [latest release](https://github.com/nxt-dev/nxt_editor/releases/latest)
    2. Extract and follow `README.md` inside  [nxt_blender](nxt_editor/integration/blender/README.md) instructions (also included in the download)
- Launch:
    1. Load the `nxt_blender` Addon (Edit > Preferences > Add-ons)
    2. Navigate the newly created NXT menu and select Open Editor.
- Update:
    - Automatically: NXT > Update NXT
    - By Hand: `/path/to/python.exe -m pip install -U nxt-editor`
    - Relaunch Blender after


### Maya plugin:

- Install:
    1. Download the maya module(`nxt_maya.zip`) from the [latest release](https://github.com/nxt-dev/nxt_editor/releases/latest)
    2. Follow the [nxt_maya](nxt_editor/integration/maya/README.md) instructions (also included in the download)
- Launch:
    1. Load `nxt_maya` plugin in Maya
    2. Select the `nxt` menu from the menus at the top of Maya
    3. Click `Open Editor`
- Update:
    1. Download the `nxt_maya` zip from the [latest release](https://github.com/nxt-dev/nxt_editor/releases/latest)
    2. Extract the zip and replace the existing `nxt_maya` files with the newly extracted files.
    3. Re-launch Maya

<br>

## Special Thanks

[Sunrise Productions](https://sunriseproductions.tv/) | [School of Visual Art and Design](https://www.southern.edu/visualartanddesign/)

---

| Release | Dev |
| :---: | :---: |
| ![Build Status](https://travis-ci.com/nxt-dev/nxt_editor.svg?token=rBRbAJTv2rq1c8WVEwGs&branch=release) | ![Build Status](https://travis-ci.com/nxt-dev/nxt_editor.svg?token=rBRbAJTv2rq1c8WVEwGs&branch=dev) |

