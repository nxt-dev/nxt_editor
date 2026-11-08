"""Run provider requests off the UI thread."""
# Builtin
import threading

# External
from Qt import QtCore


class TaskThread(QtCore.QThread):
    """Calls fn(cancelled, *args) on its own thread. cancelled is a
    threading.Event that cancel() sets."""
    done = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, fn, *args, **kwargs):
        parent = kwargs.pop('parent', None)
        super(TaskThread, self).__init__(parent)
        self.fn = fn
        self.args = args
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        try:
            result = self.fn(self.cancelled, *self.args)
        except Exception as err:
            if not self.cancelled.is_set():
                self.failed.emit(str(err) or type(err).__name__)
            return
        if not self.cancelled.is_set():
            self.done.emit(result)


class ChatThread(QtCore.QThread):
    """Streams one reply, a piece at a time.

    With tools, the model may use them as it answers. A model that can not
    use tools is asked again without them, with fallback_system, and
    tools_dropped is emitted so the panel knows.
    """
    chunk = QtCore.Signal(str)
    failed = QtCore.Signal(str)
    tools_dropped = QtCore.Signal()

    def __init__(self, provider, messages, system, model, parent=None,
                 tools=None, fallback_system=None):
        super(ChatThread, self).__init__(parent)
        self.provider = provider
        self.messages = messages
        self.system = system
        self.model = model
        self.tools = tools
        self.fallback_system = fallback_system or system
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()
        if self.tools is not None:
            self.tools.cancel()

    def _stream(self, system, tools):
        if tools is None:
            return self.provider.stream_chat(self.messages, system,
                                             model=self.model)
        return self.provider.stream_chat(self.messages, system,
                                         model=self.model, tools=tools)

    def run(self):
        from nxt_editor.ai.providers import ToolsUnsupported
        try:
            try:
                self._pass(self.system, self.tools)
            except ToolsUnsupported:
                if self.cancelled.is_set():
                    return
                self.tools_dropped.emit()
                self._pass(self.fallback_system, None)
        except Exception as err:
            if not self.cancelled.is_set():
                self.failed.emit(str(err) or type(err).__name__)

    def _pass(self, system, tools):
        stream = None
        try:
            stream = self._stream(system, tools)
            for text in stream:
                if self.cancelled.is_set():
                    break
                if text:
                    self.chunk.emit(text)
        finally:
            if stream is not None:
                stream.close()
