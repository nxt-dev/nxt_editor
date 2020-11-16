# First time setup

Use `docs/docs_env.yml` to build a python env for building docs.

`conda activate` that environment.

# If sphinx needs set up

**docs/conf.py doesn't exist**

- `mkdir docs`

- `cd docs`

- `$ sphinx-quickstart`

- Note where `conf.py` is built for the next step.

- Set options in `conf.py`

  - add desired extensions into the `extensions`

    - `'sphinx.ext.autodoc'` for pulling your docstrings from the source.

      - do a `sys.path.insert(0, os.path.abspath('../..'))` to put your modules in the documentation build path. Path is relative to conf.py

    - `'sphinx.ext.viewcode'` to add the "view source" button to your docs

  - `autodoc_member_order = 'bysource'` orders your code by it's source order, rather than alphabetical.

  - `html_theme = 'sphinx_rtd_theme'` requires the reed the docs theme available via `pip install sphinx-rtd-theme`

# Building

Api docs build is automted via `build/api_docs.nxt`, can be run from the `/build` startpoint to only build html to `docs/api_docs/build` or from `/deploy` start point to built html into `docs/user_docs/api`
