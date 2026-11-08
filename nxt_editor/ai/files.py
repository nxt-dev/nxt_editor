"""Reading code for the assistant: files in folders it is let into, and the
modules a graph imports.

Nothing here runs the code it looks at. A module is found on the Python
path the way import would find it, without importing it, and read with
ast. Only a module already imported (as maya.cmds is in Maya) is looked at
live.
"""
# Builtin
import ast
import fnmatch
import importlib.machinery
import inspect
import os
import pkgutil
import re
import sys

MAX_READ_LINES = 2000
MAX_READ_BYTES = 200 * 1024
MAX_SEARCH_BYTES = 2 * 1024 * 1024
MAX_MEMBERS = 300
SKIP_DIRS = {'.git', '.hg', '.svn', '__pycache__', 'node_modules', '.venv',
             'venv', '.mypy_cache', '.pytest_cache', '.idea', '.vscode'}


class FileError(Exception):
    pass


def _binary(path):
    try:
        with open(path, 'rb') as fp:
            return b'\0' in fp.read(8192)
    except OSError:
        return True


def _walk(root, recursive=True):
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and
                         not d.startswith('.'))
        yield folder, dirs, sorted(files)
        if not recursive:
            break


def list_files(path, pattern='*', recursive=False, limit=500):
    if not os.path.isdir(path):
        raise FileError('{} is not a folder'.format(path))
    lines = []
    total = 0
    for folder, dirs, files in _walk(path, recursive):
        rel = os.path.relpath(folder, path)
        prefix = '' if rel == '.' else rel.replace(os.sep, '/') + '/'
        if not recursive:
            for name in dirs:
                total += 1
                if len(lines) < limit:
                    lines.append(prefix + name + '/')
        for name in files:
            if not fnmatch.fnmatch(name, pattern or '*'):
                continue
            total += 1
            if len(lines) < limit:
                try:
                    size = os.path.getsize(os.path.join(folder, name))
                except OSError:
                    size = 0
                lines.append('{}{}  ({:,} bytes)'.format(prefix, name, size))
    if not lines:
        return 'Nothing in {} matches.'.format(path)
    if total > len(lines):
        lines.append('... and {} more'.format(total - len(lines)))
    return '\n'.join(lines)


def read_file(path, start=1, end=None):
    if not os.path.isfile(path):
        raise FileError('There is no file {}'.format(path))
    if _binary(path):
        raise FileError('{} is not a text file'.format(path))
    with open(path, 'r', encoding='utf-8', errors='replace') as fp:
        lines = fp.read().split('\n')
    start = max(1, int(start or 1))
    end = min(len(lines), int(end) if end else start + MAX_READ_LINES - 1)
    shown, size = [], 0
    for number in range(start, end + 1):
        line = '{:>5}  {}'.format(number, lines[number - 1])
        size += len(line)
        if size > MAX_READ_BYTES:
            shown.append('... stopped at {} characters, read on from line '
                         '{}'.format(MAX_READ_BYTES, number))
            break
        shown.append(line)
    else:
        if end < len(lines):
            shown.append('... {} more lines, read on from line {}'.format(
                len(lines) - end, end + 1))
    return '{} ({} lines)\n{}'.format(path, len(lines), '\n'.join(shown))


def search_files(path, text, pattern='*', regex=False, case=False,
                 limit=100):
    if not text:
        raise FileError('Give some text to look for')
    flags = 0 if case else re.IGNORECASE
    try:
        found = re.compile(text if regex else re.escape(text), flags)
    except re.error as err:
        raise FileError('That is not a regular expression: {}'.format(err))
    files = [path] if os.path.isfile(path) else None
    if files is None:
        if not os.path.isdir(path):
            raise FileError('There is no folder {}'.format(path))
        files = (os.path.join(folder, name)
                 for folder, _dirs, names in _walk(path)
                 for name in names if fnmatch.fnmatch(name, pattern or '*'))
    hits = []
    for file_path in files:
        try:
            if os.path.getsize(file_path) > MAX_SEARCH_BYTES or \
                    _binary(file_path):
                continue
            with open(file_path, 'r', encoding='utf-8',
                      errors='replace') as fp:
                for number, line in enumerate(fp, 1):
                    if found.search(line):
                        hits.append('{}:{}: {}'.format(
                            file_path, number, line.strip()[:200]))
                        if len(hits) >= limit:
                            hits.append('... stopped at {}'.format(limit))
                            return '\n'.join(hits)
        except OSError:
            continue
    return '\n'.join(hits) if hits else 'Nothing matched.'


# Imports
def find_spec(name):
    """Where import would find name, without importing it or its
    packages. None when it can not be found."""
    module = sys.modules.get(name)
    if module is not None and getattr(module, '__spec__', None):
        return module.__spec__
    parts = name.split('.')
    search = None
    spec = None
    for i in range(len(parts)):
        sub = '.'.join(parts[:i + 1])
        loaded = sys.modules.get(sub)
        if loaded is not None and getattr(loaded, '__spec__', None):
            spec = loaded.__spec__
        elif search is None and \
                importlib.machinery.BuiltinImporter.find_spec(sub):
            spec = importlib.machinery.BuiltinImporter.find_spec(sub)
        else:
            spec = importlib.machinery.PathFinder.find_spec(sub, search)
        if spec is None:
            return None
        search = spec.submodule_search_locations
        if search is not None:
            search = list(search)
        elif i < len(parts) - 1:
            return None
    return spec


