"""Optional components: extra packages the editor can use, installed on
demand into a folder of nxt's own.

Two today:

- **Qt (PySide6)**, which Blender and Unreal do not ship. The editor is a
  Qt application, so in those two it cannot open without it.
- **Python Analysis (jedi)**, which makes code completion smarter. Every
  host can use it, and none ships it.

They never go into the host's python, which is usually somewhere an artist
cannot write and which a host update would replace anyway. They go under a
root folder, which is, in order:

- ``NXT_DEPS``, or ``NXT_QT_DEPS`` from when this was only for Qt, for a
  studio that installs them once somewhere shared,
- ``<nxt user dir>/deps``, which is ``~/nxt/deps`` unless ``NXT_USER_DIR``
  says otherwise.

When the shared folder can not be written to, an artist's own installs go
to the second, and anything the studio put in the shared one is used first.

Inside a root, compiled packages go in ``py<major><minor>``, because they
only load in the python they were built for, and pure python ones share
``pure``. On Windows, a host that loads an older Microsoft C++ runtime gets
a compiled folder of its own, ``py311-crt14.29``: PySide6 6.11 is built
with a compiler whose runtime code crashes on the 14.29 runtime Blender 4.2
through 4.5 ship, the moment QtCore loads, so those hosts are given a
PySide6 from before that change, and never share a folder with a host that
has the newer one.

``NXT_DEPS_WHEELS`` names a folder of wheel files, or several joined with
os.pathsep, and makes every install come from there and nowhere else, for
a site with no internet.

Nothing here imports Qt or nxt_editor, because it runs before either can
be imported. The hosts load this file by its path. It also runs as a
script, for installing from a shell::

    python optional_deps.py status
    python optional_deps.py install jedi
"""
import ctypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

DEPS_ENV_VAR = 'NXT_DEPS'
#: The older name, from when only Qt was installed this way. Still read.
LEGACY_DEPS_ENV_VAR = 'NXT_QT_DEPS'
WHEELS_ENV_VAR = 'NXT_DEPS_WHEELS'
USER_DIR_ENV_VAR = 'NXT_USER_DIR'
DCC_ENV_VAR = 'NXT_DCC'

#: The folder pure python components share, inside a root.
PURE_FOLDER = 'pure'
#: Where an install is put together before it replaces what was there.
STAGING_FOLDER = '.staging'
#: Where an update waits when the old one is in use, until the next start.
PENDING_FOLDER = '.pending'
#: Names which component a pending folder holds.
PENDING_MARKER = 'nxt_component.txt'
#: How old a staging folder has to be to count as left behind.
STALE_SECONDS = 6 * 60 * 60

#: The first runtime the newer compiler's code is safe on (Visual Studio
#: 2022 17.10).
MODERN_CRT = (14, 40)

#: VerQueryValue's name for the fixed version block.
ROOT_BLOCK = chr(92)


# -- versions ---------------------------------------------------------------

def normalize(name):
    """A distribution name as pip compares them."""
    return re.sub(r'[-_.]+', '-', name).lower()


def split_requirement(requirement):
    """'jedi>=0.19,<0.21' -> ('jedi', '>=0.19,<0.21')"""
    match = re.match(r'\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(.*)$', requirement)
    return match.group(1), match.group(2).split(';')[0].strip()


def version_tuple(version):
    """The release numbers of a version, '6.10.1rc2' -> (6, 10, 1)."""
    match = re.match(r'\s*v?(\d+(?:\.\d+)*)', version or '')
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split('.'))


def _compare(a, b):
    width = max(len(a), len(b))
    a = a + (0,) * (width - len(a))
    b = b + (0,) * (width - len(b))
    return (a > b) - (a < b)


_OPERATORS = {
    '>=': lambda c: c >= 0, '>': lambda c: c > 0, '<=': lambda c: c <= 0,
    '<': lambda c: c < 0, '==': lambda c: c == 0, '!=': lambda c: c != 0,
}


def in_range(version, spec):
    """Whether a version is one a spec such as '>=0.19,<0.21' allows."""
    have = version_tuple(version)
    if not have:
        return False
    for clause in filter(None, (c.strip() for c in spec.split(','))):
        match = re.match(r'(>=|<=|==|!=|>|<)\s*(.+)$', clause)
        if not match:
            continue
        op, wanted = match.groups()
        if not _OPERATORS[op](_compare(have, version_tuple(wanted))):
            return False
    return True


