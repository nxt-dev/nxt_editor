"""The tools the assistant uses to look at, change and run the graph.

The same tools are given to every provider: through the provider's own
tool calling for API keys, ChatGPT, Grok and local models, and through the
editor's MCP server (see mcp_server) for a Claude Code sign in. Each tool
runs on the editor's main thread, as the graph is not thread safe, and
tells the panel what it did so the chat can show it.

Looking needs nothing turned on. Changing the graph needs "Edit graph",
and running code needs "Run code", both toggles under the message box.
All the changes in one reply are one undo step.

Files are read as in Claude Code: the open graph's folder is free to read,
and anywhere else the user is asked first (see memory). Modules the graph
imports can be inspected without running them (see files).
"""
# Builtin
import collections
import fnmatch
import json
import logging
import os
import sys
import threading
import time

# External
from Qt import QtCore, QtWidgets

# Internal
import nxt_editor
from nxt import DATA_STATE, nxt_path
from nxt.nxt_log import COMPINFO
from nxt.nxt_node import INTERNAL_ATTRS
from nxt_editor.ai import files, graph_actions
from nxt_editor.ai.memory import Memory, inside, norm

logger = logging.getLogger(nxt_editor.LOGGER_NAME)

READ, SHOW, EDIT, RUN, MEMORY = 'read', 'show', 'edit', 'run', 'memory'
# What the user answers when asked to let the assistant read a folder.
ONCE, ALWAYS, DENY = 'once', 'always', 'deny'
MAX_TEXT = 20000
MAX_LOG_LINES = 400
CALL_TIMEOUT = 600

INSTRUCTIONS = '''
You have tools for the graph open in the nxt editor. Look before you
answer: read the nodes the question is about rather than guessing, and
search when you do not know where something is. Paths are absolute node
paths such as /parent/child.

When the user asks for changes and you have change_graph, make them with
it; never only describe them. Check what a change did when it matters.
When you have the run tools, run what you changed if the user wants it
tested, and read the output. Without those tools, say what the user can
do instead. Keep your answer short and say what you changed.

You can read code on this computer with list_files, read_file and
search_files. The open graph's folder is free to read; anywhere else the
user is asked first, so give a short reason. Use inspect_import and
get_node_imports to see what the modules a graph uses offer, rather than
guessing at their functions.

When the user tells you something to keep in mind for later chats, or
asks you to remember it, save it with remember as one short note.
'''


def instructions():
    return INSTRUCTIONS.strip()


class Tool(object):
    def __init__(self, name, kind, description, schema, handler, label,
                 needs_graph=True):
        self.name = name
        self.kind = kind
        self.description = description
        self.schema = schema
        self.handler = handler
        # How the chat says what it did, from the arguments.
        self.label = label
        self.needs_graph = needs_graph


def _obj(properties=None, required=None):
    schema = {'type': 'object', 'properties': properties or {}}
    if required:
        schema['required'] = list(required)
    return schema


PATH = {'type': 'string', 'description': 'An absolute node path, such as '
                                         '/rig/arm'}
PATHS = {'type': 'array', 'items': {'type': 'string'},
         'description': 'Absolute node paths'}
READ_REASON = {'type': 'string', 'description': 'Why you want to read '
                                                'there, in one short '
                                                'sentence, shown to the '
                                                'user if they are asked'}
READ_ABOUT = {'type': 'string', 'description': 'What the folder holds, in '
                                               'a few words, such as "the '
                                               'rig library". Remembered '
                                               'if the user always allows '
                                               'it'}


def _place(path):
    """A file or folder, short enough for the chat."""
    if not path:
        return ''
    path = str(path).rstrip('/\\')
    return os.path.basename(path) or path


class _Tee(object):
    """Passes writes on to a stream, keeping a copy."""

    def __init__(self, stream, kept):
        self.stream = stream
        self.kept = kept

    def write(self, text):
        self.kept.append(text)
        if self.stream is not None:
            return self.stream.write(text)
        return len(text)

    def __getattr__(self, name):
        return getattr(self.stream, name)


class RecentLog(logging.Handler):
    """Keeps the last lines the editor logged, for get_output_log and to
    give back what a run printed."""

    def __init__(self, size=2000):
        super(RecentLog, self).__init__(level=logging.DEBUG)
        self.lines = collections.deque(maxlen=size)
        self.count = 0
        self.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

    def emit(self, record):
        try:
            text = self.format(record)
        except Exception:
            return
        self.count += 1
        self.lines.append((self.count, record.levelno, text))

    def since(self, count):
        return [line for line in self.lines if line[0] > count]


