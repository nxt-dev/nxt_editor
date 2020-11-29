# NXT Quick Start
Graphs in this folder contain the scaffolding to support common use cases of nxt. Just copy them out to your project, no need to update the reference paths.

_The assumption is you're generally familiar with the basics of nxt and need a little boost into using some of the deeper features._

### Quick Start Files
- `my_sub_graph.nxt` Is a simple example of how to call a sub graph.
- `my_remote_maya_graph.nxt` Is a simple example of how to call a graph in a remote headless Maya session.
- `my_contexts.py` Context plugin example see [here](#example-remote-context).
- `maya_context.nxt` Graph used by the context plugin, again see [here](#example-remote-context).

---

# Example remote context
To quickly get started with remote contexts we've provided a Maya example.
- First open the nxt editor, navigate to the help menu, and select `Open Plugins Dir`.
- Next copy `my_contexts.py` and `maya_context.nxt` to the plugins folder that just opened.
    - _Assuming your API major version is 0, the path to place this file would be: `~/nxt/config/0/plugins/my_contexts.py`_
    
If you're working on Windows and have Maya 2019 installed in its default location then you're all set. 
If that isn't you, go ahead and read the comments in `my_contexts.py` to configure your context correctly.

Checkout `my_remote_maya_graph.nxt` for an example on how to use your new remote context!