def too_old(version, spec):
    """Whether a version is below the lowest a spec allows."""
    have = version_tuple(version)
    for clause in filter(None, (c.strip() for c in spec.split(','))):
        match = re.match(r'(>=|>)\s*(.+)$', clause)
        if match and _compare(have, version_tuple(match.group(2))) < (
                0 if match.group(1) == '>=' else 1):
            return True
    return False


def describe_range(spec):
    """'>=0.19,<0.21' -> '0.19 or newer, before 0.21', for people."""
    parts = []
    for clause in filter(None, (c.strip() for c in spec.split(','))):
        match = re.match(r'(>=|<=|==|!=|>|<)\s*(.+)$', clause)
        if not match:
            continue
        op, version = match.groups()
        parts.append({'>=': '{} or newer', '>': 'newer than {}',
                      '<': 'before {}', '<=': '{} or older',
                      '==': 'exactly {}', '!=': 'not {}'}[op].format(version))
    return ', '.join(parts)


class Component(object):
    """One optional package, and what nxt knows about it."""

    def __init__(self, id, name, description, requirement, module,
                 dists=None, compiled=False, hosts=None, size='',
                 legacy_requirement=None, setup_name=None, setup_extra=None):
        """
        :param id: short name, for the command line and preferences
        :param name: what the dialog calls it
        :param description: one line saying what it is for
        :param requirement: what pip is asked for, with the range of
            versions this nxt works with
        :param module: the name it is imported by
        :param dists: the distribution names that count as installed, the
            requirement's own when None
        :param compiled: whether it has compiled code, and so needs a
            folder per python version
        :param hosts: the hosts that need it, every one when None
        :param size: roughly how much it downloads
        :param legacy_requirement: what a host with an old C++ runtime gets
        :param setup_name: its name in setup.py, whose range has to match
        :param setup_extra: the setup.py extra it is listed under, if any
        """
        self.id = id
        self.name = name
        self.description = description
        self.requirement = requirement
        self.module = module
        self.project, self.spec = split_requirement(requirement)
        self.dists = tuple(normalize(d) for d in (dists or (self.project,)))
        self.compiled = compiled
        self.hosts = hosts
        self.size = size
        self.legacy_requirement = legacy_requirement
        self.setup_name = setup_name or self.project
        self.setup_extra = setup_extra

    def __repr__(self):
        return 'Component({!r})'.format(self.id)

    def needed_in(self, host):
        return self.hosts is None or host in self.hosts


PYSIDE6 = Component(
    'pyside6', 'Qt (PySide6)',
    'The toolkit the editor window is built with.',
    # The same range nxt_editor's package requires.
    'pyside6-essentials>=6,<6.12', 'PySide6',
    dists=('pyside6-essentials', 'pyside6'), compiled=True,
    hosts=('blender', 'unreal'), size='about 80 MB',
    # 6.10 is the last PySide6 built with a compiler whose code the 14.29
    # runtime can run; 6.11 crashes in std::mutex as QtCore loads. Checked
    # in Blender 4.2 and 4.5.
    legacy_requirement='pyside6-essentials>=6,<6.11', setup_name='PySide6')

JEDI = Component(
    'jedi', 'Python Analysis (jedi)',
    'Smarter code completion: what a call returns, what a variable holds.',
    'jedi>=0.19,<0.21', 'jedi', size='about 5 MB', setup_extra='completion')

#: Every component, in the order the dialog shows them.
COMPONENTS = (JEDI, PYSIDE6)


def component(component_id):
    for each in COMPONENTS:
        if each.id == component_id:
            return each
    raise KeyError('No optional component called {!r}. There are: {}'.format(
        component_id, ', '.join(c.id for c in COMPONENTS)))


# -- the C++ runtime ----------------------------------------------------------

