<div align="center">

![Release Status](https://github.com/nxt-dev/nxt_editor/actions/workflows/release.yml/badge.svg?branch=release)
![Dev Status](https://github.com/nxt-dev/nxt_editor/actions/workflows/unittests.yml/badge.svg?branch=dev)
# NXT Editor

</div>


**nxt** (**/ɛn·ɛks·ti/**) is a general purpose code compositor designed for rigging, scene assembly, and automation. (node execution tree)  
[Installation/Usage](#installationusage) | [Docs](https://nxt-dev.github.io/) | [Contributing](CONTRIBUTING.md) | [Licensing](LICENSE)

# Installation/Usage
**To Use NXT please use the [NXT Standalone](#nxt-standalone) or [DCC plugin zip.](#DCC-Plugins)**  
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

### DCC Plugins

Each of our supported DCC's get a zip file on our [latest release](https://github.com/nxt-dev/nxt_editor/releases/latest)

Each one contains a `README.md` inside to explain how to install/update them.
- [nxt_maya](nxt_editor/integration/maya/README.md)
- [nxt_blender](nxt_editor/integration/blender/README.md)
- [nxt_unreal](nxt_editor/integration/unreal/README.md)

<br>

## Special Thanks

[Sunrise Productions](https://sunriseproductions.tv/) | [School of Visual Art and Design](https://www.southern.edu/visualartanddesign/)

---

| Release | Dev |
| :---: | :---: |
| ![Build Status](https://travis-ci.com/nxt-dev/nxt_editor.svg?token=rBRbAJTv2rq1c8WVEwGs&branch=release) | ![Build Status](https://travis-ci.com/nxt-dev/nxt_editor.svg?token=rBRbAJTv2rq1c8WVEwGs&branch=dev) |

