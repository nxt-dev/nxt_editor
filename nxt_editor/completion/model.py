"""CompletionModel: the Model of the completion MVC.

Owns the optional jedi engine, builds the completion namespace from the host
+ runtime providers, and routes a CompletionContext to the right source. It
is Qt free so it can be unit tested headlessly.
"""
from nxt_editor.completion import logger
from nxt_editor.completion import hosts, sources
from nxt_editor.completion.context import ContextKind

# jedi is an optional dependency (pip install nxt-editor[completion]). Without
# it completion falls back to keywords, builtins and buffer identifiers.
try:
    import jedi
except ImportError:
    jedi = None
    logger.info('jedi not found, using basic code completion')
else:
    try:
        # parso's on disk cache is written per interpreter and collides
        # across DCC python versions (e.g. Maya 2024 py3.10 vs 2025 py3.11),
        # raising on load. The in-memory cache still applies within a session.
        import parso.cache as _parso_cache
        _parso_cache._load_from_file_system = lambda *a, **k: None
        _parso_cache._save_to_file_system = lambda *a, **k: None
    except Exception:
        logger.exception('Could not disable parso disk cache')
    # Skip costly dynamic usage searches, we only need names.
    jedi.settings.fast_parser = True
    jedi.settings.dynamic_params = False
    jedi.settings.dynamic_params_for_other_modules = False
    jedi.settings.dynamic_array_additions = False
    # Warm up once so the first real completion isn't cold.
    try:
        jedi.Interpreter('import os\nos.', namespaces=[{}]).complete(2, 3)
    except Exception:
        pass

_HAS_JEDI = jedi is not None


class CompletionModel(object):
    """Aggregates namespace providers and completion sources.

    :param host: A HostProvider; auto detected when omitted.
    :param stage_model_getter: Callable returning the live stage model (used
    for ${} tokens and live STAGE/self globals).
    :param providers: Override the namespace providers (defaults to runtime
    + host).
    """

    # Live globals pulled from the runtime layer's console (set after a run).
    _LIVE_KEYS = ('STAGE', 'self', '__stage__', 'w', 'execute')

    def __init__(self, host=None, stage_model_getter=None, providers=None):
        self.host = host or hosts.detect_host()
        self.providers = providers or [hosts.NxtRuntimeProvider(), self.host]
        self._stage_model_getter = stage_model_getter
        self.namespaces = self._build_namespaces()  # static base, built once
        self.jedi_enabled = _HAS_JEDI
        # Sources read the namespace through a getter so STAGE/self can
        # reflect the live runtime each request.
        self.jedi_source = (sources.JediSource(jedi, self._current_namespaces)
                            if _HAS_JEDI else None)
        # Runtime dir() for dynamic namespace modules (e.g. maya.cmds) and
        # live STAGE/self attributes that jedi can only see statically.
        self.runtime_attr_source = sources.RuntimeAttributeSource(
            self._current_namespaces)
        self.token_source = sources.TokenSource(stage_model_getter)
        self.keyword_source = sources.KeywordSource()
        self.document_source = sources.DocumentSource()

    def _build_namespaces(self):
        namespace = {}
        for provider in self.providers:
            try:
                namespace.update(provider.namespaces())
            except Exception:
                logger.exception('Namespace provider {} failed'.format(
                    getattr(provider, 'name', '?')))
        return namespace

    def _current_namespaces(self):
        """Static base overlaid with live STAGE/self from the runtime layer."""
        namespace = dict(self.namespaces)
        namespace.update(self._live_namespace())
        return namespace

    def _live_namespace(self):
        getter = self._stage_model_getter
        model = getter() if getter else None
        if model is None:
            return {}
        rt_layer = getattr(model, 'current_rt_layer', None)
        console = getattr(rt_layer, '_console', None)
        globals_dict = getattr(console, 'globals', None)
        if not globals_dict:
            return {}
        live = {}
        for key in self._LIVE_KEYS:
            value = globals_dict.get(key)
            if value is not None:
                live[key] = value
        return live

    def candidates(self, context):
        """Return the unfiltered candidate names for a context.
        :param context: CompletionContext
        :return: list of str
        """
        if context.is_token:
            return self.token_source.candidates(context)
        if context.kind is ContextKind.CODE:
            names = self.runtime_attr_source.candidates(context)
            if self.jedi_source is not None:
                names += self.jedi_source.candidates(context)
            else:
                names += (self.keyword_source.candidates(context) +
                          self.document_source.candidates(context))
            names = sorted(set(names))
            # Hide dunder noise unless the user is explicitly typing one.
            if not context.prefix.startswith('_'):
                names = [n for n in names if not n.startswith('__')]
            return names
        return []
