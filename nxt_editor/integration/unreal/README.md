# Installation
**This is an experimental version of nxt_unreal. Save early, save often.**

The plugin carries nxt, nxt_editor and Qt.py in `Content/Python`, so it
runs the nxt it was released with and does not install anything from PyPI.

1. Move this plugin either into your project's or the engine's `Plugins`
   directory.
2. Ensure that the Python Editor Script Plugin is enabled.
3. Enable the plugin in the plugin browser and restart the editor.
4. The first time, choose **nxt > Install Qt (PySide6)**. Unreal ships no
   Qt, so this downloads PySide6 with the engine's pip into
   `~/nxt/deps/py<version>`, outside the engine.

For machines without internet access, install PySide6 once somewhere shared
and point `NXT_QT_DEPS` at it:

    <engine python> -m pip install --target <shared>/py311 "pyside6-essentials>=6,<6.12"

The engine's python is under `Engine/Binaries/ThirdParty/Python3`. The
folder name is its python version, because PySide6 only loads in the python
it was installed for.

# Launch
From the top menu **nxt**, select **Open Editor**.

# Update
Replace the plugin folder with the one from a newer release.

If an older version of this plugin pip installed `nxt-editor` into the
engine, the bundled copy is used ahead of it; it can be removed with
`<engine python> -m pip uninstall nxt-editor nxt-core`.
