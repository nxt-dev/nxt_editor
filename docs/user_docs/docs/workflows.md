# Workflows

Nxt supports a particularly diverse cross-section of users with  very different needs and working methods. 

##### Artist

Code is just a click away for artists who know some scripting. Artists can tweak code written by a TD, and build on that example. Artists can also build their own graphs if a project doesn't require a TD.

For example, they could change the height of a rig, or the image size for a render callback, or the directory where an asset is loaded.

##### TD

A TD’s workflow bridges the gap between artists and developers. TD will need most of the deep functionality that a developer needs, but need to focus on speed when  when it’s time to solve problems for artists.  

##### Black Box

A Nxt graph can be packaged up as a pipeline tool and run in the background or on the farm. This might include:

- Rig build
- Asset publish
- Asset QC
- Farm submission
- Post render image processing
- VFX wedge
- Scene assembly

##### Developer

If nxt can provide a accessible front end to software and processes, developers can spend more time on lower level tools. 

# Transition Map

This table will take concepts you are familiar with in other products and draw paralells to nxt concepts.

| OS                                                                                                                                              | NXT                                                                                                                                                      |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| You refer to a directory and file by a path. For example, `/projects/images/image.png` This path points your program to the data in that file. | You refer to a node and attribute by a path. For example `/node/node2.attr`  This points NXT to the data in that source attribute.                      |
| You can create a shortcut to another file. We know that it isn’t the file, but a pointer to quickly work with that file.                        | A token is a little like that shortcut. The token syntax is `${path}`.<br/> A instance is also notionally similar to a shortcut in the most simple case. |
| You can use relative paths, like `../scenes/object.obj`.                                                                                        | You can use relative node paths, like, `${../node2.attr}`                                                                                                |
| You refer to the drive root with `/`                                                                                                            | You refer to the stage root with `/`                                                                                                                     |

!!! note
    NXT node hierarchies process in a tree structure very similar to a directory structure. It starts at the root, executes any code in that node, then crawls through child nodes, compositing and executing any code it finds.

| Photoshop/ NLE                                                                                                                                                                                                      | NXT                                                                                                                                                                                                             |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A basic photoshop layer contains an image. Add a new layer and you can see everything below until you paint on the higher layer in an area where there is already an image. Then the base layers become overridden. | A NXT layer contains a set of nodes. Add a new layer and you can see everything below until you add a node on the higher layer that shares a name with a layer. Then the node on the lower layer is overridden. |
| You can mute and solo layers to change what you see.                                                                                                                                                                | You can mute and solo layers to change what is composited and executed                                                                                                                                          |
| You can overwrite a small portion of the image with a higher layer, or cover the entire layer.                                                                                                                      | You can overwrite a single attribute, or overwrite the entire node.                                                                                                                                             |

| Maya                                                                                                                                                            | NXT                                                                                                                                                                 |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Maya nodes have attributes that hold data or connections to other nodes.                                                                                        | NXT nodes have properties that hold data or pointers to other nodes or properties                                                                                   |
| Maya draws connections between connected attributes.                                                                                                            | NXT draws two types of connections. 1. Node execution 2. Attribute connections                                                                                      |
| Maya transform nodes exist in a hierarchy and inherit the transforms of their parent.                                                                           | NXT nodes inherit properties and values of parent nodes.                                                                                                            |
| Maya executes using a DAG.                                                                                                                                      | NXT executes using a DAG and then a tree.                                                                                                                           |
| A Maya instance is a pointer to a shape, but that shape can have any transform. Any change to the shape propagates to all the instances.                        | A NXT instance is a pointer to a node, and any attributes on that node can be selectively overridden. A change to the original node propagates to all the instances |
| A Maya reference loads an external file, and then attributes and connections can be overridden or added ( but not deleted ), leaving the source file untouched. | A  NXT layer loads an external file, and then attributes and connections can be overridden or added ( but not deleted ), leaving the source file untouched.         |
| To make substantial changes to a Maya reference, you would change the original file, or import the file and ‘own’ it in your scene.                             | A NXT node can be localized and similar to importing.                                                                                                               |
| Values are edited via channel box or attribute editor                                                                                                           | Values are edited via property editor                                                                                                                               |
| UI: navigation, renaming, node connections, 123 hotkeys, qwer hotkeys,                                                                                          |                                                                                                                                                                     |

| Nuke                                                                                                       | NXT                                                                                           |
| ---------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Nuke processes a graph of nodes. Each node can manipulate, add, or remove image data in specific channels. | NXT processes a graph of node trees. Any node can access or overwrite an inherited attribute. |
|                                                                                                            |                                                                                               |

# 

| Houdini                                                                                                  | NXT                                                                                    |
| -------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Houdini SOP nodes pass a table of attributes to subsequent nodes that can be modified, added or deleted. | NXT works in a similar way with it’s inheritance tree.                                 |
| Any child node can access an inherited attribute, visualized via spreadsheet.                            | Any child node can access an inherited attribute, visualized via resolved/cached view. |
| Node paths follow OS conventions                                                                         | Node paths follow OS conventions                                                       |

# 

| Blueprint/Bifrost/Ice/VEX                                                           | NXT                                                                                                                         |
| ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| VP has a node for every function; type conversion, flow control, random generation. | NXT uses nodes and graphs to represent the data and tree execution, but the logic, flow control, and execution is all code. |
|                                                                                     |                                                                                                                             |
|                                                                                     |                                                                                                                             |
