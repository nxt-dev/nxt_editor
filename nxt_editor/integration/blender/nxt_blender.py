"""nxt in Blender, from a menu -- the Blender counterpart of nxt_maya.

Install: Edit > Preferences > Add-ons > Install from Disk, pick the
``nxt_blender.zip`` from the release, tick it. An **NXT** menu appears in
the top bar, the same place the Maya plugin puts its "nxt" menu.

**What it runs.** The release add-on carries nxt, nxt_editor and Qt.py in
its ``lib`` folder and uses those. With nothing bundled -- this file
installed on its own -- it uses whatever nxt and nxt_editor Blender's
python can already import.

**Qt.** Blender ships no Qt and the editor is a Qt application, so PySide6
has to be installed once; the menu offers to do it, into a folder outside
Blender (see ``nxt_editor/integration/qt_deps.py``). Graphs run without
it. Only the editor window needs it.

**Blender owns the event loop.** Maya is a Qt application already, so an
nxt window just joins its loop. Blender knows nothing about Qt, so a timer
hands Qt a slice of Blender's loop while an editor is open; without it
the window paints once and then ignores everything.

**Reload Code is not a convenience.** Blender caches modules for the life
of the session, so a newer nxt on disk is not picked up by running a
graph again; what was already imported runs instead. It reads as a graph
problem rather than a stale import, so Run Graph forgets nxt first.
"""
import importlib
import importlib.util
import json
import os
import sys

import bpy
from bpy_extras.io_utils import ImportHelper

bl_info = {
    "name": "NXT for Blender",
    "author": "The nxt contributors",
    "version": (0, 2, 0),
    "blender": (4, 2, 0),
    "location": "Top bar > NXT",
    "description": "Open the nxt editor and run graphs inside Blender",
    "category": "System",
}

#: Where the release add-on keeps nxt, nxt_editor and Qt.py.
BUNDLED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")

#: How often to let Qt do its work, in seconds. Small enough that typing
#: feels immediate, large enough that Blender is not spending its life in
#: there.
PUMP_INTERVAL = 0.02

#: Remembered so the menu can offer the last graph again.
LAST_GRAPH = ""

#: Live editor windows, so the pump knows when to stop and a reload does
#: not pull the module out from under one.
__NXT_WINDOWS__ = []
__PUMPING__ = [False]


def is_bundled():
    """Whether this is the release add-on, carrying its own nxt.

    :return: True when ``lib`` has nxt_editor in it.
    :rtype: bool
    """
    return os.path.isdir(os.path.join(BUNDLED_DIR, "nxt_editor"))


def _source_dirs():
    """The folders nxt, nxt_editor and Qt.py are imported from.

    :return: paths to put on ``sys.path``, first wins.
    :rtype: list[str]
    """
    if is_bundled():
        return [BUNDLED_DIR]
    # Not bundled: wherever Blender's python already finds nxt_editor.
    try:
        spec = importlib.util.find_spec("nxt_editor")
    except (ImportError, ValueError):
        spec = None
    if spec is None or not spec.submodule_search_locations:
        return []
    return [os.path.dirname(list(spec.submodule_search_locations)[0])]


def _where():
    """Where nxt is looked for, to say so when it is not there."""
    return " or ".join(_source_dirs()) or BUNDLED_DIR


def _put_first(path):
    """Put a path at the front of sys.path, however it got there before.

    :param path: the folder.
    :type path: str
    :return: None
    :rtype: None
    """
    for existing in list(sys.path):
        if os.path.normcase(os.path.abspath(existing)) == \
                os.path.normcase(os.path.abspath(path)):
            sys.path.remove(existing)
    sys.path.insert(0, path)


def _paths():
    """Put nxt, nxt_editor and Qt.py on ``sys.path``.

    :return: None
    :rtype: None
    """
    for path in reversed(_source_dirs()):
        if os.path.isdir(path):
            _put_first(path)


