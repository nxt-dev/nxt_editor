"""What the assistant is told about the graph: the selected nodes."""
# Builtin
import logging
import re

# Internal
import nxt_editor
from nxt.nxt_node import INTERNAL_ATTRS
from nxt_editor.constants import EDITOR_VERSION

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

MAX_NODES = 10
MAX_VALUE = 300
MAX_CODE = 6000

SYSTEM = (
    'You are an assistant inside the nxt editor {version}. nxt is a node '
    'graph where each node holds Python code and attributes. Nodes '
    'execute in order, and a node can be an instance of another node and '
    'inherit from it. Layers reference other layers, and a stronger layer '
    'overrides a weaker one.\n'
    'In node code, attributes are read as self.attr_name, and an '
    'attribute value can use tokens such as ${{attr_name}} or '
    '${{path::attr}}.\n'
    'When you suggest new code for a node without changing the graph, '
    'give the whole of it in one fenced python block, so the user can '
    'apply it to the node.'
)


def system_prompt():
    return SYSTEM.format(version=EDITOR_VERSION.VERSION_STR)


def _short(value, limit):
    text = str(value)
    if len(text) > limit:
        return text[:limit] + ' ...'
    return text


def describe_selection(model):
    """Text describing the selected nodes of model, or '' when none."""
    if model is None:
        return ''
    paths = list(model.selection or [])[:MAX_NODES]
    if not paths:
        return ''
    comp = model.comp_layer
    parts = []
    target = model.target_layer
    if target is not None:
        parts.append('Target layer: {} ({})'.format(
            target.get_alias(), target.real_path or 'not saved'))
    for path in paths:
        try:
            parts.append(_describe_node(model, comp, path))
        except Exception as err:
            logger.debug('Could not describe {}: {}'.format(path, err))
    if len(model.selection) > MAX_NODES:
        parts.append('({} more nodes are selected.)'.format(
            len(model.selection) - MAX_NODES))
    return '\n\n'.join(parts)


def _describe_node(model, comp, path):
    lines = ['Node {}'.format(path)]
    instance = model.get_node_instance_path(path, layer=comp)
    if instance:
        lines.append('Instance of: {}'.format(instance))
    if not model.get_node_enabled(path):
        lines.append('Disabled')
    attrs = []
    for name in sorted(model.get_node_attr_names(path, layer=comp)):
        if name in INTERNAL_ATTRS.PROTECTED:
            continue
        value = model.get_node_attr_value(path, name, layer=comp,
                                          as_string=True)
        attrs.append('  {} = {}'.format(name, _short(value, MAX_VALUE)))
    if attrs:
        lines.append('Attributes:')
        lines += attrs
    code = model.get_node_code_string(path, layer=comp)
    if code:
        lines.append('Code:\n```python\n{}\n```'.format(
            _short(code, MAX_CODE)))
    return '\n'.join(lines)


_BLOCK = re.compile(r'```(?:python|py)?[ \t]*\n(.*?)```', re.S)


def last_code_block(text):
    """The last fenced code block in text, or None."""
    blocks = _BLOCK.findall(text or '')
    if not blocks:
        return None
    return blocks[-1].rstrip('\n')
