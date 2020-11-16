# mkdocs install Notes

mkdocs is very well documented, go figure 
https://www.mkdocs.org/

# Setup
1. Create a conda environment based on nxt_user_docs_env.yml; `nxtuserdocs`
2. Launch anaconda shell, `conda activate nxtuserdocs`
3. Navigate to `~/project/nxt/docs/user_docs/`, run `mkdocs serve`
4. point your brower to: http://127.0.0.1:8000/

# Theme
- Currently using an overloaded `mkdocs` default theme, set in `mkdocs.yml`
- To switch themes, clone the theme of your choice https://github.com/mkdocs/mkdocs/wiki/MkDocs-Themes
- Specify that theme in the `mkdocs.yml`. Be sure to comment out the `custom_dir` as that CSS is relative to the `mkdocs` theme

        theme:
        name: material
        # name: mkdocs
        highlightjs: true
        hljs_style: tomorrow-night
        hljs_languages:
            - yaml
            - json
            - python
        # custom_dir: custom_theme/

        # extra_css: [extra.css]

# Changing CSS
- In chrome, right click and `inspect`.
- Click through the html to hilight the element you want to look at.
- In the styles tab, override the CSS to prototype live in your page, then apply that change in `bootstrap.css` or `base.css`
- If you have another theme, you need to specify another `custom_dir` in your `mkdocs.yml`

# Editing
I've been using https://marktext.app/
I turned on auto save, and chagnes get picked up by server right away
marktext supports drag/drop image placement, but does with absolute paths. 

Place images in `/images` and drag drop, then strip the absolute path.

# Publishing

`mkdocs gh-deploy`


