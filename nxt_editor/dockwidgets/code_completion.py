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
import logging
import os
import re
import sys
import threading
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


#: Most names offered after the dot of something a graph left behind. A rig
#: can keep thousands of things on STAGE, and a list that long is no help.
LIVE_NAME_LIMIT = 2000

# Read straight from type, so a class cannot answer with code of its own.
_class_dict = type.__dict__['__dict__'].__get__
_class_mro = type.__dict__['__mro__'].__get__

# What reading a slot or an instance's __dict__ goes through. They copy a
# value out of the object, no python runs.
_PLAIN_READS = (types.MemberDescriptorType, types.GetSetDescriptorType)

_MISSING = object()


def _is_a(obj, klass):
    """isinstance without asking obj, which could answer through __class__."""
    return any(base is klass for base in _class_mro(type(obj)))


def _has_on_class(klass, name):
    return any(name in _class_dict(base) for base in _class_mro(klass))


def _instance_dict(obj):
    """obj's own __dict__, or None, read without running anything of obj's."""
    for base in _class_mro(type(obj)):
        entry = _class_dict(base).get('__dict__')
        if entry is None:
            continue
        if type(entry) not in _PLAIN_READS:
            # A class that makes __dict__ a property of its own.
            return None
        found = entry.__get__(obj)
        return found if _is_a(found, dict) else None
    return None


def _namespaces(obj):
    """(obj's own __dict__ or None, its classes' dicts in lookup order)."""
    if _is_a(obj, type):
        return None, [_class_dict(base) for base in _class_mro(obj)]
    return (_instance_dict(obj),
            [_class_dict(base) for base in _class_mro(type(obj))])


def static_attr(obj, name):
    """An attribute of a live object, without running any of its code.

    No __getattr__, no __getattribute__, no property. A value stored on the
    object or its class is read; a method is read as the function it is; a
    property or any other computed attribute is where the walk stops.

    :return: the attribute, or None when there is none or it would have to
        be computed
    """
    try:
        own, classes = _namespaces(obj)
        on_class = next((namespace[name] for namespace in classes
                         if name in namespace), _MISSING)
        computed = (on_class is not _MISSING and
                    _has_on_class(type(on_class), '__get__'))
        if own is not None and dict.__contains__(own, name):
            data = computed and (_has_on_class(type(on_class), '__set__') or
                                 _has_on_class(type(on_class), '__delete__'))
            if not data:
                # Python reads the object's own value first, unless the
                # class has a property of that name.
                return dict.__getitem__(own, name)
        if on_class is _MISSING:
            return None
        if _is_a(on_class, staticmethod) or _is_a(on_class, classmethod):
            return on_class.__func__
        if not computed or _is_a(on_class, types.FunctionType):
            return on_class
        if (type(on_class) is types.MemberDescriptorType and
                not _is_a(obj, type)):
            # A __slots__ entry, copied out of the object.
            return on_class.__get__(obj)
        return None
    except Exception:
        return None


def static_names(obj, start='', limit=LIVE_NAME_LIMIT):
    """The public names on a live object, without running any of its code.

    dir() calls the object's __dir__, which is its code to run. These come
    from the object's own __dict__ and its classes' instead, which is also
    where __slots__ entries are listed.

    :param start: only names that start with this, the part already typed
    :param limit: stop after this many
    :rtype: list
    """
    names = []
    seen = set()
    try:
        own, classes = _namespaces(obj)
        if own is not None:
            classes.insert(0, own)
        for namespace in classes:
            if _is_a(namespace, dict):
                keys = list(dict.keys(namespace))
            else:
                keys = list(namespace.keys())
            for key in keys:
                if (type(key) is not str or key.startswith('_') or
                        not key.startswith(start) or key in seen):
                    continue
                seen.add(key)
                names.append(key)
                if len(names) >= limit:
                    return names
    except Exception:
        # A build in another thread can change a dict while it is read.
        logger.debug('Could not list names for completion', exc_info=True)
    return names


def live_completions(obj, rest, limit=LIVE_NAME_LIMIT):
    """What follows the dots after something a graph left behind.

    Only names come back, never the objects they name, so nothing that
    belongs to the graph is held on to or handed elsewhere.

    :param obj: STAGE or self, as the build left it
    :param rest: what is typed after its first dot, like rig.bu
    :return: the dotted names after the first dot, like rig.build_guides
    :rtype: list
    """
    parts = rest.split('.')
    walked = ''
    for part in parts[:-1]:
        obj = static_attr(obj, part)
        if obj is None:
            return []
        walked += part + '.'
    return [walked + name for name in static_names(obj, parts[-1], limit)]


def attr_for_completion(obj, name):
    """An attribute to look inside, read without running anything.

    Walking os.path.jo needs os.path, and getattr is fine on a module.
    On anything else getattr can run a property or a __getattr__, which on
    a scene object can do anything, so those are read with static_attr.

    :return: the attribute, or None when there is none or it would have to
        be computed
    """
    if _is_a(obj, types.ModuleType):
        return getattr(obj, name, None)
    return static_attr(obj, name)


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

    The editor asks it from a worker thread, so a slow answer never holds
    up typing. One question is answered at a time.
    """

    #: Where jedi keeps its parse cache. Its own default is shared by every
    #: jedi on the machine, while this one belongs to nxt.
    CACHE_DIR = os.path.join(USER_DIR, 'jedi_cache')

    def __init__(self):
        self._module = None
        self._tried = False
        self._failed_once = False
        # The key and its names, swapped together so a reader on another
        # thread never sees one without the other.
        self._cache = (None, [])
        self._lock = threading.Lock()

    def module(self):
        """jedi itself, or None when it is not installed."""
        with self._lock:
            return self._load()

    def _load(self):
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
        cache_key, names = self._cache
        return names if key == cache_key else None

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
        with self._lock:
            cached = None if fresh else self.cached(key)
            if cached is not None:
                return cached
            jedi = self._load()
            if jedi is None:
                return []
            names = self._complete(jedi, source, line, column, namespace)
            self._cache = (key, names)
            return names

    def _complete(self, jedi, source, line, column, namespace):
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
        return names


#: One for the whole editor, so the warm up and the cache are shared.
JEDI = Jedi()
