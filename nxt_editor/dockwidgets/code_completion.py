"""Where the code editor's completions come from, beyond the editor itself.

Three things a compute can use without importing them, and an optional
python analyser:

- The names nxt hands every compute: STAGE, self, nxt_path and the rest.
- The modules a host keeps loaded, maya.cmds in Maya, unreal in Unreal,
  so cmds. completes before an import line is written. Only modules the
  host has already loaded are offered; nothing is imported for them,
  because importing pymel alone can take seconds.
- jedi, when it is installed (pip install nxt-editor[completion]). It knows
  what a name is, so it can complete what a call returns or what a local
  variable holds, which reading import lines cannot.

The jedi support, the token sanitizing and the host module lists come
from a pull request by @enriquevelmai (nxt-dev/nxt_editor#298).
"""
# Builtin
import importlib.util
import inspect
import logging
import os
import re
import sys
import types

# Internal
from nxt import nxt_path
from nxt.constants import NXT_DCC_ENV_VAR, USER_DIR
from nxt.runtime import ExitNode, ExitGraph

logger = logging.getLogger(__name__)

#: The names every compute runs with. The ones only a running graph can
#: fill in are None, which is still enough for the name to complete.
RUNTIME_GLOBALS = {
    'STAGE': None,
    'self': None,
    'w': None,
    'execute': None,
    'nxt_path': nxt_path,
    'types': types,
    'ExitNode': ExitNode,
    'ExitGraph': ExitGraph,
}

#: The names above that a graph fills in when it runs.
LIVE_GLOBALS = tuple(name for name, value in RUNTIME_GLOBALS.items()
                     if value is None)


def runtime_namespace(rt_layer=None, node_path=None):
    """What can be completed after the dot of a name nxt gives a compute.

    The None placeholders are left out. Completing on None offered what
    None has, __bool__, __class__ and the rest, after STAGE. and self.,
    which is worse than offering nothing. Once the graph has run, the
    runtime layer holds the real things: STAGE with whatever the graph
    stored on it, and this node as it ran, for self.

    :param rt_layer: the runtime layer of the last build, if there was one
    :param node_path: the node being edited, which is what self means
    :type node_path: str | None
    :return: {name: object}
    :rtype: dict
    """
    namespace = {name: value for name, value in RUNTIME_GLOBALS.items()
                 if value is not None}
    console = getattr(rt_layer, '_console', None)
    live = getattr(console, 'globals', None) or {}
    for name in LIVE_GLOBALS:
        value = live.get(name)
        if value is not None:
            namespace[name] = value
    # The console's self is whichever node ran last. In the code editor
    # self is the node being edited.
    namespace.pop('self', None)
    if node_path and live:
        try:
            node = rt_layer.lookup(node_path)
        except Exception:
            node = None
        if node is not None:
            namespace['self'] = node
    return namespace


def attr_for_completion(obj, name):
    """An attribute to look inside, read without running anything.

    Walking os.path.jo needs os.path, and getattr is fine on a module.
    On a live object getattr can run a property, and a property on a scene
    object can do anything, so those are read statically and a property is
    where the walk stops.

    :return: the attribute, or None when there is none or it would have to
        be computed
    """
    if isinstance(obj, types.ModuleType):
        return getattr(obj, name, None)
    try:
        value = inspect.getattr_static(obj, name)
    except AttributeError:
        return None
    if isinstance(value, (staticmethod, classmethod)):
        return value.__func__
    if hasattr(type(value), '__get__') and not inspect.isroutine(value):
        # A property or another descriptor: its value is not there to read.
        return None
    return value

#: Modules each host keeps loaded, by the name scripts usually give them.
HOST_MODULES = {
    'maya': (('cmds', 'maya.cmds'), ('mc', 'maya.cmds'), ('mel', 'maya.mel'),
             ('om', 'maya.api.OpenMaya'), ('oma', 'maya.api.OpenMayaAnim'),
             ('omui', 'maya.api.OpenMayaUI'),
             ('omr', 'maya.api.OpenMayaRender'), ('pm', 'pymel.core')),
    'unreal': (('unreal', 'unreal'),),
    'blender': (('bpy', 'bpy'),),
    'motionbuilder': (('pyfbsdk', 'pyfbsdk'),
                      ('pyfbsdk_additions', 'pyfbsdk_additions')),
    '3dsmax': (('pymxs', 'pymxs'),),
}


