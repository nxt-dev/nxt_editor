"""Let the assistant change the graph: nodes, hierarchies, code and layers.

Every provider can answer with plain text, so changes come back as a
fenced ```nxt-actions block of JSON, the same for Claude, OpenAI, Grok and
local models. The editor runs each action through the stage model, as one
undo step, so Ctrl+Z takes the whole answer back.
"""
# Builtin
import json
import logging
import os
import re

# Internal
import nxt_editor
from nxt import nxt_path
from nxt.nxt_node import INTERNAL_ATTRS

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

FENCE = 'nxt-actions'
MAX_OUTLINE = 300

INSTRUCTIONS = '''
You can change the open graph. You have no files or tools: the only way to
change the graph is to end your answer with one fenced block like this, and
the editor applies it straight away. Never say you wrote or saved a file.

```nxt-actions
[
  {"action": "add_node", "path": "/rig/arm/shoulder",
   "code": "print(self.side)", "attrs": {"side": "L"}},
  {"action": "set_exec_in", "path": "/build", "source": "/setup"}
]
```

Actions (paths are absolute node paths such as /parent/child):
{reference}
Give only the block for the changes the user asked for, and a short
sentence saying what you changed.
'''

ACTION_REFERENCE = '''
- add_node: path, and optionally code, attrs (an object), comment,
  instance (path of the node to inherit from), exec_in (path that runs
  before it, top level nodes only), start_point (true or false), enabled.
  Missing parents are made, so one add_node of /a/b/c builds the whole
  hierarchy. If the node is already there it is updated instead.
- set_code: path, code (the whole of it)
- set_attr: path, name, value (attributes are made if they are missing)
- set_comment: path, comment
- set_instance: path, instance (or null to stop inheriting)
- set_exec_in: path, source (or null)
- set_start_point: path, value
- set_enabled: path, value
- rename_node: path, name (the new short name)
- set_parent: path, parent (a path, or "/" for top level)
- delete_node: path, and optionally recursive (also its children)
- duplicate_node: path (its children come too)
- localize_node: path (copy what it inherits onto the target layer)
- delete_attr: path, name
- rename_attr: path, name, new_name
- set_position: path, x, y (top level nodes)
- set_child_order: path, children (a list of child names, first first)
- select: paths (a list), to show the user nodes in the graph
- add_layer: file (a new .nxt file name, made next to the top layer,
  which must already be saved),
  and optionally alias, and position "below" (default) or "above" the
  target layer. The new layer becomes the target layer.
- reference_layer: file (an .nxt file that is already there, relative to
  the top layer), and optionally position "below" or "above"
- remove_layer: layer (take it out of the graph; the file stays)
- set_layer_alias: layer, alias
- mute_layer: layer, value; solo_layer: layer, value
- set_target_layer: layer (an alias or file path from the layer list)

Changes go on the target layer unless an action gives "layer" (an alias).
Attribute values are strings, numbers, lists or objects. Code is Python,
reading attributes as self.name.
'''

_BLOCK = re.compile(r'```' + FENCE + r'[ \t]*\n(.*?)```', re.S)


def action_reference():
    """What each action does and needs, for the block and the tools."""
    return ACTION_REFERENCE.strip()


def instructions():
    return INSTRUCTIONS.strip().replace('{reference}', action_reference())


def find_actions(text):
    """The actions in a reply, and any problem reading them."""
    actions, problems = [], []
    for block in _BLOCK.findall(text or ''):
        try:
            found = json.loads(block)
        except ValueError as err:
            problems.append('Could not read the changes: {}'.format(err))
            continue
        if isinstance(found, dict):
            found = found.get('actions', [found])
        if not isinstance(found, list):
            problems.append('The changes were not a list.')
            continue
        for action in found:
            if isinstance(action, dict) and action.get('action'):
                actions.append(action)
            else:
                problems.append('Skipped a change with no action: '
                                '{}'.format(action))
    return actions, problems


