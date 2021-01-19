
# Supported Graph Versions
This release saves `${graph_version}` graphs.  
This release includes backwards compatibility for graph versions as old as `0.45` .

# Installation Types
Each described installation is self contained, and produces a working nxt.
## Pip Installation
From a Python(2 or 3) environment run the following command:  
`pip install nxt-editor`  
**Python Dependancies**  
- [nxt-core](https://github.com/nxt-dev/nxt)   
- [Qt.py](https://github.com/mottosso/Qt.py)  
- [pyside2](https://doc.qt.io/qtforpython/index.html)  
    - **Windows Only** Note that pyside2 is not available for python2.7 by default on windows([details](https://wiki.qt.io/Qt_for_Python/Considerations#Missing_Windows_.2F_Python_2.7_release)). For instructions on using conda to build an environment to satifsy these dependencies please see [CONTRIBUTING.md](https://github.com/nxt-dev/nxt/blob/release/CONTRIBUTING.md#python-environment)

## Blender (2.8 and newer) Installation
1. Download Blender addon (nxt_blender.zip)
2. Extract and follow `README.md` inside  

### Blender update
- Automatically: NXT > Update NXT
- By Hand: `/path/to/python.exe -m pip install -U nxt-editor`


## Maya(2019-2020) Installation/Update
1. Download Maya module(nxt_maya.zip)
2. Extract and follow `README.md` inside  
