# Extensions

NXT can easily extended to better meet a user's/studio's needs. In this section you will find examples of how to use NXT's configuration and plugin system.

**If you're looking for a quick test and not trying to dive too deep, we have an *almost* drag and drop example Maya context [here](https://github.com/nxt-dev/nxt_editor/tree/release/examples/quick_start_graphs).** 

# Config dir

Custom configurations are graphs and code that extends or alters the functionality of nxt. Cofigs are not to be confused with preferences which are soley UX related.

To add a config there are two approaches, both of which are compatible with eachother.

1. Local config
   
   - Config directory location: `~/nxt/config/<major_api_version>`

2- Site config

- Site config directory can be set via an environment variable. `NXT_SITE_DIR=/path/to/site_config`

Inside the config dir you'll need a directory called `plugins`. So for example if you're using API `v0.1.2` your local config plugins dir would be: `~/nxt/config/0/plugins`

# Plugins

Any `.py` files inside your plugin dir(s) will automatilly be imported during nxt startup. 

## Creating Custom Contexts

It is possible to execute graphs in "remote contexts", for example it one may want to execute a graph in a headless Maya session. These remote contexts can easilly be configured by users and TDs, this section will provide some examples on how to go about writing your own custom context plugin.

Below is an exmaple of creating a custom Maya context. This code is an example to get you started, its not the _only_ way to do things.

Files we'll be creating:

```
Plugins
   |_ my_custom_contexts.py
   |_ maya_2020_context.nxt
```

#### my_custom_contexts.py

The following example is for Maya 2020 running on Windows.

The two imports from nxt that you'll need are the `RemoteContext` class and `register_context` function. The first arg in `RemoteContexts` is the **context name**, this will be used by users to call your context. Next we have the context executable, this must be a python (currently only `Python 2.7`) executable. And finally the path to your context graph.


    # Builtin
    import os
    # External
    from nxt.remote.contexts import RemoteContext, register_context
    # Maya 2020
    maya2020_name = 'maya2020'
    maya2020_exe = 'C:/Program Files/Autodesk/Maya2020/bin/mayapy.exe'
    maya2020_graph = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                  'maya_2020_context.nxt'))
    maya_2020_context = RemoteContext(maya2020_name, maya2020_exe, maya2020_graph)
    register_context(maya_2020_context)


#### maya_2020_context.nxt

Now to write your context graph.

- Create an nxt graph and make sure to add the following reference layer:

        "references": [
            "$NXT_BUILTINS/_context.nxt"
        ]


!!! Note
    Currently the _only_ way to add a layer like this (using the env var) is to
     open the graph in a text editor.


- On the `/` node add an attr called `maya_inst_name` and set its value to `nxt`

- Also on the `/` node we're going to want to write some custom code in. Add
 the following to the code block.
           
        cwd = os.path.dirname(sys.executable)
        python_home = os.path.abspath(os.path.join(cwd, '..', 'Python/Lib/site-packages'))
        sys.path.insert(0, python_home)
        from maya import standalone
   
    _This will add the Maya site-packages to your environment and import
     `maya.standalone`._

- In the `/enter/init` node you'll want to add your own custom code, something like this:
 
           STAGE.old_cwd = os.getcwd()
           maya_cwd = os.path.dirname(sys.executable) 
           os.chdir(maya_cwd) 
           standalone.initialize(name='${maya_inst_name}')


5. In the `/enter/teardown` node you want to uninitialize Maya, add the following code:

           standalone.uninitialize(name='${maya_inst_name}')
           os.chdir(STAGE.old_cwd)


### Using Custom Contexts

1. Make sure your graph has this reference layer: `$NXT_BUILTINS/remote_contexts.nxt`

2. Create a node, lets call it `run_in_maya"`

3. Set your new node's instance path to `/_remote_sub_graph`

4. Set the `_context` attr to the raw **context name** you have acces to or just created

5. Set the `_graph_path` attr to the path to a graph that you wish to run in the remote context.

Note: Any other attributes on or inherited by your node `/run_in_maya` will be inherited by the `/` node of your remote graph.