def loaded_crt_version():
    """The version of the C++ runtime this process has loaded, on Windows.

    Read from the msvcp140.dll the host already has in memory, which is
    the one PySide6 will be given, not whatever the system has installed.

    :return: (major, minor, build), or None when there is nothing to ask
    """
    if sys.platform != 'win32':
        return None
    try:
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        handle = kernel32.GetModuleHandleW('msvcp140.dll')
        if not handle:
            return None
        path = ctypes.create_unicode_buffer(32768)
        kernel32.GetModuleFileNameW(wintypes.HMODULE(handle), path, 32768)
        version = ctypes.WinDLL('version')
        size = version.GetFileVersionInfoSizeW(path.value, None)
        if not size:
            return None
        data = ctypes.create_string_buffer(size)
        if not version.GetFileVersionInfoW(path.value, 0, size, data):
            return None
        info = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version.VerQueryValueW(data, ROOT_BLOCK, ctypes.byref(info),
                                      ctypes.byref(length)):
            return None
        # VS_FIXEDFILEINFO: signature, struct version, then the version.
        words = ctypes.cast(info, ctypes.POINTER(wintypes.DWORD))
        most, least = words[2], words[3]
        return most >> 16, most & 0xffff, least >> 16
    except Exception:
        return None


def is_legacy_crt(crt):
    return crt is not None and tuple(crt[:2]) < MODERN_CRT


def requirement(comp, crt=None):
    """What pip is asked for, for a host with this C++ runtime."""
    if comp.legacy_requirement and is_legacy_crt(crt):
        return comp.legacy_requirement
    return comp.requirement


def wanted_spec(comp, crt=None):
    return split_requirement(requirement(comp, crt))[1]


# -- folders ------------------------------------------------------------------

def user_root():
    user_dir = os.environ.get(USER_DIR_ENV_VAR) or os.path.expanduser(
        os.path.join('~', 'nxt'))
    return os.path.join(user_dir, 'deps')


def shared_root():
    """The root a studio set, or None."""
    return (os.environ.get(DEPS_ENV_VAR) or
            os.environ.get(LEGACY_DEPS_ENV_VAR) or None)


def roots():
    """Every root that is looked in, first wins."""
    found = []
    for root in (shared_root(), user_root()):
        if root and os.path.normcase(os.path.abspath(root)) not in [
                os.path.normcase(os.path.abspath(r)) for r in found]:
            found.append(root)
    return found


def writable(path):
    """Whether files can be made in a folder, or in the nearest folder
    above it that exists.

    Asked by trying, because the permission bits of a network share do not
    say what its server will allow.
    """
    path = os.path.abspath(path)
    while not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            return False
        path = parent
    try:
        handle, probe = tempfile.mkstemp(prefix='.nxt_write_test_', dir=path)
    except (IOError, OSError):
        return False
    os.close(handle)
    try:
        os.remove(probe)
    except OSError:
        pass
    return True


def install_root():
    """Where installs go: the shared root, unless it exists and can not be
    written to, and then the user's own.
    """
    shared = shared_root()
    if shared and (not os.path.isdir(shared) or writable(shared)):
        return shared
    return user_root()


def python_tag(crt=None):
    name = 'py%d%d' % sys.version_info[:2]
    if is_legacy_crt(crt):
        name += '-crt%d.%d' % tuple(crt[:2])
    return name


def folder_name(comp, crt=None):
    return python_tag(crt) if comp.compiled else PURE_FOLDER


def folder(comp, root=None, crt=None):
    """Where a component lives in a root, whether or not it is there yet.

    :param root: the install root when None
    :param crt: the loaded C++ runtime, see loaded_crt_version
    """
    return os.path.join(root or install_root(), folder_name(comp, crt))


def folders(comp, crt=None):
    """Every folder a component can be in, first wins."""
    return [folder(comp, root, crt) for root in roots()]


def wheel_dirs():
    value = os.environ.get(WHEELS_ENV_VAR, '')
    return [path for path in value.split(os.pathsep) if path.strip()]


# -- what is there ------------------------------------------------------------

def _distributions(path):
    try:
        from importlib import metadata
    except ImportError:
        return []
    if not os.path.isdir(path):
        return []
    try:
        return list(metadata.distributions(path=[path]))
    except Exception:
        return []


def _dist_name(dist):
    try:
        return normalize(dist.metadata['Name'] or '')
    except Exception:
        return ''


def find_distribution(comp, path):
    """The installed distribution of a component in one folder, or None."""
    for dist in _distributions(path):
        if _dist_name(dist) in comp.dists:
            return dist
    return None


