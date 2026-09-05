"""Completion sources: each turns a CompletionContext into candidate names.

Sources return *unfiltered* full name lists; the controller filters by the
context prefix (jedi already filters, the static sources do not). This keeps
the filtering rule in one place.
"""
import abc
import builtins
import keyword
import re

from nxt import nxt_path, tokens
from nxt_editor.completion import logger
from nxt_editor.completion.context import ContextKind

_WORD_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
# A pure dotted attribute access left of the cursor, e.g. "cmds." or "a.b.c".
_ATTR_EXPR_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_.]*)\.\w*$')
# nxt ${...} tokens are not valid Python, jedi can't parse a buffer with them.
_TOKEN_RE = re.compile(r'\$\{[^{}]*\}')


def sanitize_tokens(source):
    """Replace ${...} tokens with equal-length string literals.

    A single token makes jedi unable to parse the buffer (so nothing
    completes). Replacing each with a same-length string keeps the code
    parseable and preserves every line/column so the cursor position handed
    to jedi stays correct.
    :param source: str
    :return: str
    """
    def _repl(match):
        span = match.group(0)
        return '"' + ('x' * (len(span) - 2)) + '"'
    return _TOKEN_RE.sub(_repl, source)


class CompletionSource(abc.ABC):
    """Turns a CompletionContext into a list of candidate strings."""

    @abc.abstractmethod
    def candidates(self, context):
        raise NotImplementedError


class JediSource(CompletionSource):
    """Rich Python completion via jedi.Interpreter against live namespaces.

    ``namespace_getter`` is a callable returning the (possibly live)
    namespace dict, so STAGE/self can reflect the current runtime each request.
    """

    def __init__(self, jedi_module, namespace_getter):
        self._jedi = jedi_module
        self._get_namespaces = namespace_getter

    def candidates(self, context):
        if context.kind is not ContextKind.CODE:
            return []
        source = sanitize_tokens(context.source)
        try:
            script = self._jedi.Interpreter(
                source, namespaces=[self._get_namespaces()])
            return [c.name for c in script.complete(context.line,
                                                    context.column)]
        except Exception:
            logger.exception('Jedi completion failed')
            return []


class TokenSource(CompletionSource):
    """nxt ${...} token completion: node paths and attribute names."""

    def __init__(self, stage_model_getter=None):
        self._get_model = stage_model_getter

    def candidates(self, context):
        model = self._get_model() if self._get_model else None
        if model is None:
            return []
        if context.kind is ContextKind.TOKEN_ATTR:
            node_path = context.token_body.rpartition('.')[0]
            return sorted(set(model.get_node_attr_names(node_path) or []))
        if context.kind is ContextKind.TOKEN_NODE:
            names = []
            try:
                names += model.get_descendants(nxt_path.WORLD) or []
            except Exception:
                logger.exception('Failed to gather node paths for completion')
            names += [t.prefix for t in tokens.TOKENTYPE.ALL if t.prefix]
            return sorted(set(names))
        return []


class RuntimeAttributeSource(CompletionSource):
    """dir() based attribute completion for live namespace objects.

    jedi analyses modules statically, so dynamically populated modules such
    as ``maya.cmds`` only expose their dunders. When the cursor is on an
    attribute access of a name we injected into the namespace, fall back to
    a runtime ``dir()`` of the real object. Expressions containing calls or
    subscripts are skipped so nothing is ever executed.
    """

    def __init__(self, namespace_getter):
        self._get_namespaces = namespace_getter

    def candidates(self, context):
        if context.kind is not ContextKind.CODE:
            return []
        lines = context.source.split('\n')
        if not 0 <= context.line - 1 < len(lines):
            return []
        left = lines[context.line - 1][:context.column]
        match = _ATTR_EXPR_RE.search(left)
        if not match:
            return []
        parts = match.group(1).split('.')
        namespaces = self._get_namespaces()
        if parts[0] not in namespaces:
            return []
        obj = namespaces[parts[0]]
        try:
            for part in parts[1:]:
                obj = getattr(obj, part)
        except Exception:
            return []
        if obj is None:
            return []
        try:
            return [n for n in dir(obj) if not n.startswith('__')]
        except Exception:
            return []


class KeywordSource(CompletionSource):
    """Python keywords + builtins; used only when jedi is unavailable."""

    def __init__(self, extra=()):
        builtin_names = [n for n in dir(builtins) if not n.startswith('__')]
        self._names = sorted(set(keyword.kwlist + builtin_names + list(extra)))

    def candidates(self, context):
        if context.kind is not ContextKind.CODE:
            return []
        return self._names


class DocumentSource(CompletionSource):
    """Identifiers already present in the buffer; jedi-unavailable fallback."""

    def candidates(self, context):
        if context.kind is not ContextKind.CODE:
            return []
        words = set(_WORD_RE.findall(context.source))
        words.discard(context.prefix)
        return sorted(words)