def _signature(node):
    try:
        return '({})'.format(ast.unparse(node.args))
    except Exception:
        return '(...)'


def _doc_line(doc):
    doc = (doc or '').strip()
    return doc.split('\n')[0][:200] if doc else ''


def _static_members(tree):
    members = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            members.append('def {}{}  {}'.format(
                node.name, _signature(node), _doc_line(
                    ast.get_docstring(node))).rstrip())
        elif isinstance(node, ast.ClassDef):
            members.append('class {}  {}'.format(
                node.name, _doc_line(ast.get_docstring(node))).rstrip())
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and (not item.name.startswith('_') or
                             item.name == '__init__'):
                    members.append('    def {}{}  {}'.format(
                        item.name, _signature(item), _doc_line(
                            ast.get_docstring(item))).rstrip())
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) \
                else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    members.append('{} = ...'.format(target.id))
        if len(members) >= MAX_MEMBERS:
            members.append('... more')
            break
    return members


def _find_static(tree, source, dotted):
    """The source of a function or class (or Class.method) in tree."""
    body = tree.body
    found = None
    for part in dotted.split('.'):
        found = None
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)) and node.name == part:
                found = node
                break
        if found is None:
            return None
        body = getattr(found, 'body', [])
    return ast.get_source_segment(source, found)


def _live_members(module):
    members = []
    for name, value in sorted(vars(module).items()):
        if name.startswith('_'):
            continue
        try:
            if inspect.isclass(value):
                members.append('class {}  {}'.format(
                    name, _doc_line(inspect.getdoc(value))).rstrip())
            elif callable(value):
                try:
                    sig = str(inspect.signature(value))
                except (TypeError, ValueError):
                    sig = '(...)'
                members.append('def {}{}  {}'.format(
                    name, sig, _doc_line(inspect.getdoc(value))).rstrip())
            elif inspect.ismodule(value):
                members.append('module {}'.format(name))
            else:
                members.append('{} = {}'.format(name, type(value).__name__))
        except Exception:
            members.append(name)
        if len(members) >= MAX_MEMBERS:
            members.append('... more')
            break
    return members


def inspect_module(name, member=None):
    """What a module has, or one of its members in full."""
    spec = find_spec(name)
    if spec is None:
        raise FileError('{} can not be imported here: it is not on the '
                        'Python path ({})'.format(name, sys.executable))
    origin = spec.origin
    info = {'module': name, 'imported': name in sys.modules,
            'file': origin if origin and os.path.isfile(origin) else origin}
    if spec.submodule_search_locations:
        info['package'] = True
        info['submodules'] = sorted(
            m.name for m in pkgutil.iter_modules(
                list(spec.submodule_search_locations)))[:MAX_MEMBERS]
    module = sys.modules.get(name)
    source = None
    if origin and origin.endswith('.py') and os.path.isfile(origin):
        with open(origin, 'r', encoding='utf-8', errors='replace') as fp:
            source = fp.read()
    if member:
        if module is not None:
            value = module
            try:
                for part in member.split('.'):
                    value = getattr(value, part)
            except AttributeError:
                raise FileError('{} has no {}'.format(name, member))
            result = {'member': '{}.{}'.format(name, member)}
            try:
                result['signature'] = str(inspect.signature(value))
            except (TypeError, ValueError):
                pass
            result['doc'] = inspect.getdoc(value) or ''
            try:
                result['source'] = inspect.getsource(value)
            except (TypeError, OSError):
                pass
            return result
        if source is None:
            raise FileError('{} is compiled, so its members can only be '
                            'seen once it is imported'.format(name))
        found = _find_static(ast.parse(source), source, member)
        if found is None:
            raise FileError('{} has no {} that can be found without '
                            'running it'.format(name, member))
        return {'member': '{}.{}'.format(name, member), 'source': found}
    if module is not None:
        info['doc'] = _doc_line(inspect.getdoc(module))
        info['members'] = _live_members(module)
    elif source is not None:
        try:
            tree = ast.parse(source)
        except SyntaxError as err:
            raise FileError('{} does not parse: {}'.format(origin, err))
        info['doc'] = _doc_line(ast.get_docstring(tree))
        info['members'] = _static_members(tree)
    else:
        info['note'] = ('Compiled or built in, and not imported yet, so '
                        'its members can not be seen without importing it.')
    return info


_IMPORT_LINE = re.compile(r'^\s*(?:from\s+([\w.]+)\s+import|import\s+(.+))')


def imports_in(code):
    """The modules code imports, in order, without repeats."""
    names = []
    try:
        tree = ast.parse(code or '')
    except SyntaxError:
        # Node code can hold ${tokens}; read the import lines instead.
        for line in (code or '').split('\n'):
            match = _IMPORT_LINE.match(line)
            if match and match.group(1):
                names.append(match.group(1))
            elif match:
                for part in match.group(2).split(','):
                    names.append(part.strip().split(' ')[0])
    else:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and \
                    not node.level:
                names.append(node.module)
    seen, ordered = set(), []
    for name in names:
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def where_imports_go(names):
    found = []
    for name in names:
        spec = find_spec(name)
        if spec is None:
            where = 'not found on the Python path'
        elif spec.origin in (None, 'built-in', 'frozen'):
            where = spec.origin or 'namespace package'
        else:
            where = spec.origin
        found.append({'module': name, 'from': where,
                      'imported': name in sys.modules})
    return found