def installed(comp, crt=None):
    """Where nxt's folders have a component, and which version.

    :return: (version, folder), or (None, None)
    """
    for path in folders(comp, crt):
        dist = find_distribution(comp, path)
        if dist is not None:
            return dist.version, path
    return None, None


def elsewhere_version(comp):
    """A version of the component the python has without nxt's help, from
    its own site-packages or a path a studio set up, or None.
    """
    try:
        from importlib import metadata
    except ImportError:
        return None
    ours = set()
    for root in roots():
        for name in os.listdir(root) if os.path.isdir(root) else ():
            ours.add(os.path.normcase(os.path.abspath(os.path.join(root,
                                                                  name))))
    paths = [p for p in sys.path
             if os.path.normcase(os.path.abspath(p or '.')) not in ours]
    for dist in metadata.distributions(path=paths):
        if _dist_name(dist) in comp.dists:
            return dist.version
    return None


def loaded_from(comp):
    """The file a component was imported from, if it has been."""
    module = sys.modules.get(comp.module)
    return getattr(module, '__file__', None) if module else None


def _inside(path, parent):
    path = os.path.normcase(os.path.abspath(path))
    parent = os.path.normcase(os.path.abspath(parent))
    return path == parent or path.startswith(parent.rstrip(os.sep) + os.sep)


def has_qt():
    try:
        import PySide6  # noqa: F401
    except ImportError:
        return False
    return True


def pending(comp, root=None, crt=None):
    """The update waiting for the next start, if there is one."""
    path = os.path.join(root or install_root(), PENDING_FOLDER,
                        folder_name(comp, crt))
    marker = os.path.join(path, PENDING_MARKER)
    if os.path.isfile(marker):
        with open(marker, encoding='utf-8') as handle:
            if handle.read().strip() == comp.id:
                return path
    return None


def current_host():
    """The host nxt is running in, as NXT_DCC names it, or 'standalone'."""
    return os.environ.get(DCC_ENV_VAR) or 'standalone'


class Status(object):
    """What the dialog shows for one component."""
    NOT_NEEDED = 'not_needed'
    NOT_INSTALLED = 'not_installed'
    INSTALLED = 'installed'
    UPDATE = 'update'
    MANAGED = 'managed'
    ELSEWHERE = 'elsewhere'
    RESTART = 'restart'

    def __init__(self, component, state, version=None, folder=None,
                 wanted='', too_old=False):
        self.component = component
        self.state = state
        self.version = version
        #: where it is, or where it would go
        self.folder = folder
        #: the range of versions this nxt works with
        self.wanted = wanted
        #: out of range by being older, rather than newer
        self.too_old = too_old

    @property
    def out_of_range(self):
        return bool(self.version) and not in_range(self.version, self.wanted)

    def __repr__(self):
        return 'Status({}, {}, {})'.format(self.component.id, self.state,
                                           self.version)


def status(comp, host=None, crt=None):
    """Whether a component is there, usable, and wanted here.

    :param host: what current_host() says when None
    :param crt: the loaded C++ runtime, asked for when None
    :rtype: Status
    """
    host = host or current_host()
    if crt is None:
        crt = loaded_crt_version()
    wanted = wanted_spec(comp, crt)
    version, where = installed(comp, crt)
    loaded = loaded_from(comp)
    from_ours = bool(loaded and any(_inside(loaded, f)
                                    for f in folders(comp, crt)))
    if not comp.needed_in(host) and not from_ours:
        return Status(comp, Status.NOT_NEEDED, version, where, wanted)
    if pending(comp, crt=crt):
        return Status(comp, Status.RESTART, version, where, wanted)
    if version is None:
        other = elsewhere_version(comp)
        if other:
            return Status(comp, Status.ELSEWHERE, other, None, wanted)
        return Status(comp, Status.NOT_INSTALLED, None, folder(comp, crt=crt),
                      wanted)
    old = too_old(version, wanted)
    shared = shared_root()
    if shared and _inside(where, shared) and not writable(where):
        return Status(comp, Status.MANAGED, version, where, wanted, old)
    if not in_range(version, wanted):
        return Status(comp, Status.UPDATE, version, where, wanted, old)
    return Status(comp, Status.INSTALLED, version, where, wanted)