_log = None


def recent_log():
    """The editor's recent log, started on first use."""
    global _log
    if _log is None:
        _log = RecentLog()
        # The editor's logger is under nxt's, so this hears both.
        target = logging.getLogger('nxt')
        if _log not in target.handlers:
            target.addHandler(_log)
    return _log


def _clip(text, limit=MAX_TEXT):
    if len(text) <= limit:
        return text
    return text[:limit] + '\n... ({} more characters)'.format(
        len(text) - limit)


def _short(paths, most=3):
    paths = list(paths or [])
    if len(paths) <= most:
        return ', '.join(paths) or 'nothing'
    return '{} and {} more'.format(', '.join(paths[:most]),
                                   len(paths) - most)


class ToolError(Exception):
    pass


class Toolbox(QtCore.QObject):
    """The tools for one reply.

    :param model: the StageModel of the open graph, or None
    :param can_edit: True to offer change_graph
    :param can_run: True to offer the run tools
    :param memory: the Memory to read and save notes and folders in
    :param chat_folders: a set of the folders allowed for this chat only,
        kept by the chat and added to as the user allows more
    :param ask_access: called with (folder, reason) when the assistant
        wants to read somewhere new; gives back ONCE, ALWAYS or DENY.
        Without it, nowhere new can be read.
    """
    # {'id', 'name', 'kind', 'label', 'state': 'running', 'done' or
    # 'failed', 'detail'}
    activity = QtCore.Signal(dict)
    _invoke = QtCore.Signal(object)

    def __init__(self, model, can_edit=False, can_run=False, parent=None,
                 memory=None, chat_folders=None, ask_access=None):
        super(Toolbox, self).__init__(parent)
        self.model = model
        self.can_edit = can_edit
        self.can_run = can_run
        self.memory = memory if memory is not None else Memory()
        self.chat_folders = chat_folders if chat_folders is not None \
            else set()
        self.ask_access = ask_access
        # Folders the user said no to in this reply, so it is not asked
        # again and again.
        self.denied = set()
        self.cancelled = threading.Event()
        self.done = []
        self.failed = []
        self.calls = 0
        self._macro = False
        self._running = False
        self._invoke.connect(self._run_job, QtCore.Qt.QueuedConnection)
        self.tools = collections.OrderedDict(
            (tool.name, tool) for tool in self._all_tools())
        recent_log()

    # What is offered
    def available(self):
        allowed = {READ, SHOW, MEMORY}
        if self.can_edit:
            allowed.add(EDIT)
        if self.can_run:
            allowed.add(RUN)
        return [t for t in self.tools.values() if t.kind in allowed and
                (self.model is not None or not t.needs_graph)]

    def anthropic_tools(self):
        return [{'name': t.name, 'description': t.description,
                 'input_schema': t.schema} for t in self.available()]

    def responses_tools(self):
        return [{'type': 'function', 'name': t.name,
                 'description': t.description, 'parameters': t.schema}
                for t in self.available()]

    def chat_completions_tools(self):
        return [{'type': 'function',
                 'function': {'name': t.name, 'description': t.description,
                              'parameters': t.schema}}
                for t in self.available()]

    def mcp_tools(self):
        return [{'name': t.name, 'description': t.description,
                 'inputSchema': t.schema} for t in self.available()]

    # Calling
    def call(self, name, args):
        """Run a tool from any thread. Gives back (text, is_error)."""
        if isinstance(args, str):
            try:
                args = json.loads(args or '{}')
            except ValueError as err:
                return 'The arguments were not JSON: {}'.format(err), True
        args = args if isinstance(args, dict) else {}
        app = QtWidgets.QApplication.instance()
        if app is None or QtCore.QThread.currentThread() is app.thread():
            return self._call(name, args)
        job = {'name': name, 'args': args, 'event': threading.Event(),
               'result': ('The editor did not answer.', True)}
        self._invoke.emit(job)
        end = time.time() + CALL_TIMEOUT
        while not job['event'].wait(0.1):
            if time.time() > end:
                return 'The editor took too long to answer.', True
        return job['result']

    def _run_job(self, job):
        if self._running:
            # A tool is waiting on the user or a build. One at a time, so
            # this one goes after it rather than inside it.
            QtCore.QTimer.singleShot(30, lambda: self._run_job(job))
            return
        self._running = True
        try:
            job['result'] = self._call(job['name'], job['args'])
        finally:
            self._running = False
            job['event'].set()

    def _call(self, name, args):
        tool = self.tools.get(name)
        offered = tool in self.available() if tool else False
        self.calls += 1
        call_id = self.calls
        label = name
        if tool:
            try:
                label = tool.label(args)
            except Exception:
                label = name
        if self.cancelled.is_set():
            return 'The user stopped the reply.', True
        if not offered:
            if tool and tool.kind == EDIT:
                text = ('Changing the graph is turned off. Ask the user to '
                        'turn on "Edit graph" under the message box.')
            elif tool and tool.kind == RUN:
                text = ('Running code is turned off. Ask the user to turn '
                        'on "Run code" under the message box.')
            elif self.model is None and tool and tool.needs_graph:
                text = 'No graph is open.'
            else:
                text = 'There is no tool called {}.'.format(name)
            self._tell(call_id, tool, label, 'failed', text)
            return text, True
        self._tell(call_id, tool, label, 'running')
        try:
            result = tool.handler(args)
        except ToolError as err:
            self._tell(call_id, tool, label, 'failed', str(err))
            return str(err), True
        except Exception as err:
            logger.exception('AI tool {} failed'.format(name))
            text = '{} failed: {}'.format(name, err)
            self._tell(call_id, tool, label, 'failed', text)
            return text, True
        if not isinstance(result, str):
            result = json.dumps(result, indent=1, default=str)
        self._tell(call_id, tool, label, 'done')
        return _clip(result), False

    def _tell(self, call_id, tool, label, state, detail=''):
        self.activity.emit({'id': call_id,
                            'name': tool.name if tool else '',
                            'kind': tool.kind if tool else READ,
                            'label': label, 'state': state,
                            'detail': detail})

    def finish(self):
        """End the reply: its changes become one undo step."""
        if self._macro:
            self._macro = False
            try:
                self.model.undo_stack.endMacro()
            except RuntimeError:
                pass

    def cancel(self):
        self.cancelled.set()

    # Helpers
    @property
    def comp(self):
        return self.model.comp_layer

    def path(self, args, key='path', required=True):
        path = args.get(key)
        if path in (None, ''):
            if required:
                raise ToolError('"{}" is needed'.format(key))
            return None
        path = str(path).strip()
        if not path.startswith('/'):
            path = '/' + path
        return path.rstrip('/') or '/'

    def graph_folder(self):
        top = self.model.top_layer.real_path if self.model else None
        return os.path.dirname(top) if top else None

    def may_read(self, path):
        folder = self.graph_folder()
        if folder and inside(path, folder):
            return True
        if any(inside(path, f) for f in self.chat_folders):
            return True
        return self.memory.allowed(path)

    def readable(self, args, key='path', reason=''):
        """The path asked for, once the user lets it be read."""
        path = str(args.get(key) or '').strip()
        if not path:
            folder = self.graph_folder()
            if not folder:
                raise ToolError('Give a "{}"; the graph is not saved, so '
                                'there is no folder of its own'.format(key))
            path = folder
        path = os.path.expanduser(path)
        if not os.path.isabs(path):
            base = self.graph_folder()
            if not base:
                raise ToolError('Give a full path; the graph is not saved, '
                                'so there is no folder to start from')
            path = os.path.join(base, path)
        path = os.path.normpath(path)
        if self.may_read(path):
            return path
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        if not os.path.isdir(folder):
            raise ToolError('There is no folder {}'.format(folder))
        if norm(folder) in self.denied:
            raise ToolError('The user did not let you read {}.'.format(
                folder))
        answer = DENY
        if self.ask_access is not None and not self.cancelled.is_set():
            reason = str(args.get('reason') or reason or '').strip()
            answer = self.ask_access(folder, reason)
        if answer == ALWAYS:
            self.memory.allow(folder, str(args.get('about') or ''))
        elif answer == ONCE:
            self.chat_folders.add(folder)
        else:
            self.denied.add(norm(folder))
            raise ToolError('The user did not let you read {}. Do not ask '
                            'for it again in this reply.'.format(folder))
        return path

    def require(self, path):
        if path != nxt_path.WORLD and not self.model.node_exists(path):
            raise ToolError('There is no node {}'.format(path))

    def layer_info(self, layer):
        model = self.model
        info = {'alias': layer.get_alias(),
                'file': layer.real_path or None,
                'target': layer is model.target_layer,
                'top': layer is model.top_layer}
        for key, getter in (('muted', 'get_muted'), ('soloed', 'get_soloed'),
                            ('locked', 'get_locked')):
            try:
                if getattr(layer, getter)():
                    info[key] = True
            except Exception:
                pass
        try:
            if layer.real_path in model.effected_layers:
                info['unsaved_changes'] = True
        except Exception:
            pass
        return info

    def node_flags(self, path):
        model = self.model
        flags = []
        if model.get_is_node_start(path, self.comp):
            flags.append('start point')
        if model.get_node_enabled(path, self.comp) is False:
            flags.append('disabled')
        instance = model.get_node_instance_path(path, self.comp)
        if instance:
            flags.append('instance of ' + instance)
        exec_in = model.get_node_exec_in(path, self.comp)
        if exec_in:
            flags.append('runs after ' + exec_in)
        if model.node_is_implied(path, self.comp):
            flags.append('implied')
        return flags

    # The tools
    def _all_tools(self):
        return [
            Tool('get_graph_overview', READ,
                 'What is open: the layers (strongest first, which is the '
                 'target the changes go to), how many nodes there are, the '
                 'top level nodes, the start points and what the user has '
                 'selected. Start here.',
                 _obj(), self.get_graph_overview,
                 lambda a: 'Looked over the graph'),
            Tool('list_nodes', READ,
                 'The nodes under a path, as an indented tree with what '
                 'each one is (start point, disabled, instance, exec '
                 'input). depth 1 is just the children.',
                 _obj({'path': dict(PATH, default='/'),
                       'depth': {'type': 'integer', 'default': 2},
                       'limit': {'type': 'integer', 'default': 300}}),
                 self.list_nodes,
                 lambda a: 'Listed {}'.format(a.get('path') or '/')),
            Tool('get_node', READ,
                 'Everything about one node: its attributes with their '
                 'values and where each comes from (local, inherited from '
                 'its parent, or from its instance), its code, comment, '
                 'instance, exec input, children and the layers that '
                 'change it. resolved gives values with ${tokens} worked '
                 'out.',
                 _obj({'path': PATH,
                       'resolved': {'type': 'boolean', 'default': False},
                       'code': {'type': 'boolean', 'default': True}},
                      ['path']),
                 self.get_node, lambda a: 'Read {}'.format(a.get('path'))),
            Tool('find_nodes', READ,
                 'Search the graph. text is matched (ignoring case) against '
                 'node names, attribute names and values, code and '
                 'comments, or only the places in "where". Wildcards such '
                 'as *ctrl* match names.',
                 _obj({'text': {'type': 'string'},
                       'where': {'type': 'array', 'items': {
                           'type': 'string',
                           'enum': ['name', 'attrs', 'code', 'comment']}},
                       'under': dict(PATH, description='Only search under '
                                                       'this path'),
                       'limit': {'type': 'integer', 'default': 50}},
                      ['text']),
                 self.find_nodes,
                 lambda a: 'Searched for "{}"'.format(a.get('text'))),
            Tool('get_build_order', READ,
                 'The order the nodes run in when the build starts at a '
                 'start point. Without start, the first start point.',
                 _obj({'start': PATH}), self.get_build_order,
                 lambda a: 'Checked the build order{}'.format(
                     ' from ' + a['start'] if a.get('start') else '')),
            Tool('find_problems', READ,
                 'Nodes with problems: a broken instance, an exec input '
                 'that is not there, or other errors the editor shows.',
                 _obj({'under': PATH}), self.find_problems,
                 lambda a: 'Checked for problems'),
            Tool('get_output_log', READ,
                 'The last lines of the editor\'s output log: what nodes '
                 'printed and any errors.',
                 _obj({'lines': {'type': 'integer', 'default': 80},
                       'errors_only': {'type': 'boolean',
                                       'default': False}}),
                 self.get_output_log, lambda a: 'Read the output log'),
            Tool('select_nodes', SHOW,
                 'Select nodes in the graph and frame them, to show the '
                 'user what you mean.',
                 _obj({'paths': PATHS}, ['paths']), self.select_nodes,
                 lambda a: 'Selected {}'.format(_short(a.get('paths')))),
            Tool('change_graph', EDIT,
                 'Make changes to the graph, applied in order. Each change '
                 'is an object with "action" and the fields it needs:\n' +
                 graph_actions.action_reference(),
                 _obj({'changes': {
                     'type': 'array',
                     'items': {'type': 'object', 'properties': {
                         'action': {'type': 'string',
                                    'enum': graph_actions.ACTIONS}},
                         'required': ['action']}}}, ['changes']),
                 self.change_graph,
                 lambda a: 'Changed the graph ({} change{})'.format(
                     len(a.get('changes') or []),
                     '' if len(a.get('changes') or []) == 1 else 's')),
            Tool('run_nodes', RUN,
                 'Run nodes\' code in the editor (or the host, such as '
                 'Maya), in the order given, and give back what they '
                 'printed and any error.',
                 _obj({'paths': PATHS}, ['paths']), self.run_nodes,
                 lambda a: 'Ran {}'.format(_short(a.get('paths')))),
            Tool('run_build', RUN,
                 'Run the build from a start point, as the Build button '
                 'does, and give back what it printed and any error.',
                 _obj({'start': PATH}), self.run_build,
                 lambda a: 'Ran the build{}'.format(
                     ' from ' + a['start'] if a.get('start') else '')),
            Tool('run_snippet', RUN,
                 'Run some Python as if it were the code of a node, to try '
                 'something or look at the host (such as the Maya scene). '
                 'self is that node. Print what you want to see.',
                 _obj({'code': {'type': 'string'},
                       'node': dict(PATH, description='The node it runs '
                                                      'as, / by default')},
                      ['code']),
                 self.run_snippet, lambda a: 'Ran a snippet'),
            Tool('list_files', READ,
                 'List the files in a folder on this computer. The open '
                 'graph\'s folder is free to read; for anywhere else the '
                 'user is asked first, so say why in reason.',
                 _obj({'path': {'type': 'string', 'description':
                                'A folder, or a path relative to the '
                                'graph\'s folder'},
                       'pattern': {'type': 'string', 'default': '*'},
                       'recursive': {'type': 'boolean', 'default': False},
                       'reason': READ_REASON, 'about': READ_ABOUT}),
                 self.list_files,
                 lambda a: 'Listed {}'.format(_place(a.get('path'))),
                 needs_graph=False),
            Tool('read_file', READ,
                 'Read a text file, with line numbers. Long files are read '
                 'a part at a time with start_line and end_line.',
                 _obj({'path': {'type': 'string'},
                       'start_line': {'type': 'integer', 'default': 1},
                       'end_line': {'type': 'integer'},
                       'reason': READ_REASON, 'about': READ_ABOUT}, ['path']),
                 self.read_file,
                 lambda a: 'Read {}'.format(_place(a.get('path'))),
                 needs_graph=False),
            Tool('search_files', READ,
                 'Search the files under a folder for text (or a regular '
                 'expression with regex), giving each line that matches.',
                 _obj({'text': {'type': 'string'},
                       'path': {'type': 'string'},
                       'pattern': {'type': 'string', 'default': '*',
                                   'description': 'Only files matching '
                                                  'this, such as *.py'},
                       'regex': {'type': 'boolean', 'default': False},
                       'reason': READ_REASON, 'about': READ_ABOUT}, ['text']),
                 self.search_files,
                 lambda a: 'Searched {} for "{}"'.format(
                     _place(a.get('path')) or 'the graph\'s folder',
                     a.get('text')),
                 needs_graph=False),
            Tool('inspect_import', READ,
                 'What a module the graph can import offers: where it is, '
                 'its submodules, functions and classes with their '
                 'arguments. With member (such as "Joint" or '
                 '"Joint.create") gives that one in full, with its source. '
                 'It is not run to find out, unless it is already '
                 'imported.',
                 _obj({'module': {'type': 'string', 'description':
                                  'A module, such as maya.cmds or '
                                  'rig_lib.joints'},
                       'member': {'type': 'string'}}, ['module']),
                 self.inspect_import,
                 lambda a: 'Inspected {}{}'.format(
                     a.get('module'),
                     '.' + a['member'] if a.get('member') else ''),
                 needs_graph=False),
            Tool('get_node_imports', READ,
                 'The modules a node\'s code imports (and its descendants\' '
                 'with children), and where each one is found, or that it '
                 'is missing.',
                 _obj({'path': PATH,
                       'children': {'type': 'boolean', 'default': False}},
                      ['path']),
                 self.get_node_imports,
                 lambda a: 'Checked the imports of {}'.format(a.get('path'))),
            Tool('remember', MEMORY,
                 'Save a short note to remember in every later chat, such '
                 'as how the user likes things done or what a folder '
                 'holds. The user can see and delete it in the settings.',
                 _obj({'note': {'type': 'string'}}, ['note']),
                 self.remember,
                 lambda a: 'Remembered "{}"'.format(
                     _clip(str(a.get('note') or ''), 60)),
                 needs_graph=False),
            Tool('forget', MEMORY,
                 'Forget a note, by the id it is listed with, when it is '
                 'wrong or the user asks.',
                 _obj({'id': {'type': 'string'}}, ['id']),
                 self.forget, lambda a: 'Forgot a note', needs_graph=False),
        ]

    # Files and imports
    def list_files(self, args):
        path = self.readable(args)
        try:
            return files.list_files(path, args.get('pattern') or '*',
                                    bool(args.get('recursive')))
        except files.FileError as err:
            raise ToolError(str(err))

    def read_file(self, args):
        path = self.readable(args)
        try:
            return files.read_file(path, args.get('start_line') or 1,
                                   args.get('end_line'))
        except files.FileError as err:
            raise ToolError(str(err))

    def search_files(self, args):
        path = self.readable(args)
        try:
            return files.search_files(path, args.get('text'),
                                      args.get('pattern') or '*',
                                      regex=bool(args.get('regex')))
        except files.FileError as err:
            raise ToolError(str(err))

    def inspect_import(self, args):
        name = str(args.get('module') or '').strip()
        if not name:
            raise ToolError('Give a "module"')
        try:
            return files.inspect_module(name, args.get('member') or None)
        except files.FileError as err:
            raise ToolError(str(err))
        except SyntaxError as err:
            raise ToolError('{} does not parse: {}'.format(name, err))

    def get_node_imports(self, args):
        path = self.path(args)
        self.require(path)
        paths = [path]
        if args.get('children'):
            paths += list(self.comp.descendants(path))
        result = {}
        for node in paths:
            code = self.model.get_node_code_string(node, layer=self.comp)
            names = files.imports_in(code)
            if names:
                result[node] = files.where_imports_go(names)
        return result or 'No imports.'

    # Memory
    def remember(self, args):
        try:
            note = self.memory.add(args.get('note') or '')
        except ValueError as err:
            raise ToolError(str(err))
        return 'Remembered as note {}.'.format(note['id'])

    def forget(self, args):
        if not self.memory.remove(str(args.get('id') or '')):
            raise ToolError('There is no note {}'.format(args.get('id')))
        return 'Forgotten.'

    def get_graph_overview(self, args):
        model = self.model
        paths = list(self.comp.descendants(nxt_path.WORLD))
        tops = []
        for path in model.get_children(nxt_path.WORLD, ordered=True,
                                       include_implied=True):
            tops.append({'path': path,
                         'descendants': len(self.comp.descendants(path)),
                         'flags': self.node_flags(path)})
        return {'file': model.top_layer.real_path or '(not saved)',
                'layers': [self.layer_info(l)
                           for l in model.stage._sub_layers],
                'node_count': len(paths),
                'top_level_nodes': tops,
                'start_points': list(model.get_start_nodes()),
                'selected': list(model.selection or []),
                'build_running': bool(model.executing)}

    def list_nodes(self, args):
        root = self.path(args, required=False) or nxt_path.WORLD
        self.require(root)
        depth = max(1, int(args.get('depth') or 2))
        limit = max(1, int(args.get('limit') or 300))
        lines = []
        total = [0]

        def walk(path, level):
            for child in self.model.get_children(path, ordered=True,
                                                 include_implied=True):
                total[0] += 1
                if len(lines) < limit:
                    flags = self.node_flags(child)
                    lines.append('{}{}{}'.format(
                        '  ' * level, child,
                        '  [{}]'.format('; '.join(flags)) if flags else ''))
                if level + 1 < depth:
                    walk(child, level + 1)

        walk(root, 0)
        if not lines:
            return '{} has no children.'.format(root)
        if total[0] > len(lines):
            lines.append('... and {} more'.format(total[0] - len(lines)))
        return '\n'.join(lines)

    def get_node(self, args):
        model = self.model
        path = self.path(args)
        self.require(path)
        comp = self.comp
        state = (DATA_STATE.RESOLVED if args.get('resolved')
                 else DATA_STATE.RAW)
        local = set(model.get_node_local_attr_names(path, comp))
        instanced = set(model.get_node_instanced_attr_names(path, comp))
        attrs = {}
        for name in sorted(model.get_node_attr_names(path, comp)):
            if name in INTERNAL_ATTRS.PROTECTED:
                continue
            value = model.get_node_attr_value(path, name, comp,
                                              data_state=state,
                                              as_string=True)
            if name in local:
                source = 'local'
            elif name in instanced:
                source = 'instance'
            else:
                source = 'inherited from ' + (model.get_node_attr_source_path(
                    path, name, comp) or 'a parent')
            attrs[name] = {'value': value, 'from': source}
        info = {'path': path,
                'flags': self.node_flags(path),
                'comment': model.get_node_comment(path, comp) or None,
                'attrs': attrs,
                'children': list(model.get_children(path, ordered=True,
                                                    include_implied=True)),
                'layers_with_changes': model.get_layers_with_opinion(path)}
        if args.get('code', True):
            code = model.get_node_code_string(path, data_state=state,
                                              layer=comp)
            info['code'] = code or ''
        return info

    def find_nodes(self, args):
        text = str(args.get('text') or '').strip()
        if not text:
            raise ToolError('Give some text to look for')
        where = set(args.get('where') or
                    ['name', 'attrs', 'code', 'comment'])
        under = self.path(args, 'under', required=False)
        limit = max(1, int(args.get('limit') or 50))
        model, comp = self.model, self.comp
        needle = text.lower()
        pattern = needle if any(c in needle for c in '*?[') else None
        found = []
        paths = sorted(comp.descendants(under or nxt_path.WORLD))
        for path in paths:
            hits = []
            name = nxt_path.node_name_from_node_path(path).lower()
            if 'name' in where and (
                    fnmatch.fnmatch(name, pattern) if pattern
                    else needle in name):
                hits.append('name')
            if 'attrs' in where and not pattern:
                for attr in model.get_node_attr_names(path, comp):
                    if attr in INTERNAL_ATTRS.PROTECTED:
                        continue
                    value = model.get_node_attr_value(
                        path, attr, comp, data_state=DATA_STATE.RAW,
                        as_string=True) or ''
                    if needle in attr.lower() or needle in value.lower():
                        hits.append('attr ' + attr)
                        break
            if 'code' in where and not pattern:
                code = model.get_node_code_string(path, layer=comp) or ''
                for number, line in enumerate(code.split('\n'), 1):
                    if needle in line.lower():
                        hits.append('code line {}: {}'.format(
                            number, line.strip()[:120]))
                        break
            if 'comment' in where and not pattern:
                comment = model.get_node_comment(path, comp) or ''
                if needle in comment.lower():
                    hits.append('comment')
            if hits:
                found.append('{}  ({})'.format(path, '; '.join(hits)))
                if len(found) >= limit:
                    found.append('... stopped at {}'.format(limit))
                    break
        return '\n'.join(found) if found else 'Nothing matched.'

    def get_build_order(self, args):
        model = self.model
        start = self.path(args, 'start', required=False)
        starts = list(model.get_start_nodes())
        if not start:
            if not starts:
                raise ToolError('There are no start points')
            start = starts[0]
        self.require(start)
        return {'start': start, 'start_points': starts,
                'order': list(model.get_exec_order(start) or [])}

    def find_problems(self, args):
        under = self.path(args, 'under', required=False)
        found = {}
        for path in self.comp.descendants(under or nxt_path.WORLD):
            errors = self.model.get_node_error(path)
            if errors:
                found[path] = [str(e) for e in errors]
        return found or 'No problems found.'

    def get_output_log(self, args):
        lines = max(1, min(int(args.get('lines') or 80), MAX_LOG_LINES))
        entries = list(recent_log().lines)
        if args.get('errors_only'):
            entries = [e for e in entries if e[1] >= logging.WARNING]
        text = '\n'.join(e[2] for e in entries[-lines:])
        return text or 'The log is empty.'

    def select_nodes(self, args):
        paths = args.get('paths') or []
        if isinstance(paths, str):
            paths = [paths]
        paths = [self.path({'path': p}) for p in paths]
        found = [p for p in paths if self.model.node_exists(p)]
        self.model.set_selection(found)
        if found:
            self.model.frame_items.emit(tuple(found))
        missing = [p for p in paths if p not in found]
        text = 'Selected {}.'.format(_short(found, 10))
        if missing:
            text += ' Not found: {}.'.format(', '.join(missing))
        return text

    def change_graph(self, args):
        changes = args.get('changes')
        if isinstance(changes, dict):
            changes = [changes]
        if not isinstance(changes, list) or not changes:
            raise ToolError('"changes" must be a list of changes')
        if not self._macro:
            self.model.undo_stack.beginMacro('AI Assistant changes')
            self._macro = True
        done, failed = graph_actions.Applier(self.model).apply(changes)
        self.done += done
        self.failed += failed
        lines = ['Done: ' + d for d in done] + \
            ['Could not: ' + f for f in failed]
        return '\n'.join(lines) or 'Nothing changed.'

    # Running
    def _run(self, start_build):
        model = self.model
        if model.executing:
            raise ToolError('A build is already running. Wait for it, or '
                            'ask the user to stop it.')
        log = recent_log()
        mark = log.count
        started = time.time()
        error = None
        # What the nodes print, as well as what they log.
        printed = []
        streams = sys.stdout, sys.stderr
        sys.stdout = _Tee(streams[0], printed)
        sys.stderr = _Tee(streams[1], printed)
        try:
            try:
                start_build()
            except Exception as err:
                error = '{}: {}'.format(type(err).__name__, err)
            # A host runs it straight away, standalone it may still be going.
            end = time.time() + CALL_TIMEOUT
            while model.executing and not model.build_paused and                     time.time() < end and not self.cancelled.is_set():
                QtWidgets.QApplication.processEvents()
                time.sleep(0.01)
        finally:
            sys.stdout, sys.stderr = streams
        # Leave out the composite's bookkeeping.
        entries = [e for e in log.since(mark) if e[1] != COMPINFO]
        result = {'seconds': round(time.time() - started, 2)}
        if model.executing and model.build_paused:
            result['state'] = 'paused at a breakpoint, still running'
        elif model.executing:
            result['state'] = 'still running'
        else:
            result['state'] = 'finished'
        if error:
            result['error'] = error
        errors = [e[2] for e in entries if e[1] >= logging.WARNING]
        if errors:
            result['errors'] = errors[-20:]
        text = ''.join(printed).strip()
        if text:
            result['printed'] = _clip(text, 12000)
        result['log'] = _clip('\n'.join(e[2] for e in
                                        entries[-MAX_LOG_LINES:]), 12000)
        return result

    def run_nodes(self, args):
        paths = args.get('paths') or []
        if isinstance(paths, str):
            paths = [paths]
        paths = [self.path({'path': p}) for p in paths]
        for path in paths:
            self.require(path)
        if not paths:
            raise ToolError('Give the paths to run')
        return self._run(lambda: self.model.execute_nodes(paths))

    def run_build(self, args):
        start = self.path(args, 'start', required=False)
        if start:
            self.require(start)
        elif not self.model.get_start_nodes():
            raise ToolError('There are no start points')
        return self._run(lambda: self.model.execute_stage(start))

    def run_snippet(self, args):
        code = str(args.get('code') or '')
        if not code.strip():
            raise ToolError('Give some code to run')
        node = self.path(args, 'node', required=False) or nxt_path.WORLD
        if node != nxt_path.WORLD:
            self.require(node)
        model = self.model
        rt_layer = model.current_rt_layer
        if rt_layer is None:
            # Nothing has run yet, so there is no cache to lose.
            comp = model.stage.build_stage(model.comp_layer.layer_idx())
            rt_layer = model.stage.setup_runtime_layer(comp)
            model.current_rt_layer = rt_layer
        else:
            valid, _bad = model.validate_runtime_layer(
                rt_layer=rt_layer, node_paths=[node])
            if not valid:
                raise ToolError('The cache from the last run does not match '
                                'the graph any more. Ask the user to clear '
                                'the cache (Execute > Clear cache) or run '
                                'a build first.')
        return self._run(lambda: model.execute_snippet(code, node,
                                                       rt_layer=rt_layer))
