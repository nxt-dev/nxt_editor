# NXT Compositing

The general principle of data composition in NXT is centered around the concept of base classes and metaclasses. Data is read from disc and converted into base objects of name `NodeSpec` in memory. These objects are never instantiated (except in very select cases) and are dynamicly used as base classes for intermedate so called "comp nodes". These intermedate classes are simple objects that oftien have sparse overieds to their base classes. The term metaclasse is used because these clases are created using the default `type()` class, we are not using metaclassing to the fullest extent as we simply do not need it. 

In very basic terms we're writing python classes at runtime, in memory, the same way you would write them in your favoirte IDE.

- [Node Classes](#node-classes)
  
  - [NodeSpec](#nodespec)

- [Arc Manger Classes](#arc-manager-classes)
  
  - [Layer](#layer)
  
  - [Stage](#stage)

---

# Node Classes

## NodeSpec

```python
class NodeSpec:
    _nxtname_ = 'node_name'  # String of the node name seen in the UI
    instance = ['node', 'child'] # Namespace of "instace of" node
    instance_source_node = None# Class that this node is an instace of
    descendants = []  # List of imediate children
    _child_order = ['child1', 'child2']  # List of strings of _nxtnames_ of children
    inherit: parent_object  # Class that this node inherits from
    _uid = uuid4()  # Future proofing
```

The lowest level object. Contains all the local data for an NXT node. Above are listed the default propeties of the `NodeSpec` object. If no compute is detected at node creation that attribute is removed to allow upstream compute values to surface.

Node specs attirbutes can be expanded with non-userfacing data in the following ways.

```python
compute = []  # List of strings, each line of code is an item in the list.
```

## User made node attributes

User attrs are setup in the following way.

```python
class NodeSpce:
    ...
    Foo = "Hello World"
    Foo_source__nxt = <NodeSpec>  # The node that has "Foo" as a local attr
```

The other meta or sub attributes for the given attr `Foo` are managed in the following way.

```python
class NodeSpec:
    ...
    Foo_comment__nxt = "Hi I am a comment."
    Foo_runtime__nxt = True  # Not used for anything, legacy
    Foo__type__nxt = str()  # Not used for anything, really should be called a hint since forcing typed attrs isn't very pythonic
```

## NXTInherit

```python
class NXTInherit(NodeSpec, NodeSpec):
    # We reset these two attrs to avoid bad data being inherited by any children nodes
    inherit = None
    descendants = []
```

An `NXTInherit` handles "dumb" parenting of multiple`NodeSpec` objects together via base classing.

## NXTReference

```python
class NXTReference(NodeSpec, NXTInherit):
    # We reset these two attrs to avoid bad data being inherited by any children nodes
    inherit = None
    descendants = []
```

A `NXTReference` can take `NodeSpec` and/or `NXTInherit` objects as base classes. Its purpose is to create a composite of a given namespace across multiple layers.

## NXTInstance

```python
class NXTInstance(NodeSpec, NodeSpec):
    # We reset these two attrs to avoid bad data being inherited by any     children nodes
    inherit = None
    descendants = []
```

Much like the `NXTInherit` object, a `NXTInstance` takes multiple `NodeSpec` objects as base classes. Think of instancing as special parenting, it allows you to pull a node from a tree and insert it as an invisble parent to any node. An instance will not inherit upstream in on the source tree, it will however bring its children as instances. The instance children are compoisited in a simmilar way to an `NXTReference` such that the instance is weaker than the local child of a node.

## NXTRelationship

```python
class NXTRelationship(NXTReference, NXTReference):
    # We reset these two attrs to avoid bad data being inherited by any children nodes
    inherit = None
    descendants = []
```

Much like the `NXTInherit` object, a `NXTRelationship` takes multiple `NXTReference` objects as base classes. It is the final step in the composition arc as it parents `ReferenceNode` objects into hierarchies.

---

# Arc Manager Classes

## Layer

```python
class Layer:
    filepath = "/home/nxt/TestGraph.nxt"
    layer_idx = 0  # Number in layer stack, lower numbers are stronger
    alias = "TestGraph"  # Name of layer. Future proofing
    positions = [[...], [...]]  # The posistion data for the nodes
    execute_order = {}  # Should be list
    breaks = {}
    start_node = "NodeName"
    color = "#119B77"
    sub_layer_paths = []
    sub_layers = []
    enabled_nodes = {}
    collapsed_nodes = {}
    spec_list = []
    descendants = []
```

`spec_list`list holds all the `NodeSpe` objects for a layer, these nodes will never have an arc applied to them.

`descendants`holds the top level nodes in the layer. These nodes can be of any comp arc type. The decendence of the top level node (root node) can be found by recursively looking through the descendants list on the root nodes.

## Stage

TODO: This is gonna be a big one to update!

```python
class Stage:
    sub_layers = [Layer, Layer]
    roots = [RelationshipNode, ReferenceNode]
    def lookup(self, namespace, layer=None):
        '''Returns a CompNode or LayerCompNode''''
```

The `Stage` holds a list of sub_layer objects as well as stage level comp resutls. Stage level comp results are tree dimensional nodes that have been comped across layers by namespace and are then parented together such that the same realitive hierachies are maintained while allowing any one node's data to filter up any number of layers.