def statuses(host=None, crt=None):
    if crt is None:
        crt = loaded_crt_version()
    return [status(c, host, crt) for c in COMPONENTS]


# -- sys.path -----------------------------------------------------------------

def add_to_path(crt=None):
    """Make what is installed importable, in this python. Run at startup.

    The pure folders always, and the compiled folder for this python while
    there is no Qt, since PySide6 is the only compiled component and a
    host's own Qt has to win. Appended rather than put first, so a package
    the host or the studio already provides wins over one installed here.

    :return: the folders added
    """
    if crt is None:
        crt = loaded_crt_version()
    for root in roots():
        try:
            apply_pending(root)
        except Exception as error:
            sys.stderr.write('nxt: could not finish an update in {}: '
                             '{}\n'.format(root, error))
    wanted = [folder(JEDI, root, crt) for root in roots()]
    if not has_qt():
        wanted += [folder(PYSIDE6, root, crt) for root in roots()]
    added = []
    for path in wanted:
        if os.path.isdir(path) and path not in sys.path:
            sys.path.append(path)
            added.append(path)
    if added:
        import importlib
        importlib.invalidate_caches()
    return added


# -- installing ---------------------------------------------------------------

def python_executable():
    """The host's python interpreter, which is not always sys.executable.

    In Unreal sys.executable is the editor, in Maya it is maya.exe, and in
    older Blenders it was blender.exe, so the interpreter is looked for
    under sys.prefix and beside the executable too.
    """
    windows = sys.platform == 'win32'
    name = 'python.exe' if windows else 'python3'
    here = os.path.dirname(sys.executable or '')
    candidates = [sys.executable,
                  os.path.join(sys.prefix, name),
                  os.path.join(sys.prefix, 'bin', name),
                  os.path.join(sys.prefix, 'bin', 'python'),
                  os.path.join(here, 'mayapy.exe' if windows else 'mayapy')]
    for path in candidates:
        base = os.path.basename(path or '').lower()
        if base.startswith(('python', 'mayapy')) and os.path.isfile(path):
            return os.path.abspath(path)
    return None


def install_command(comp, target=None, crt=None, progress=False):
    """The pip command that installs a component into a folder.

    :param target: the component's folder when None
    :param progress: ask pip for progress lines, which needs pip 24.1
    :rtype: list
    """
    python = python_executable() or 'python'
    cmd = [python, '-m', 'pip', 'install', '--upgrade',
           '--target', target or folder(comp, crt=crt),
           '--disable-pip-version-check', '--no-input']
    if progress:
        cmd += ['--progress-bar', 'raw']
    wheels = wheel_dirs()
    if wheels:
        cmd.append('--no-index')
        for path in wheels:
            cmd += ['--find-links', path]
    cmd.append(requirement(comp, crt))
    return cmd


