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
    """Streams one reply, a piece at a time."""
    chunk = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(self, provider, messages, system, model, parent=None):
        super(ChatThread, self).__init__(parent)
        self.provider = provider
        self.messages = messages
        self.system = system
        self.model = model
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        stream = None
        try:
            stream = self.provider.stream_chat(self.messages, self.system,
                                               model=self.model)
            for text in stream:
                if self.cancelled.is_set():
                    break
                self.chunk.emit(text)
        except Exception as err:
            if not self.cancelled.is_set():
                self.failed.emit(str(err) or type(err).__name__)
        finally:
            if stream is not None:
                stream.close()