def qt_deps():
    """nxt_editor's Qt installer, loaded by path.

    Loaded that way because importing anything under nxt_editor imports Qt,
    which is the thing that may not be there yet.

    :return: the module, or ``None`` when nxt_editor cannot be found.
    :rtype: module | None
    """
    found = sys.modules.get("nxt_qt_deps")
    if found is not None:
        return found
    for root in _source_dirs():
        path = os.path.join(root, "nxt_editor", "integration", "qt_deps.py")
        if os.path.isfile(path):
            break
    else:
        return None
    spec = importlib.util.spec_from_file_location("nxt_qt_deps", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules["nxt_qt_deps"] = module
    return module


def has_qt():
    """Make PySide6 importable if it is installed anywhere nxt looks.

    :return: whether it is.
    :rtype: bool
    """
    _paths()
    deps = qt_deps()
    if deps is None:
        return False
    return deps.add_to_path()


def _live_windows():
    """The editor windows still open, forgetting the closed ones.

    :return: the open windows.
    :rtype: list
    """
    alive = []
    for window in __NXT_WINDOWS__:
        try:
            if window.isVisible():
                alive.append(window)
        except RuntimeError:
            # Qt already deleted it.
            pass
    __NXT_WINDOWS__[:] = alive
    return alive


def _start_pump():
    """Give Qt a slice of Blender's event loop while a window is open.

    :return: None
    :rtype: None
    """
    if __PUMPING__[0]:
        return
    from Qt import QtWidgets

    def pump():
        app = QtWidgets.QApplication.instance()
        if app is None or not _live_windows():
            # Nothing left to drive, so stop asking to be called.
            __PUMPING__[0] = False
            return None
        app.processEvents()
        return PUMP_INTERVAL

    bpy.app.timers.register(pump, persistent=True)
    __PUMPING__[0] = True


def launch_nxt(graph=None):
    """Open an nxt editor window inside this Blender.

    :param graph: optional .nxt file to open.
    :type graph: str | None
    :return: the editor window.
    """
    from nxt.constants import NXT_DCC_ENV_VAR
    import nxt_editor
    from Qt import QtWidgets
    os.environ[NXT_DCC_ENV_VAR] = "blender"
    if QtWidgets.QApplication.instance() is None:
        # Blender has no QApplication of its own to join.
        nxt_editor._new_qapp()
    window = nxt_editor.show_new_editor([graph] if graph else None)
    window.show()
    __NXT_WINDOWS__.append(window)
    _start_pump()
    return window


def close_nxt():
    """Close every window this add-on opened. The pump stops with them.

    :return: None
    :rtype: None
    """
    while __NXT_WINDOWS__:
        window = __NXT_WINDOWS__.pop()
        try:
            window.close()
        except RuntimeError:
            pass


class NXT_OT_open_editor(bpy.types.Operator):
    """Open an nxt editor window inside Blender"""

    bl_idname = "nxt.open_editor"
    bl_label = "Open Editor"
    bl_options = {"REGISTER"}

    def execute(self, context):
        """Open a window, when Qt is there to open it with.

        :param context: Blender's context.
        :type context: bpy.types.Context
        :return: the operator result.
        :rtype: set
        """
        if qt_deps() is None:
            self.report({"ERROR"},
                        "nxt_editor not found in {}. Reinstall the add-on, "
                        "or pip install nxt-editor into Blender's python."
                        .format(_where()))
            return {"CANCELLED"}
        if not has_qt():
            print(qt_deps().install_instructions())
            self.report({"ERROR"},
                        "Blender has no Qt. Use NXT > Install Qt (PySide6), "
                        "or see the system console")
            return {"CANCELLED"}
        try:
            launch_nxt()
        except Exception as error:              # noqa: BLE001
            self.report({"ERROR"},
                        "{} -- see the system console".format(error))
            raise
        self.report({"INFO"}, "nxt editor open")
        return {"FINISHED"}


class NXT_OT_install_qt(bpy.types.Operator):
    """Download PySide6 for the nxt editor, into a folder outside Blender.
    Blender pauses while it installs"""

    bl_idname = "nxt.install_qt"
    bl_label = "Install Qt (PySide6)"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        """Only offered while there is no Qt.

        :param context: Blender's context.
        :type context: bpy.types.Context
        :return: whether it is needed.
        :rtype: bool
        """
        return qt_deps() is not None and not has_qt()

    def invoke(self, context, event):
        """Say what is about to happen before it does.

        :param context: Blender's context.
        :type context: bpy.types.Context
        :param event: the triggering event.
        :type event: bpy.types.Event
        :return: the operator result.
        :rtype: set
        """
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        """pip install it.

        :param context: Blender's context.
        :type context: bpy.types.Context
        :return: the operator result.
        :rtype: set
        """
        deps = qt_deps()
        print("nxt: installing PySide6 into {}".format(deps.deps_dir()))
        try:
            where = deps.install()
        except RuntimeError as error:
            print(error)
            self.report({"ERROR"},
                        "Installing PySide6 failed -- see the system console")
            return {"CANCELLED"}
        self.report({"INFO"}, "PySide6 installed to {}".format(where))
        return {"FINISHED"}


class NXT_OT_close_editor(bpy.types.Operator):
    """Close the nxt editor windows this session opened"""

    bl_idname = "nxt.close_editor"
    bl_label = "Close Editor"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        """Only offered while there is a window to close.

        :param context: Blender's context.
        :type context: bpy.types.Context
        :return: whether there is anything to close.
        :rtype: bool
        """
        return bool(__NXT_WINDOWS__)

    def execute(self, context):
        """Close them.

        :param context: Blender's context.
        :type context: bpy.types.Context
        :return: the operator result.
        :rtype: set
        """
        close_nxt()
        self.report({"INFO"}, "nxt editor closed")
        return {"FINISHED"}


class NXT_OT_run_graph(bpy.types.Operator, ImportHelper):
    """Execute a .nxt graph in this scene, without opening the editor"""

    bl_idname = "nxt.run_graph"
    bl_label = "Run Graph..."
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".nxt"
    filter_glob: bpy.props.StringProperty(default="*.nxt",
                                          options={"HIDDEN"})
    fresh: bpy.props.BoolProperty(
        name="Reload code first",
        description=("Forget cached modules before running, so edits take "
                     "effect. Off runs whatever this session imported"),
        default=True)

    def execute(self, context):
        """Run the chosen graph.

        :param context: Blender's context.
        :type context: bpy.types.Context
        :return: the operator result.
        :rtype: set
        """
        return _run(self, self.filepath, self.fresh)


class NXT_OT_run_last(bpy.types.Operator):
    """Run the graph that was run last"""

    bl_idname = "nxt.run_last"
    bl_label = "Run Last Graph"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Only offered once a graph has been run.

        :param context: Blender's context.
        :type context: bpy.types.Context
        :return: whether there is a graph to repeat.
        :rtype: bool
        """
        return bool(LAST_GRAPH) and os.path.isfile(LAST_GRAPH)

    def execute(self, context):
        """Run it again, reloading first.

        :param context: Blender's context.
        :type context: bpy.types.Context
        :return: the operator result.
        :rtype: set
        """
        return _run(self, LAST_GRAPH, True)


class NXT_OT_reload(bpy.types.Operator):
    """Forget cached nxt modules so the next run reads the files"""

    bl_idname = "nxt.reload_code"
    bl_label = "Reload Code"
    bl_options = {"REGISTER"}

    def execute(self, context):
        """Drop them.

        :param context: Blender's context.
        :type context: bpy.types.Context
        :return: the operator result.
        :rtype: set
        """
        _paths()
        dropped = _drop_nxt()
        _paths()
        self.report({"INFO"}, "Forgot {} module(s); {}".format(
            dropped, nxt_report()))
        return {"FINISHED"}


def nxt_report():
    """Which nxt is actually loaded, and whether it can resolve layers.

    Worth surfacing because getting this wrong looks like a broken GRAPH,
    not a stale interpreter. A session holding nxt 0.19.0 loses the
    ``layer_dir`` fallback in ``nxt.nxt_io.expand_reference_path`` -- the
    part that resolves a reference relative to the referring layer's own
    directory. Without it every NESTED relative reference dangles, so a
    stack that should compose nine layers composes three and the graph
    looks like it lost its references.

    :return: a one line summary.
    :rtype: str
    """
    module = sys.modules.get("nxt")
    if module is None:
        return "nxt not loaded"
    here = os.path.dirname(getattr(module, "__file__", "") or "")
    version = "?"
    try:
        with open(os.path.join(here, "version.json")) as handle:
            api = json.load(handle).get("API", {})
        version = "{}.{}.{}".format(api.get("MAJOR"), api.get("MINOR"),
                                    api.get("PATCH"))
    except Exception:
        pass
    resolves = False
    try:
        from nxt.nxt_io import expand_reference_path
        resolves = "layer_dir" in expand_reference_path.__code__.co_varnames
    except Exception:
        pass
    return "nxt {} from {}{}".format(
        version, here,
        "" if resolves else "  -- TOO OLD to resolve nested references")


def _drop_nxt():
    """Forget the nxt modules.

    Blender caches modules for the life of the session, so a session that
    first imported an older nxt keeps it until it is dropped. The graphs
    then stop resolving their nested references and the fault reads as a
    graph problem rather than a stale import.

    ``nxt_editor`` and ``Qt`` are left alone when an editor window is open,
    because dropping the module out from under a live Qt window crashes it.

    :return: how many were dropped.
    :rtype: int
    """
    roots = ["nxt"]
    if not _live_windows():
        roots.append("nxt_editor")
    names = [n for n in list(sys.modules)
             if any(n == r or n.startswith(r + ".") for r in roots)]
    for name in names:
        del sys.modules[name]
    importlib.invalidate_caches()
    return len(names)


def _run(operator, graph, fresh):
    """Execute a graph, saying where to look when it fails.

    :param operator: the calling operator, for its report.
    :type operator: bpy.types.Operator
    :param graph: the ``.nxt`` file.
    :type graph: str
    :param fresh: forget cached modules first.
    :type fresh: bool
    :return: the operator result.
    :rtype: set
    """
    global LAST_GRAPH

    if not graph or not os.path.isfile(graph):
        operator.report({"ERROR"}, "No graph at {}".format(graph))
        return {"CANCELLED"}

    _paths()
    if fresh:
        _drop_nxt()
        _paths()

    try:
        from nxt.session import Session
    except ImportError as error:
        operator.report({"ERROR"},
                        "nxt is not importable from {}: {}".format(
                            _where(), error))
        return {"CANCELLED"}

    try:
        print("nxt: running {}".format(graph))
        Session().execute_graph(graph)
    except Exception as error:                  # noqa: BLE001
        # nxt prints the failing node's path and traceback to the console,
        # which locates the problem far better than a dialog can.
        operator.report({"ERROR"},
                        "{} -- see the system console for the node".format(
                            error))
        raise

    LAST_GRAPH = graph
    operator.report({"INFO"}, "Ran {}".format(os.path.basename(graph)))
    return {"FINISHED"}


class NXT_MT_menu(bpy.types.Menu):
    """The top bar menu, where nxt_maya puts its own."""

    bl_label = "NXT"
    bl_idname = "NXT_MT_menu"

    def draw(self, context):
        """Lay the menu out.

        :param context: Blender's context.
        :type context: bpy.types.Context
        :return: None
        :rtype: None
        """
        layout = self.layout
        layout.operator(NXT_OT_open_editor.bl_idname, icon="NODETREE")
        layout.operator(NXT_OT_close_editor.bl_idname, icon="X")
        if NXT_OT_install_qt.poll(context):
            layout.operator(NXT_OT_install_qt.bl_idname, icon="IMPORT")
        layout.separator()
        layout.operator(NXT_OT_run_graph.bl_idname, icon="PLAY")
        layout.operator(NXT_OT_run_last.bl_idname, icon="FILE_REFRESH")
        if LAST_GRAPH:
            layout.label(text=os.path.basename(LAST_GRAPH), icon="FILE")
        layout.separator()
        layout.operator(NXT_OT_reload.bl_idname, icon="SCRIPT")


def _draw_menu(self, context):
    """Put the menu in the top bar.

    :param self: the menu being extended.
    :type self: bpy.types.Menu
    :param context: Blender's context.
    :type context: bpy.types.Context
    :return: None
    :rtype: None
    """
    self.layout.menu(NXT_MT_menu.bl_idname)


CLASSES = (NXT_OT_open_editor, NXT_OT_install_qt, NXT_OT_close_editor,
           NXT_OT_run_graph, NXT_OT_run_last, NXT_OT_reload, NXT_MT_menu)


def register():
    """Register the add-on.

    :return: None
    :rtype: None
    """
    _paths()
    for item in CLASSES:
        bpy.utils.register_class(item)
    bpy.types.TOPBAR_MT_editor_menus.append(_draw_menu)


def unregister():
    """Unregister the add-on.

    :return: None
    :rtype: None
    """
    close_nxt()
    bpy.types.TOPBAR_MT_editor_menus.remove(_draw_menu)
    for item in reversed(CLASSES):
        bpy.utils.unregister_class(item)


if __name__ == "__main__":
    register()