def pip_environment(base=None):
    """The environment pip runs in: unbuffered, so lines arrive as they
    are written, and without the user's own site-packages.
    """
    env = dict(os.environ if base is None else base)
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONNOUSERSITE'] = '1'
    env['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'
    # The host's own paths mean nothing to the python pip runs in.
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    return env


def progress_unsupported(output):
    """Whether pip said it is too old for --progress-bar raw."""
    return 'progress-bar' in output and 'invalid choice' in output


def new_staging(comp, root=None):
    """An empty folder to install into, beside where it will end up, so
    moving it into place is a rename.
    """
    root = root or install_root()
    parent = os.path.join(root, STAGING_FOLDER)
    os.makedirs(parent, exist_ok=True)
    # What an install that never finished, because nxt was closed while it
    # ran say, left behind. Old enough that no install still running uses
    # it.
    for name in os.listdir(parent):
        path = os.path.join(parent, name)
        try:
            stale = time.time() - os.path.getmtime(path) > STALE_SECONDS
        except OSError:
            continue
        if stale:
            discard(path)
    return tempfile.mkdtemp(prefix=comp.id + '-', dir=parent)


def discard(path):
    shutil.rmtree(path, ignore_errors=True)


def _requires(dist):
    names = []
    for line in dist.requires or ():
        if 'extra' in line.split(';', 1)[-1] and ';' in line:
            continue
        names.append(normalize(split_requirement(line)[0]))
    return names


def _top_levels(dist, path):
    """The files and folders directly in path that a distribution owns."""
    owned = set()
    for item in dist.files or ():
        full = os.path.abspath(os.path.join(path, str(item)))
        if not _inside(full, path):
            continue
        relative = os.path.relpath(full, path)
        owned.add(relative.split(os.sep)[0])
    # A distribution's own metadata folder, even if RECORD is missing.
    meta = getattr(dist, '_path', None)
    if meta is not None:
        owned.add(os.path.basename(str(meta)))
    return owned


def _owned(comp, path):
    """What in a folder belongs to a component and the packages only it
    needs, as top level names, and the names of those packages.
    """
    dists = {_dist_name(d): d for d in _distributions(path)}
    roots_ = [n for n in comp.dists if n in dists]
    if not roots_:
        return set(), set()
    mine = set()
    todo = list(roots_)
    while todo:
        name = todo.pop()
        if name in mine or name not in dists:
            continue
        mine.add(name)
        todo.extend(_requires(dists[name]))
    # Keep anything another package in the folder still needs.
    others = set(dists) - mine
    needed = set()
    todo = list(others)
    while todo:
        name = todo.pop()
        if name in needed or name not in dists:
            continue
        needed.add(name)
        todo.extend(_requires(dists[name]))
    mine -= needed
    keep = set()
    for name in needed:
        keep |= _top_levels(dists[name], path)
    owned = set()
    for name in mine:
        owned |= _top_levels(dists[name], path)
    return owned - keep, mine


def _remove_path(path):
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    elif os.path.lexists(path):
        os.remove(path)


def remove(comp, path=None, crt=None):
    """Delete a component, and what only it needed, from its folder.

    :param path: its folder, where installed() finds it when None
    :return: the top level names removed, which are the modules to forget
    :raises RuntimeError: with what could not be removed and why
    """
    if path is None:
        path = installed(comp, crt)[1]
    if not path:
        raise RuntimeError('{} is not installed.'.format(comp.name))
    if not writable(path):
        raise RuntimeError("{} is in {}, which you can't change. Ask whoever "
                           "manages it.".format(comp.name, path))
    owned, _names = _owned(comp, path)
    failed = []
    for name in sorted(owned):
        try:
            _remove_path(os.path.join(path, name))
        except OSError as error:
            failed.append('{}: {}'.format(name, error.strerror or error))
    _forget_empty(path)
    if failed:
        raise RuntimeError(
            "Some of {} could not be removed, probably because it is in use. "
            "Close {} and try again.\n{}".format(
                comp.name, 'the host' if comp.compiled else 'nxt',
                '\n'.join(failed)))
    return sorted(os.path.splitext(n)[0] for n in owned
                  if not n.endswith(('.dist-info', '.egg-info')))


def _forget_empty(path):
    try:
        if os.path.isdir(path) and not os.listdir(path):
            os.rmdir(path)
    except OSError:
        pass


def _move_in(staging, path):
    os.makedirs(path, exist_ok=True)
    for name in os.listdir(staging):
        if name in (PENDING_MARKER, 'bin', 'Scripts'):
            # Console scripts point at the python pip ran in; nothing here
            # runs them.
            continue
        destination = os.path.join(path, name)
        if os.path.lexists(destination):
            _remove_path(destination)
        os.replace(os.path.join(staging, name), destination)


def finish_install(comp, staging, crt=None, root=None):
    """Put a finished install in place of what was there.

    A component already loaded from its folder can not be swapped under a
    running python on Windows, so it waits in the pending folder and
    add_to_path finishes it at the next start.

    :return: 'installed', or 'restart' when it waits for the next start
    """
    root = root or install_root()
    target = folder(comp, root, crt)
    loaded = loaded_from(comp)
    if comp.compiled and loaded and _inside(loaded, target):
        waiting = os.path.join(root, PENDING_FOLDER, folder_name(comp, crt))
        if os.path.isdir(waiting):
            discard(waiting)
        os.makedirs(os.path.dirname(waiting), exist_ok=True)
        os.replace(staging, waiting)
        with open(os.path.join(waiting, PENDING_MARKER), 'w',
                  encoding='utf-8') as handle:
            handle.write(comp.id)
        return 'restart'
    if find_distribution(comp, target) is not None:
        remove(comp, target, crt)
    _move_in(staging, target)
    discard(staging)
    _forget_empty(os.path.join(root, STAGING_FOLDER))
    return 'installed'


def apply_pending(root):
    """Finish the updates that waited for a start, before anything they
    replace has been imported.
    """
    parent = os.path.join(root, PENDING_FOLDER)
    if not os.path.isdir(parent):
        return []
    done = []
    for name in os.listdir(parent):
        waiting = os.path.join(parent, name)
        marker = os.path.join(waiting, PENDING_MARKER)
        if not os.path.isfile(marker):
            continue
        with open(marker, encoding='utf-8') as handle:
            comp = component(handle.read().strip())
        target = os.path.join(root, name)
        if find_distribution(comp, target) is not None:
            owned, _names = _owned(comp, target)
            for item in owned:
                _remove_path(os.path.join(target, item))
        _move_in(waiting, target)
        discard(waiting)
        done.append(comp.id)
    _forget_empty(parent)
    return done


# -- reading pip --------------------------------------------------------------

_PROGRESS = re.compile(r'^Progress (\d+) of (\d+)')
_DOWNLOADING = re.compile(r'^\s*Downloading (?:https?://\S+/)?([^\s/]+?)'
                          r'(?:\.whl|\.tar\.gz|\.zip)?(?:\.metadata)?'
                          r'(?: \(([^)]+)\))?\s*$')
_PROCESSING = re.compile(r'^Processing \S*?([^\\/\s]+?)'
                         r'(?:\.whl|\.tar\.gz|\.zip)\s*$')


def _package_label(file_name):
    """'jedi-0.20.1-py2.py3-none-any' -> 'jedi 0.20.1'"""
    parts = file_name.split('-')
    if len(parts) >= 2 and version_tuple(parts[1]):
        return '{} {}'.format(parts[0], parts[1])
    return file_name


def parse_line(line):
    """What a line of pip's output says, for a progress display.

    :return: ('progress', done, total) in bytes, ('step', text), or None
    """
    line = line.rstrip()
    match = _PROGRESS.match(line)
    if match:
        return 'progress', int(match.group(1)), int(match.group(2))
    if line.startswith('Collecting '):
        name = split_requirement(line[len('Collecting '):])[0]
        return 'step', 'Finding {}'.format(name)
    if line.strip().startswith('Downloading ') and '.metadata' not in line:
        match = _DOWNLOADING.match(line)
        if match:
            text = 'Downloading {}'.format(_package_label(match.group(1)))
            if match.group(2):
                text += ' ({})'.format(match.group(2))
            return 'step', text
    if line.strip().startswith('Using cached '):
        name = line.strip()[len('Using cached '):].split(' ')[0]
        name = re.sub(r'(\.whl|\.tar\.gz|\.zip)$', '', name)
        return 'step', 'Unpacking {}'.format(_package_label(name))
    match = _PROCESSING.match(line.strip())
    if match:
        return 'step', 'Unpacking {}'.format(_package_label(match.group(1)))
    if line.startswith('Installing collected packages'):
        return 'step', 'Installing'
    if line.startswith('Successfully installed'):
        return 'step', 'Finishing'
    return None


def explain_failure(output, comp=None):
    """A short, plain reason for a failed pip run, from its output."""
    name = comp.name if comp else 'it'
    text = output.lower()
    wheels = wheel_dirs()
    if "no module named pip" in text:
        return ("This application's Python has no pip, so nxt can't install "
                "{} here.".format(name))
    if ('no matching distribution' in text or
            'could not find a version' in text):
        if wheels:
            return ('No version of {} for this Python is in {}. Ask whoever '
                    'set up that folder to add one.'.format(
                        name, os.pathsep.join(wheels)))
        return ('No version of {} was found for this Python ({}.{}).'.format(
            name, *sys.version_info[:2]))
    network = ('connectionerror', 'connection refused', 'failed to establish',
               'temporary failure in name resolution', 'getaddrinfo failed',
               'network is unreachable', 'read timed out', 'max retries',
               'proxyerror', 'ssl')
    if any(word in text for word in network):
        return ("Couldn't download {}. Check your internet connection, or ask "
                "your studio about an offline wheels folder ({}).".format(
                    name, WHEELS_ENV_VAR))
    if ('permission denied' in text or 'access is denied' in text or
            'errno 13' in text):
        return ("Couldn't write to the install folder. It may be read only, "
                "or a file in it is in use.")
    if 'no space left' in text or 'errno 28' in text:
        return 'The disk is full.'
    lines = [l.strip() for l in output.splitlines() if l.strip()]
    errors = [l for l in lines if l.lower().startswith('error')]
    return (errors or lines or ['pip stopped with an error.'])[-1]


# -- installing, all in one go ------------------------------------------------

def _run_pip(cmd, on_line=None):
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, env=pip_environment())
    lines = []
    for raw in iter(proc.stdout.readline, b''):
        line = raw.decode('utf-8', errors='replace').rstrip('\r\n')
        lines.append(line)
        if on_line:
            on_line(line)
    proc.stdout.close()
    return proc.wait(), '\n'.join(lines)