def without_actions(text, summary=None):
    """text with its action blocks swapped for a short summary."""
    if not _BLOCK.search(text or ''):
        return text
    return _BLOCK.sub(lambda m: summary or '', text).rstrip()


def describe_graph(model):
    """The layers and an outline of the nodes, so the model knows what is
    there before it changes anything."""
    if model is None:
        return ''
    lines = ['Layers, strongest first:']
    target = model.target_layer
    for layer in model.stage._sub_layers:
        mark = ' (target)' if layer is target else ''
        lines.append('  {} {}{}'.format(layer.get_alias(),
                                        layer.real_path or '(not saved)',
                                        mark))
    paths = sorted(model.comp_layer.descendants(nxt_path.WORLD))
    lines.append('Nodes ({}):'.format(len(paths)))
    for path in paths[:MAX_OUTLINE]:
        lines.append('  ' + path)
    if len(paths) > MAX_OUTLINE:
        lines.append('  ... and {} more'.format(len(paths) - MAX_OUTLINE))
    return '\n'.join(lines)


class ActionError(Exception):
    pass


class Applier(object):
    """Runs actions against a StageModel."""

    def __init__(self, model):
        self.model = model
        # Asked for path -> the path the node really got, as a new node is
        # renamed when its name is taken.
        self.renamed = {}
        self.new_roots = 0

    def apply(self, actions):
        """Apply actions as one undo step. Gives back (done, failed): a
        line for each change made, and for each that could not be."""
        done, failed = [], []
        if not actions:
            return done, failed
        stack = self.model.undo_stack
        stack.beginMacro('AI Assistant: {} change{}'.format(
            len(actions), '' if len(actions) == 1 else 's'))
        try:
            for action in actions:
                name = action.get('action')
                handler = getattr(self, 'do_' + str(name), None)
                if handler is None:
                    failed.append('Unknown change "{}"'.format(name))
                    continue
                try:
                    done.append(handler(action))
                except ActionError as err:
                    failed.append(str(err))
                except Exception as err:
                    logger.exception('AI change failed: {}'.format(action))
                    failed.append('{} failed: {}'.format(name, err))
        finally:
            stack.endMacro()
        return done, failed

    # Helpers
    def path(self, action, key='path', required=True):
        path = action.get(key)
        if path in (None, ''):
            if required:
                raise ActionError('{} needs a "{}"'.format(
                    action.get('action'), key))
            return None
        path = str(path).strip()
        if not path.startswith('/'):
            path = '/' + path
        path = path.rstrip('/') or '/'
        return self.renamed.get(path, path)

    def layer(self, action):
        wanted = action.get('layer')
        if not wanted:
            return self.model.target_layer
        found = self.find_layer(wanted)
        if found is None:
            raise ActionError('There is no layer "{}"'.format(wanted))
        return found

    def find_layer(self, wanted):
        for layer in self.model.stage._sub_layers:
            if wanted in (layer.get_alias(), layer.real_path):
                return layer
            if layer.real_path and os.path.basename(
                    layer.real_path) == wanted:
                return layer
        return None

    def exists(self, path, layer=None):
        return self.model.node_exists(path, layer or self.model.comp_layer)

    def require(self, path):
        if not self.exists(path):
            raise ActionError('There is no node {}'.format(path))

    def next_root_pos(self):
        """Somewhere clear of the nodes already there, for a new top level
        node."""
        xs, ys = [], []
        for path in self.model.get_children(nxt_path.WORLD):
            pos = self.model.get_node_pos(path)
            if pos:
                xs.append(pos[0])
                ys.append(pos[1])
        x = (max(xs) + 300) if xs else 0
        y = (min(ys) if ys else 0) + self.new_roots * 120
        self.new_roots += 1
        return [x, y]

    def make_node(self, path, layer):
        """Make path and any parents it is missing. Gives back the path the
        node got."""
        if self.exists(path, layer):
            return path
        parent = nxt_path.get_parent_path(path)
        if parent and parent != nxt_path.WORLD:
            parent = self.make_node(parent, layer)
        else:
            parent = nxt_path.WORLD
        name = nxt_path.node_name_from_node_path(path)
        pos = self.next_root_pos() if parent == nxt_path.WORLD else None
        made = self.model.add_node(name=name, parent_path=parent, pos=pos,
                                   layer=layer)
        if not made:
            raise ActionError('Could not make {}'.format(path))
        if made != path:
            self.renamed[path] = made
        return made

    def set_attrs(self, path, attrs, layer):
        if not isinstance(attrs, dict):
            raise ActionError('attrs for {} must be an object'.format(path))
        for name, value in attrs.items():
            self._set_attr(path, str(name), value, layer)

    def _set_attr(self, path, name, value, layer):
        if name in INTERNAL_ATTRS.PROTECTED:
            raise ActionError('{} is kept by nxt and can not be set'.format(
                name))
        if not isinstance(value, str):
            value = json.dumps(value) if isinstance(value, (list, dict)) \
                else str(value)
        if self.model.node_attr_exists(path, name, layer=self.model.comp_layer):
            self.model.set_node_attr_value(path, name, value, layer=layer)
        else:
            self.model.add_node_attr(path, attr=name, value=value,
                                     layer=layer)

    @staticmethod
    def code_lines(code):
        if isinstance(code, list):
            return [str(line) for line in code]
        return str(code).split('\n')

    # Actions
    def do_add_node(self, action):
        layer = self.layer(action)
        asked = self.path(action)
        existed = self.exists(asked, layer)
        path = self.make_node(asked, layer)
        if 'instance' in action and action['instance']:
            self.model.set_node_instance(path, self.path(action, 'instance'),
                                         layer=layer)
        if action.get('attrs'):
            self.set_attrs(path, action['attrs'], layer)
        if action.get('code') is not None:
            self.model.set_node_code_lines(path,
                                           self.code_lines(action['code']),
                                           layer=layer)
        if action.get('comment'):
            self.model.set_node_comment(path, str(action['comment']),
                                        layer=layer)
        if action.get('exec_in'):
            self.model.set_node_exec_in(path, self.path(action, 'exec_in'),
                                        layer=layer)
        if 'start_point' in action:
            self.model.set_startpoints([path], bool(action['start_point']),
                                       layer=layer)
        if 'enabled' in action:
            self.model.set_node_enabled([path], bool(action['enabled']),
                                        layer=layer)
        verb = 'Updated' if existed else 'Made'
        return '{} {}'.format(verb, path)

    def do_set_code(self, action):
        path = self.path(action)
        self.require(path)
        self.model.set_node_code_lines(path,
                                       self.code_lines(action.get('code', '')),
                                       layer=self.layer(action))
        return 'Set the code of {}'.format(path)

    def do_set_attr(self, action):
        path = self.path(action)
        self.require(path)
        name = action.get('name')
        if not name:
            raise ActionError('set_attr needs a "name"')
        self._set_attr(path, str(name), action.get('value', ''),
                       self.layer(action))
        return 'Set {}.{}'.format(path, name)

    def do_set_comment(self, action):
        path = self.path(action)
        self.require(path)
        self.model.set_node_comment(path, str(action.get('comment', '')),
                                    layer=self.layer(action))
        return 'Set the comment on {}'.format(path)

    def do_set_instance(self, action):
        path = self.path(action)
        self.require(path)
        layer = self.layer(action)
        instance = self.path(action, 'instance', required=False)
        if instance:
            self.require(instance)
            self.model.set_node_instance(path, instance, layer=layer)
            return '{} now inherits from {}'.format(path, instance)
        self.model.revert_node_instance(path, layer=layer)
        return '{} no longer inherits'.format(path)

    def do_set_exec_in(self, action):
        path = self.path(action)
        self.require(path)
        source = self.path(action, 'source', required=False)
        self.model.set_node_exec_in(path, source, layer=self.layer(action))
        if source:
            return '{} runs after {}'.format(path, source)
        return '{} no longer runs after anything'.format(path)

    def do_set_start_point(self, action):
        path = self.path(action)
        self.require(path)
        value = bool(action.get('value', True))
        self.model.set_startpoints([path], value, layer=self.layer(action))
        return '{} is {}a start point'.format(path, '' if value else 'not ')

    def do_set_enabled(self, action):
        path = self.path(action)
        self.require(path)
        value = bool(action.get('value', True))
        self.model.set_node_enabled([path], value, layer=self.layer(action))
        return '{} {}'.format('Turned on' if value else 'Turned off', path)

    def do_rename_node(self, action):
        path = self.path(action)
        self.require(path)
        name = action.get('name')
        if not name:
            raise ActionError('rename_node needs a "name"')
        self.model.set_node_name(path, str(name), layer=self.layer(action))
        new_path = nxt_path.join_node_paths(nxt_path.get_parent_path(path),
                                            str(name))
        self.renamed[path] = new_path
        return 'Renamed {} to {}'.format(path, name)

    def do_set_parent(self, action):
        path = self.path(action)
        self.require(path)
        parent = self.path(action, 'parent', required=False) or \
            nxt_path.WORLD
        if parent != nxt_path.WORLD and not self.exists(parent):
            parent = self.make_node(parent, self.layer(action))
        moved = self.model.parent_nodes([path], parent)
        new_path = nxt_path.join_node_paths(
            parent, nxt_path.node_name_from_node_path(path))
        if moved and path in moved:
            new_path = moved[path]
        self.renamed[path] = new_path
        return 'Moved {} under {}'.format(path, parent)

    def do_delete_node(self, action):
        path = self.path(action)
        self.require(path)
        self.model.delete_nodes([path], layer=self.layer(action),
                                recursive=bool(action.get('recursive')))
        return 'Deleted {}'.format(path)

    def do_duplicate_node(self, action):
        path = self.path(action)
        self.require(path)
        made = self.model.duplicate_nodes([path],
                                          target_layer=self.layer(action))
        if not made:
            raise ActionError('Could not duplicate {}'.format(path))
        return 'Duplicated {} as {}'.format(path, ', '.join(made))

    def do_localize_node(self, action):
        path = self.path(action)
        self.require(path)
        self.model.localize_nodes([path])
        return 'Localized {}'.format(path)

    def do_delete_attr(self, action):
        path = self.path(action)
        self.require(path)
        name = action.get('name')
        if not name:
            raise ActionError('delete_attr needs a "name"')
        self.model.delete_node_attr(path, str(name),
                                    layer=self.layer(action))
        return 'Deleted {}.{}'.format(path, name)

    def do_rename_attr(self, action):
        path = self.path(action)
        self.require(path)
        name, new_name = action.get('name'), action.get('new_name')
        if not name or not new_name:
            raise ActionError('rename_attr needs a "name" and "new_name"')
        self.model.rename_node_attr(path, str(name), str(new_name),
                                    layer=self.layer(action))
        return 'Renamed {}.{} to {}'.format(path, name, new_name)

    def do_set_position(self, action):
        path = self.path(action)
        self.require(path)
        try:
            pos = [float(action['x']), float(action['y'])]
        except (KeyError, TypeError, ValueError):
            raise ActionError('set_position needs numbers for "x" and "y"')
        self.model.set_nodes_pos({path: pos})
        return 'Moved {} to {}, {}'.format(path, *pos)

    def do_set_child_order(self, action):
        path = self.path(action)
        self.require(path)
        children = action.get('children')
        if not isinstance(children, list):
            raise ActionError('set_child_order needs a list of "children"')
        self.model.set_node_child_order(path, [str(c) for c in children])
        return 'Ordered the children of {}'.format(path)

    def do_select(self, action):
        paths = action.get('paths') or []
        if isinstance(paths, str):
            paths = [paths]
        paths = [self.renamed.get(p, p) for p in paths if self.exists(p)]
        self.model.set_selection(paths)
        return 'Selected {}'.format(', '.join(paths) or 'nothing')

    def layer_named(self, action):
        wanted = action.get('layer')
        layer = self.find_layer(wanted) if wanted else None
        if layer is None:
            raise ActionError('There is no layer "{}"'.format(wanted))
        return layer

    def do_reference_layer(self, action):
        name = str(action.get('file') or '').strip()
        if not name:
            raise ActionError('reference_layer needs a "file"')
        top = self.model.top_layer.real_path
        folder = os.path.dirname(top) if top else os.getcwd()
        file_path = os.path.normpath(os.path.join(folder, name))
        if not os.path.isfile(file_path):
            raise ActionError('There is no file {}'.format(file_path))
        target = self.model.target_layer
        above = str(action.get('position', 'below')).lower() == 'above'
        idx = max(target.layer_idx() + (0 if above else 1), 0)
        self.model.reference_layer(file_path, idx=idx, chdir=folder)
        return 'Referenced {}'.format(name)

    def do_remove_layer(self, action):
        layer = self.layer_named(action)
        if layer is self.model.top_layer:
            raise ActionError('The top layer can not be removed')
        alias = layer.get_alias()
        self.model.remove_sublayer(layer)
        return 'Removed the layer {} (its file is still there)'.format(alias)

    def do_set_layer_alias(self, action):
        layer = self.layer_named(action)
        alias = action.get('alias')
        if not alias:
            raise ActionError('set_layer_alias needs an "alias"')
        old = layer.get_alias()
        self.model.set_layer_alias(str(alias), layer)
        return 'Renamed the layer {} to {}'.format(old, layer.get_alias())

    def do_mute_layer(self, action):
        layer = self.layer_named(action)
        value = bool(action.get('value', True))
        if layer.get_muted() != value:
            self.model.mute_toggle_layer(layer)
        return '{} the layer {}'.format('Muted' if value else 'Unmuted',
                                        layer.get_alias())

    def do_solo_layer(self, action):
        layer = self.layer_named(action)
        value = bool(action.get('value', True))
        if layer.get_soloed() != value:
            self.model.solo_toggle_layer(layer)
        return '{} the layer {}'.format('Soloed' if value else 'Unsoloed',
                                        layer.get_alias())

    def do_add_layer(self, action):
        name = str(action.get('file') or '').strip()
        if not name:
            raise ActionError('add_layer needs a "file"')
        if not name.lower().endswith('.nxt'):
            name += '.nxt'
        top = self.model.top_layer.real_path
        if not top:
            raise ActionError('Save the graph first, so the new layer has '
                              'somewhere to go.')
        folder = os.path.dirname(top)
        file_path = os.path.normpath(os.path.join(folder, name))
        if os.path.dirname(file_path) != os.path.normpath(folder):
            raise ActionError('A new layer goes next to the top layer, not '
                              'in another folder.')
        if os.path.exists(file_path) or self.find_layer(name):
            raise ActionError('{} is already there'.format(name))
        target = self.model.target_layer
        above = str(action.get('position', 'below')).lower() == 'above'
        idx = max(target.layer_idx() + (0 if above else 1), 0)
        before = set(id(l) for l in self.model.stage._sub_layers)
        self.model.create_layer(file_path, os.path.splitext(name)[0],
                                idx=idx, chdir=folder)
        made = [l for l in self.model.stage._sub_layers
                if id(l) not in before]
        if not made:
            raise ActionError('Could not make the layer {}'.format(name))
        layer = made[0]
        if action.get('alias'):
            self.model.set_layer_alias(str(action['alias']), layer)
        self.model.set_target_layer(layer.real_path)
        return 'Made the layer {}'.format(name)

    def do_set_target_layer(self, action):
        wanted = action.get('layer')
        layer = self.layer_named(action)
        self.model.set_target_layer(layer.real_path)
        if self.model.target_layer is not layer:
            raise ActionError('{} can not be the target, it may be '
                              'locked'.format(wanted))
        return 'Target layer is now {}'.format(layer.get_alias())


ACTIONS = sorted(name[3:] for name in dir(Applier) if name.startswith('do_'))
