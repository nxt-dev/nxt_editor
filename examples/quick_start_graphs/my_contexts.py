# Builtin
import os

# External
from nxt.remote.contexts import RemoteContext, register_context

"""
This file should be placed in your nxt config folder.
First navigate to the help menu, and select `Open Plugins Dir`.

Next copy this file and `maya_context.nxt` to the plugins folder that just 
opened.

Example location:
    ~/nxt/config/0/plugins
"""

# Maya 2019

# This is the name you'll use in your graphs to call this context
maya2019_name = 'Maya'
# This is the path to the mayapy executable
maya2019_exe = 'C:/Program Files/Autodesk/Maya2019/bin/mayapy.exe'
# This is the path to your custom context graph
maya2019_graph = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                              'maya_context.nxt'))
# Create a RemoteContext object
maya_2019_context = RemoteContext(maya2019_name, maya2019_exe, maya2019_graph)
# Register your context with nxt
register_context(maya_2019_context)

