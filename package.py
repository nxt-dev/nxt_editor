import json

name = "nxt_editor"

description = (
    "The visual node editor for nxt, a python layering and sequential "
    "execution tool for animation and VFX."
)

authors = ["The nxt contributors dev@opennxt.dev"]


# read version json file so we only have to define version number in one location
@early()
def version():
    with open("nxt_editor/version.json", "r") as f:
        data = json.load(f)

    editor = data["EDITOR"]
    return f"{editor['MAJOR']}.{editor['MINOR']}.{editor['PATCH']}"


variants = []

# Mirrors what the pip built package required, so an existing resolve that
# asks for nxt_editor keeps getting the same dependency set.
requires = [
    "python-3.11+<3.14",
    "Qt.py<3",
    "PySide6-6+<6.12",
    "nxt_core-0.21+<1.0",
]

private_build_requires = []

release_branches = ["release"]

help = [["Home Page", "https://github.com/nxt-dev/nxt_editor"]]


def commands():
    import os

    if "dev" in ephemerals and os.path.exists(expandvars("$SB_DEV_ROOT/nxt_editor")):
        env.PYTHONPATH.prepend("$SB_DEV_ROOT/nxt_editor")
        env.MAYA_PLUG_IN_PATH.prepend(
            "$SB_DEV_ROOT/nxt_editor/nxt_editor/integration/maya/plug-ins"
        )
    else:
        env.PYTHONPATH.append("{root}/python")
        env.MAYA_PLUG_IN_PATH.append(
            "{root}/python/nxt_editor/integration/maya/plug-ins"
        )

    # The NXT menu in Blender. Blender only reads PYTHONPATH when started
    # with --python-use-system-env, which the studio blender launcher does.
    # The add-on file comes from the build in dev too; its nxt_editor comes
    # from PYTHONPATH, so dev edits to the editor are still picked up.
    if "blender" in resolve:
        env.BLENDER_SYSTEM_SCRIPTS.append("{root}/blender")
        # Blender ships no Qt, but the blender package asks for .dcc_pyside,
        # which tells rez's PySide6 to stay off PYTHONPATH (the rule for
        # Maya, which brings its own). Put rez's PySide6 back so the editor
        # opens without a separate Qt install.
        if "dcc_pyside" in ephemerals:
            for qt in ("shiboken6", "PySide6_Essentials", "PySide6_Addons",
                       "PySide6"):
                if qt in resolve:
                    env.PYTHONPATH.append(resolve[qt].root + "/python")


# A script rather than a shell one liner, so the build behaves the same on
# Windows as on the macOS and Linux runners.
build_command = "python {root}/rez_build.py"

