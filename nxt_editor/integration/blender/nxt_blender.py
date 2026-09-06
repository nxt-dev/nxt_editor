"""nxt in Blender, from a menu -- the Blender counterpart of nxt_maya.

Install: Edit > Preferences > Add-ons > Install, pick this file, tick it.
An **NXT** menu appears in the top bar, the same place the Maya plugin puts
its "nxt" menu, offering Open Editor, Run Graph, and Reload Code.

**Why this is an add-on and not just a script.** All the hard parts already
work in ``nxt_blender_launch.py`` at the dev root: finding a Qt binding
Blender does not ship, and pumping Qt's event loop from Blender's, without
which the editor window paints once and then ignores everything. This does
not reimplement any of that. It loads that module and puts its functions on
a menu, so nothing has to be pasted into the Scripting workspace.

**Loading the launcher opens a window, by design.** That module ends with
``if __name__ == '__main__' or True:`` so that pasting it into a text block
runs it. Importing it therefore launches the editor, which is exactly what
"Open Editor" wants the first time and not what anything else wants -- so
the first Open Editor loads it and every later call goes through
``launch_nxt`` instead.

**Reload Code is not a convenience.** Blender caches modules for the life
of the session, so editing ``core/blender/*.py`` and running a graph again
quietly re-runs what was already imported. It reads as an edit that did
nothing, and it has cost real time. The menu marks the loaded code stale
when it no longer matches the files.
"""
import hashlib
import importlib.util
import os
import sys

import bpy
from bpy_extras.io_utils import ImportHelper

bl_info = {
    "name": "NXT for Blender",
    "author": "Squarebit Studios",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "Top bar > NXT",
    "description": "Open the nxt editor and run graphs inside Blender",
    "category": "System",
}

#: Where the repos live. Overridden by ``SB_DEV_ROOT``.
DEV_ROOT = os.environ.get("SB_DEV_ROOT",
                          r"C:/Users/walte/Documents/dev/squarebit")

#: The launcher that knows how to get Qt running inside Blender.
LAUNCHER = os.path.join(DEV_ROOT, "nxt_blender_launch.py")

#: The module name it is loaded under, so it is loaded only once.
LAUNCHER_MODULE = "nxt_blender_launch"

#: Remembered so the menu can offer the last graph again.
LAST_GRAPH = ""