def install(comp, crt=None, on_line=None):
    """pip install a component, wait for it, and put it in place.

    For a host's own menu and the command line. The editor's dialog does
    the same steps in a QProcess so it does not freeze.

    :param on_line: called with each line pip prints
    :return: 'installed', or 'restart' when it waits for the next start
    :raises RuntimeError: with why, and pip's output
    """
    if crt is None:
        crt = loaded_crt_version()
    if python_executable() is None:
        raise RuntimeError('Could not find the python interpreter under '
                           '{}.\n{}'.format(sys.prefix,
                                            install_instructions(comp, crt)))
    try:
        staging = new_staging(comp)
    except OSError as error:
        raise RuntimeError("Couldn't make a folder in {}: {}".format(
            install_root(), error))
    try:
        cmd = install_command(comp, staging, crt, progress=True)
        code, output = _run_pip(cmd, on_line)
        if code != 0 and progress_unsupported(output):
            cmd = install_command(comp, staging, crt)
            code, output = _run_pip(cmd, on_line)
        if code != 0:
            raise RuntimeError('Installing {} failed: {}\n\n{}\n{}'.format(
                comp.name, explain_failure(output, comp), output[-4000:],
                install_instructions(comp, crt)))
        return finish_install(comp, staging, crt)
    finally:
        if os.path.isdir(staging):
            discard(staging)


