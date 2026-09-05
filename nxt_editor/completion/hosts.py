"""Host environment providers: per-DCC convenience namespaces for completion.

Each host declares the modules a user typically reaches for in that DCC so
they autocomplete *before* the import is typed. Adding a module is one tuple;
adding a DCC is one small subclass. A registry auto-detects the active host
(honoring nxt's NXT_DCC env var first, then probing imports).

The NxtRuntimeProvider mirrors the implicit globals nxt injects into a node
compute (see nxt/stage.py setup_runtime_layer), so STAGE/self/nxt_path/...
complete accurately regardless of host.
"""
import abc
import importlib
import importlib.util
import os
import types

from nxt import nxt_path
from nxt.constants import NXT_DCC_ENV_VAR
from nxt.runtime import ExitNode, ExitGraph
from nxt_editor.completion import logger


def _can_import(module_path):
    """True if a module is importable, without importing it (no side effects).
    """
    try:
        return importlib.util.find_spec(module_path) is not None
    except Exception:
        return False


def _live_namespace(module_specs):
    """Import each (alias, module_path) spec, skipping any that fail.
    :return: dict of alias -> live module object.
    """
    namespace = {}
    for alias, module_path in module_specs:
        try:
            namespace[alias] = importlib.import_module(module_path)
        except Exception:
            logger.debug("Completion host: '{}' unavailable".format(module_path))
    return namespace


class NamespaceProvider(abc.ABC):
    """Base for anything contributing names to the completion namespace."""

    name = 'base'

    @abc.abstractmethod
    def namespaces(self):
        """Return a dict of name -> live object for jedi.Interpreter."""
        raise NotImplementedError


class NxtRuntimeProvider(NamespaceProvider):
    """The implicit globals every nxt compute runs with (host agnostic).

    Importable runtime objects are exposed live so their attributes complete;
    the dynamic ones (STAGE/self/w/execute) are None placeholders so at least
    the names appear. The model overlays live values when a runtime exists.
    """

    name = 'nxt-runtime'

    def namespaces(self):
        return {'STAGE': None, 'self': None, 'w': None, 'execute': None,
                'nxt_path': nxt_path, 'types': types,
                'ExitNode': ExitNode, 'ExitGraph': ExitGraph}


class HostProvider(NamespaceProvider):
    """A DCC host contributing convenience modules. Subclass + declare modules.

    ``name`` is the host identifier (also matched against the NXT_DCC env var)
    and ``modules`` a tuple of (alias, 'module.path') exposed without an import.
    """

    name = 'base'
    modules = ()

    @classmethod
    @abc.abstractmethod
    def detect(cls):
        """Return True if this host matches the running interpreter."""
        raise NotImplementedError

    def namespaces(self):
        return _live_namespace(self.modules)


class MayaHost(HostProvider):
    name = 'maya'
    modules = (
        ('cmds', 'maya.cmds'),
        ('mc', 'maya.cmds'),
        ('mel', 'maya.mel'),
        ('om', 'maya.api.OpenMaya'),
        ('oma', 'maya.api.OpenMayaAnim'),
        ('omui', 'maya.api.OpenMayaUI'),
        ('omr', 'maya.api.OpenMayaRender'),
        ('pm', 'pymel.core'),
    )

    @classmethod
    def detect(cls):
        return _can_import('maya.cmds')


class MotionBuilderHost(HostProvider):
    name = 'motionbuilder'
    modules = (
        ('pyfbsdk', 'pyfbsdk'),
        ('pyfbsdk_additions', 'pyfbsdk_additions'),
    )

    @classmethod
    def detect(cls):
        return _can_import('pyfbsdk')


class MaxHost(HostProvider):
    name = '3dsmax'
    modules = (
        ('pymxs', 'pymxs'),
    )

    @classmethod
    def detect(cls):
        return _can_import('pymxs')


class UnrealHost(HostProvider):
    name = 'unreal'
    modules = (
        ('unreal', 'unreal'),
    )

    @classmethod
    def detect(cls):
        return _can_import('unreal')


class StandaloneHost(HostProvider):
    name = 'standalone'
    modules = ()

    @classmethod
    def detect(cls):
        return True


# Registry of DCC hosts, highest priority first. Standalone is the fallback
# and is handled explicitly by detect_host (never matched by probing).
_HOST_CLASSES = (MayaHost, MotionBuilderHost, MaxHost, UnrealHost)


def detect_host():
    """Return an instance of the active host provider.

    Resolution order:
        1. The NXT_DCC env var, matched against each host's ``name``.
        2. Probing each host's ``detect()``.
        3. StandaloneHost as a guaranteed fallback.
    :return: HostProvider
    """
    env_dcc = os.environ.get(NXT_DCC_ENV_VAR)
    if env_dcc:
        for host_cls in _HOST_CLASSES:
            if host_cls.name == env_dcc:
                return host_cls()
    for host_cls in _HOST_CLASSES:
        try:
            if host_cls.detect():
                logger.info("Completion host detected: {}".format(host_cls.name))
                return host_cls()
        except Exception:
            logger.exception("Host detection failed for {}".format(host_cls.name))
    return StandaloneHost()