def host_modules():
    """The host's modules that are already loaded, by their usual names.

    The host named by NXT_DCC is asked first. Without one, any host whose
    modules are loaded counts, which is the case when the editor runs inside
    a host that did not set it.

    :return: {name to complete: module}
    :rtype: dict
    """
    dcc = os.environ.get(NXT_DCC_ENV_VAR, '')
    hosts = [dcc] if dcc in HOST_MODULES else list(HOST_MODULES)
    found = {}
    for host in hosts:
        for alias, module_name in HOST_MODULES[host]:
            module = sys.modules.get(module_name)
            if module is not None and alias not in found:
                found[alias] = module
    return found


# A ${...} token. nxt resolves these before python sees the code, so to a
# python parser they are syntax errors.
_TOKEN_RE = re.compile(r'\$\{[^{}]*\}')


def sanitize_tokens(source):
    """Swap each ${...} token for a string literal of the same length.

    A single token makes the code unparseable, so nothing would complete.
    Keeping the length keeps every line and column where it was, so the
    cursor position handed to jedi still points at the same place.

    :param source: code that may contain tokens
    :type source: str
    :rtype: str
    """
    return _TOKEN_RE.sub(lambda match: '"' + 'x' * (len(match.group(0)) - 2)
                         + '"', source)


class Jedi(object):
    """jedi, loaded the first time it is asked for, if it is installed.

    jedi takes a couple of seconds to import and warm up, which nobody
    should pay for at startup, least of all inside a host. Its results for
    one dotted prefix are kept until the code around it changes, so typing
    more of a name only filters what it already said.
    """

    #: Where jedi keeps its parse cache. Its own default is shared by every
    #: jedi on the machine, while this one belongs to nxt.
    CACHE_DIR = os.path.join(USER_DIR, 'jedi_cache')

    def __init__(self):
        self._module = None
        self._tried = False
        self._failed_once = False
        self._cache_key = None
        self._cache_names = []

    def module(self):
        """jedi itself, or None when it is not installed."""
        if self._tried:
            return self._module
        self._tried = True
        try:
            import jedi
        except ImportError:
            return None
        jedi.settings.cache_directory = self.CACHE_DIR
        # Completing an attribute of a live object can call its properties.
        # A property on a scene object can do anything, so jedi only reads.
        jedi.settings.allow_unsafe_interpreter_executions = False
        self._module = jedi
        return jedi

    def available(self):
        return self.module() is not None

    @staticmethod
    def installed():
        """Whether jedi is there to load, without loading it."""
        try:
            return importlib.util.find_spec('jedi') is not None
        except (ImportError, ValueError):
            return False

    def cached(self, key):
        """The names last worked out for `key`, or None."""
        return self._cache_names if key == self._cache_key else None

    def complete(self, source, line, column, namespace, key, fresh=False):
        """Names that can follow the cursor, as jedi sees the code.

        :param source: the whole compute
        :param line: cursor line, starting at 1
        :param column: cursor column, starting at 0
        :param namespace: live names the compute can use without importing
        :param key: what the answer depends on, for the cache
        :param fresh: ask again even if this spot was asked before, for
            when something the code uses has changed, a reloaded module say
        :return: completed names, without the part before the last dot
        :rtype: list
        """
        cached = None if fresh else self.cached(key)
        if cached is not None:
            return cached
        jedi = self.module()
        if jedi is None:
            return []
        try:
            script = jedi.Interpreter(sanitize_tokens(source),
                                      namespaces=[namespace])
            names = [c.name for c in script.complete(line, column)]
        except Exception:
            # A compute that does not parse yet is normal while typing, so
            # this is said once rather than on every key.
            if not self._failed_once:
                logger.debug('jedi could not complete here', exc_info=True)
                self._failed_once = True
            names = []
        self._cache_key = key
        self._cache_names = names
        return names


#: One for the whole editor, so the warm up and the cache are shared.
JEDI = Jedi()