def install_instructions(comp, crt=None):
    cmd = install_command(comp, crt=crt)
    return ('To install {} by hand, run:\n\n    {}\n\nor set {} to a folder '
            'that already has it in a {} folder.'.format(
                comp.name, subprocess.list2cmdline(cmd), DEPS_ENV_VAR,
                folder_name(comp, crt)))


# -- command line -------------------------------------------------------------

STATE_TEXT = {
    Status.NOT_NEEDED: 'not needed here',
    Status.NOT_INSTALLED: 'not installed',
    Status.INSTALLED: 'installed',
    Status.UPDATE: 'update available',
    Status.MANAGED: 'managed by your studio',
    Status.ELSEWHERE: 'comes with this python',
    Status.RESTART: 'restart to finish updating',
}


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        prog='optional_deps.py',
        description="nxt's optional components, for this python.")
    parser.add_argument('--host', default=None,
                        help='the host to answer for, such as blender')
    sub = parser.add_subparsers(dest='command')
    sub.add_parser('status', help='what is installed, and where')
    for name in ('install', 'remove'):
        each = sub.add_parser(name, help='{} components'.format(name))
        each.add_argument('components', nargs='+',
                          choices=[c.id for c in COMPONENTS])
    args = parser.parse_args(argv)
    if args.command in (None, 'status'):
        for each in statuses(args.host):
            print('{:<8} {:<28} {:<10} {}'.format(
                each.component.id, STATE_TEXT[each.state],
                each.version or '', each.folder or ''))
        return 0
    code = 0
    for comp_id in args.components:
        comp = component(comp_id)
        try:
            if args.command == 'install':
                result = install(comp, on_line=print)
                print('{}: {}'.format(comp.name, result))
            else:
                remove(comp)
                print('{}: removed'.format(comp.name))
        except RuntimeError as error:
            sys.stderr.write('{}\n'.format(error))
            code = 1
    return code


if __name__ == '__main__':
    sys.exit(main())