def launcher(load=True):
    """The launch module, loading it on first use.

    :param load: load it if it is not loaded. False only ever looks.
    :type load: bool
    :return: the module, or ``None``.
    :rtype: module | None
    """
    found = sys.modules.get(LAUNCHER_MODULE)
    if found is not None or not load:
        return found
    if not os.path.isfile(LAUNCHER):
        return None
    spec = importlib.util.spec_from_file_location(LAUNCHER_MODULE, LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[LAUNCHER_MODULE] = module
    try:
        # This RUNS the launcher, which opens an editor window. See the
        # module docstring: that is what its trailing guard does, and it
        # is why only Open Editor is allowed to be the thing that loads it.
        spec.loader.exec_module(module)
    except Exception:
        del sys.modules[LAUNCHER_MODULE]
        raise
    return module


def source_hash():
    """A digest of the core Blender sources on disk.

    :return: a short hash, or empty when there is nothing to read.
    :rtype: str
    """
    folder = os.path.join(DEV_ROOT, "core", "core", "blender")
    if not os.path.isdir(folder):
        return ""
    digest = hashlib.md5()
    for name in sorted(os.listdir(folder)):
        if name.endswith(".py"):
            with open(os.path.join(folder, name), "rb") as handle:
                digest.update(handle.read())
    return digest.hexdigest()[:12]


def loaded_hash():
    """The digest recorded when core was last (re)loaded.

    :return: the hash, or empty when core is not loaded.
    :rtype: str
    """
    module = sys.modules.get("core.blender")
    return getattr(module, "_nxt_menu_hash", "") if module else ""


def _stamp():
    """Record which sources the loaded core came from.

    :return: None
    :rtype: None
    """
    module = sys.modules.get("core.blender")
    if module is not None:
        module._nxt_menu_hash = source_hash()


class NXT_OT_open_editor(bpy.types.Operator):
    """Open an nxt editor window inside Blender"""

    bl_idname = "nxt.open_editor"
    bl_label = "Open Editor"
    bl_options = {"REGISTER"}

    def execute(self, context):
        """Open a window, loading the launcher the first time.

        :param context: Blender's context.
        :type context: bpy.types.Context
        :return: the operator result.
        :rtype: set
        """
        if not os.path.isfile(LAUNCHER):
            self.report({"ERROR"},
                        "No launcher at {}. Set SB_DEV_ROOT.".format(
                            LAUNCHER))
            return {"CANCELLED"}

        already = launcher(load=False) is not None
        try:
            module = launcher()
        except Exception as error:              # noqa: BLE001
            self.report({"ERROR"},
                        "{} -- see the system console".format(error))
            raise
        if already:
            # Loading it opened one; any window after that is asked for.
            module.launch_nxt()
        elif not module.check_qt_binding():
            # It prints the exact pip line to the console rather than
            # installing anything into Blender by itself.
            self.report({"ERROR"},
                        "Blender has no Qt binding -- the console has the "
                        "command to install PySide6")
            return {"CANCELLED"}
        self.report({"INFO"}, "nxt editor open")
        return {"FINISHED"}


class NXT_OT_close_editor(bpy.types.Operator):
    """Close the nxt editor windows this session opened"""

    bl_idname = "nxt.close_editor"
    bl_label = "Close Editor"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        """Only offered once the launcher is loaded.

        :param context: Blender's context.
        :type context: bpy.types.Context
        :return: whether there is anything to close.
        :rtype: bool
        """
        return launcher(load=False) is not None

    def execute(self, context):
        """Close them.

        :param context: Blender's context.
        :type context: bpy.types.Context
        :return: the operator result.
        :rtype: set
        """
        launcher(load=False).close_nxt()
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
    """Forget cached core modules so the next run reads the files"""

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
        module = launcher(load=False)
        if module is None:
            _paths()
            dropped = _drop_core()
        else:
            dropped = module.reload_core()
        _stamp()
        self.report({"INFO"}, "Forgot {} module(s)".format(dropped))
        return {"FINISHED"}


def _paths():
    """Put nxt and core on ``sys.path`` for running graphs without Qt.

    :return: None
    :rtype: None
    """
    for name in ("nxt", "core"):
        path = os.path.join(DEV_ROOT, name)
        if os.path.isdir(path) and path not in sys.path:
            sys.path.insert(0, path)


def _drop_core():
    """Forget the core modules, when the launcher is not loaded.

    :return: how many were dropped.
    :rtype: int
    """
    names = [n for n in list(sys.modules)
             if n == "core" or n.startswith("core.")]
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
        _drop_core()
        _paths()

    try:
        from nxt.session import Session
    except ImportError as error:
        operator.report({"ERROR"},
                        "nxt is not importable from {}: {}".format(
                            os.path.join(DEV_ROOT, "nxt"), error))
        return {"CANCELLED"}

    print("nxt: running {}".format(graph))
    try:
        Session().execute_graph(graph)
    except Exception as error:                  # noqa: BLE001
        # nxt prints the failing node's path and traceback to the console,
        # which locates the problem far better than a dialog can.
        operator.report({"ERROR"},
                        "{} -- see the system console for the node".format(
                            error))
        raise

    LAST_GRAPH = graph
    _stamp()
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
        layout.separator()
        layout.operator(NXT_OT_run_graph.bl_idname, icon="PLAY")
        layout.operator(NXT_OT_run_last.bl_idname, icon="FILE_REFRESH")
        if LAST_GRAPH:
            layout.label(text=os.path.basename(LAST_GRAPH), icon="FILE")
        layout.separator()
        layout.operator(NXT_OT_reload.bl_idname, icon="SCRIPT")

        on_disk, loaded = source_hash(), loaded_hash()
        if loaded and on_disk and loaded != on_disk:
            layout.separator()
            layout.label(text="core is STALE -- reload", icon="ERROR")


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


CLASSES = (NXT_OT_open_editor, NXT_OT_close_editor, NXT_OT_run_graph,
           NXT_OT_run_last, NXT_OT_reload, NXT_MT_menu)


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
    bpy.types.TOPBAR_MT_editor_menus.remove(_draw_menu)
    for item in reversed(CLASSES):
        bpy.utils.unregister_class(item)


if __name__ == "__main__":
    register()
