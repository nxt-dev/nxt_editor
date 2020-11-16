# Supported Graph Versions
This release saves `${graph_version}` graphs.  
This release includes backwards compatibility for graph versions as old as `0.45` .

# Installation Types
Each described installation is self contained, and produces a working nxt.
## Pip Installation
1. Download the pip package below "nxt-${version}.tar.gz"
2. From a `Python 2.7` environment run the following command:
    - `pip install --upgrade path/to/nxt-${version}.tar.gz`
    - The python dependancies are:
        - [Qt.py](https://github.com/mottosso/Qt.py)
        - pyside2
    - Note that pyside2 is not available for python2.7 by default on windows([details](https://wiki.qt.io/Qt_for_Python/Considerations#Missing_Windows_.2F_Python_2.7_release)). For instructions on using conda to build an environment to satifsy these dependencies please see [CONTRIBUTING.md](https://github.com/SunriseProductions/nxt/blob/master/CONTRIBUTING.md#python-environment)

## Maya Installation
1. Download nxt_maya.zip below
2. Extract and follow `README.md` inside