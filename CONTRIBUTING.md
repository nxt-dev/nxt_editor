# Contributing to nxt

This guide covers working on nxt_editor from source: setting up both
repositories, running the editor and the tests, IDE setup, and what a pull
request needs.

nxt is two repositories, and editor work usually needs both checked out:

- [nxt](https://github.com/nxt-dev/nxt): the core. Graph loading,
  composition and execution, and the `nxt` command.
- [nxt_editor](https://github.com/nxt-dev/nxt_editor): this repository,
  the Qt editor and the host integrations.

## Setup

### Tools

- [git](https://git-scm.com/downloads)
- Python 3.11, 3.12 or 3.13. The hosts use 3.11 (Maya 2025 and 2026,
  Blender 4, Unreal 5) and 3.13 (Maya 2027, Blender 5), and CI tests both.
- An editor or IDE. Setup for [VS Code and Cursor](#vs-code-and-cursor)
  and [PyCharm](#pycharm) is below.

### Check out both repositories side by side

Clone them into the same folder, on the `dev` branch:

```
mkdir nxt-dev
cd nxt-dev
git clone -b dev https://github.com/nxt-dev/nxt.git
git clone -b dev https://github.com/nxt-dev/nxt_editor.git
```

If you plan to open pull requests, fork both on GitHub first and clone
your forks instead. The rest of this guide assumes this layout:

```
nxt-dev/
    nxt/            the core checkout
    nxt_editor/     this checkout
    .venv/          the virtual environment, made next
```

### Virtual environment and dependencies

From the `nxt-dev` folder:

```
python -m venv .venv
```

Activate it, on Windows with `.venv\Scripts\activate`, on macOS and Linux
with `source .venv/bin/activate`. Then install the dependencies:

```
python -m pip install --upgrade pip
pip install "PySide6>=6,<6.12" "Qt.py<3" pytest
pip install "jedi>=0.19,<0.21"
```

jedi is optional. Without it the code editor's completion still works,
with fewer answers, and the tests that need it are skipped.

### Make both packages importable

Either install both checkouts as editable packages (recommended, and it
puts the `nxt` command on the environment's `PATH`):

```
pip install -e ./nxt
pip install -e ./nxt_editor
```

Install the core first, so pip does not fetch `nxt-core` from PyPI for the
editor. Editable installs write an `.egg-info` folder into each checkout;
leave it out of your commits.

Or put both checkouts on `PYTHONPATH` instead of installing them. On
Windows (PowerShell):

```
$env:PYTHONPATH = "$PWD\nxt_editor;$PWD\nxt"
```

On macOS and Linux:

```
export PYTHONPATH="$PWD/nxt_editor:$PWD/nxt"
```

Without an install, there is no `nxt` command: use `python -m nxt.cli`
wherever this guide says `nxt`.

Check that both come from your checkouts:

```
python -c "import nxt, nxt_editor; print(nxt.__file__, nxt_editor.__file__)"
nxt --version
```

### The faster comp engine

nxt composites graphs with a compiled module written in Rust. Releases
carry it, but a checkout of nxt doesn't, so until you build it the editor
runs on nxt's Python code: everything works, with the same results, only
slower on big graphs. `nxt --version` ends with `Comp native` once it is
built, or `Comp python` and the reason.

To build it, install [Rust](https://rustup.rs) and your OS's C build tools
(the Microsoft C++ build tools on Windows, `xcode-select --install` on
macOS), then from the `nxt` checkout run:

```
python native/build.py
```

Run it again after pulling changes to `nxt/native`. The
[nxt contributing guide](https://github.com/nxt-dev/nxt/blob/dev/CONTRIBUTING.md#the-faster-comp-engine-in-a-checkout)
has the steps for each OS, and how to change the module.

## Running the editor from source

```
nxt ui
nxt ui path/to/graph.nxt
```

or `python -m nxt.cli ui`. `nxt -v ui` logs more, `-vv` logs for
debugging.

The editor keeps its preferences, caches and recent files in `~/nxt`. To
keep a development session from changing your everyday settings, point
`NXT_USER_DIR` at another folder before launching.

The `examples` folder has graphs to try changes on.

## Running the tests

The tests are pytest tests in `nxt_editor/test`. Run them from the root
of this checkout:

```
python -m pytest nxt_editor/test
```

The full suite is large (over 1,500 tests) and takes a long time, so while
working run the files for the area you changed, and let CI run the rest:

```
python -m pytest nxt_editor/test/test_align.py
python -m pytest nxt_editor/test/test_align.py -k distribute
```

To list the tests without running them:

```
python -m pytest --collect-only -q nxt_editor/test
```

Many tests build real windows. On a workstation they use your display, so
you can watch them. To run them without one (over SSH, in a container, or
just to keep windows from flashing up), set `QT_QPA_PLATFORM` to
`offscreen`:

```
# Windows (PowerShell)
$env:QT_QPA_PLATFORM = "offscreen"
# macOS and Linux
export QT_QPA_PLATFORM=offscreen
```

Under CI (when `CI` is set), `nxt_editor/test/conftest.py` sets it for
you. On Linux without a display server, CI also wraps the run in
`xvfb-run`.

Each test run gets a temporary user directory of its own (see
`conftest.py` at the top of the repository), so the tests never touch
your `~/nxt` settings.

The core has its own tests, in `nxt/nxt/test`. Run them too when you
change the core.

## Branches and versions

- Work against `dev`. Branch from it and open pull requests into it.
- `release` is for releases only. Changes reach it from `dev` when a
  release is made.
- The version is bumped at release time. Pull requests into `dev` do not
  touch `nxt_editor/version.json`. A check on pull requests into `release`
  fails when that file has not changed.

When an editor change needs a core change, open a pull request in each
repository and say in each that it needs the other. CI tests the editor
against the core's `dev` branch (or `release` and `next` for those
branches), so the editor's tests pass once the core change is merged.

## Pull requests

A pull request should:

- Do one thing, with a title and description that say what changed and
  why.
- Come with tests. A fix needs a test that fails without it; a feature
  needs tests for what it does.
- Update the user docs in `docs/user_docs/docs` when it changes something
  a user can see or do: the page that describes it (usually
  `reference.md`, `install.md` or `hotkeys.md`), and a line under
  **Unreleased** at the top of `whats_new.md`, linking to that page.
- Pass the tests in CI.

To preview the docs:

```
pip install mkdocs
cd docs/user_docs
mkdocs serve
```

then open http://127.0.0.1:8000/.

## Code style

- Match the code around you. Otherwise follow PEP 8, with lines up to 79
  characters.
- Pure Python only. The same release runs on every OS and in every host,
  so nothing is compiled per platform. That includes Qt resources: icons,
  fonts and stylesheets are listed in `nxt_editor/resources/resources.qrc`
  and read at runtime by `nxt_editor/qt_resources.py`. Add a new file to
  the qrc; do not compile it with `rcc` or commit a generated module.
- Import Qt through Qt.py (`from Qt import QtWidgets`), never from
  PySide6 directly, so the editor keeps working on both Qt.py 1.4 and 2.

### The editor looks the same everywhere

The editor has to look identical standalone and in Maya, Blender and
Unreal. Hosts bring their own style, palette, fonts and screen scaling,
so the editor does not rely on any of them:

- Colors come from the tokens in `nxt_editor/theme.py`. Do not write hex
  values or use the application palette in a widget; add a token if none
  fits.
- Fonts come from `theme.font()`, and are the fonts shipped in
  `resources/fonts`, sized in pixels. Never use point sizes: a point is a
  different number of pixels on macOS than on Windows, and in a host that
  changes its scaling.
- Stylesheets go on the editor's own widgets, never on the host's
  application.

Look at a UI change standalone and, if you can, in a host before opening
the pull request.

## IDE setup

### VS Code and Cursor

Open the `nxt_editor` checkout as the workspace folder, with the Python
extension installed. Cursor reads the same `.vscode` files, so everything
here applies to it too. `.vscode/` is in `.gitignore`, so these files stay
yours.

`.vscode/settings.json`:

```json
{
    // Windows. On macOS and Linux: ${workspaceFolder}/../.venv/bin/python
    "python.defaultInterpreterPath": "${workspaceFolder}/../.venv/Scripts/python.exe",
    // Lets the language server find the core, since an editable
    // install is not always followed for completion and go to definition.
    "python.analysis.extraPaths": ["${workspaceFolder}/../nxt"],
    "python.testing.pytestEnabled": true,
    "python.testing.unittestEnabled": false,
    "python.testing.pytestArgs": ["nxt_editor/test"]
}
```

Tests run from the Testing panel use your display. To run them offscreen
from there, set `QT_QPA_PLATFORM` before starting VS Code or Cursor.

`.vscode/launch.json`, to run the editor and debug a test file:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "nxt editor",
            "type": "debugpy",
            "request": "launch",
            "module": "nxt.cli",
            "args": ["ui"],
            "console": "integratedTerminal",
            "justMyCode": false
        },
        {
            "name": "Debug current test file",
            "type": "debugpy",
            "request": "launch",
            "module": "pytest",
            "args": ["-q", "${file}"],
            "cwd": "${workspaceFolder}",
            "env": {"QT_QPA_PLATFORM": "offscreen"},
            "console": "integratedTerminal",
            "justMyCode": false
        }
    ]
}
```

Open a test file and start **Debug current test file** to stop at
breakpoints in the test, the editor or the core. Remove the `env` line to
watch the windows the test builds.

These configurations assume the editable installs. If you use
`PYTHONPATH` instead, add it to the `env` of each configuration, or set
it before starting VS Code or Cursor.

### PyCharm

1. Open the `nxt_editor` checkout as a project.
2. **Settings > Project > Python Interpreter > Add Interpreter > Add
   Local Interpreter**, choose **Existing**, and pick the python in
   `nxt-dev/.venv` (`Scripts/python.exe` on Windows, `bin/python`
   elsewhere).
3. **Settings > Project > Project Structure > Add Content Root**, and add
   the `nxt` core checkout. Mark the root of each checkout as
   **Sources**, so `nxt` and `nxt_editor` resolve from your checkouts.
   Run configurations add source roots to `PYTHONPATH` by default, so this
   also works without the editable installs.
4. **Settings > Tools > Python Integrated Tools**, set **Default test
   runner** to **pytest**.
5. To run the editor: **Run > Edit Configurations... > + > Python**.
   Switch **script** to **module**, enter `nxt.cli`, set **Parameters** to
   `ui` and **Working directory** to the `nxt_editor` checkout.
6. To run the tests: **Run > Edit Configurations... > + > pytest**. Set
   **Script path** to `nxt_editor/test` (or one test file) and
   **Working directory** to the `nxt_editor` checkout. Add
   `QT_QPA_PLATFORM=offscreen` under **Environment variables** to run
   without windows. Right click a test file or test to run or debug just
   that.

## Working inside a host

- **Blender**: `nxt_editor/integration/blender/nxt_blender.py`, installed
  on its own, runs the editor from your checkouts. See "Developing it" in
  [its README](nxt_editor/integration/blender/README.md). Use **NXT >
  Reload Code** after editing, as Blender keeps imported modules for the
  whole session.
- **Maya, and other hosts**: open the editor from the host's Python with
  your checkouts on `sys.path`, as in
  [Bootstrapping nxt in another host](docs/user_docs/docs/install.md#bootstrapping-nxt-in-another-host).
  Maya brings its own PySide6; Qt.py is the only other package it needs.

## License

By contributing, you agree that your contributions are released under the
project's [MIT License](LICENSE).
