# Reference

The reference is split into pages:

- **[Using the Editor](editor.md)**: the editor's panels, what each one is
  for and how to use it.
- **[Graphs and Nodes](graphs.md)**: the stage, nodes, attributes, tokens,
  code and the order nodes run in.
- **[Layers and References](composition.md)**: how layers stack, how they
  pull each other in, and how nodes inherit from parents and instances.
- **[File Format and Design](file_format.md)**: what is in a `.nxt` file,
  and why nxt works the way it does.
- **[Hotkeys](hotkeys.md)**: every shortcut, and how to change them.

<script>
(function () {
  var pages = {
    "ai-assistant": "../editor/",
    "animate-nodes": "../editor/",
    "application-structure": "../file_format/",
    "attributes": "../graphs/",
    "auto-pairing": "../editor/",
    "autocomplete-options": "../editor/",
    "build-view": "../editor/",
    "code-editor": "../editor/",
    "completion": "../editor/",
    "composition-inside-node-hierarchies": "../composition/",
    "compute": "../graphs/",
    "deleting-and-pasting-nodes": "../editor/",
    "design-philosophy": "../file_format/",
    "discovery": "../file_format/",
    "docks-and-layout": "../editor/",
    "editors": "../editor/",
    "example-graphs": "../editor/",
    "execution-order": "../graphs/",
    "execution-plugs": "../graphs/",
    "execution-root": "../graphs/",
    "file-format-and-design": "../file_format/",
    "find-and-replace": "../editor/",
    "following-tokens": "../editor/",
    "functionalprocedural": "../file_format/",
    "go-to-line": "../editor/",
    "graphs-and-nodes": "../graphs/",
    "hierarchiesstacks": "../graphs/",
    "highlighting": "../editor/",
    "how-it-works-with-the-graph": "../editor/",
    "how-references-are-found": "../composition/",
    "instancing": "../composition/",
    "layer-manager": "../editor/",
    "layers": "../composition/",
    "layers-and-references": "../composition/",
    "memory": "../editor/",
    "mini-map": "../editor/",
    "node": "../graphs/",
    "node-paths-and-their-attributes": "../editor/",
    "nxt-file-spec": "../file_format/",
    "property-editor-history-view-output-log-and-workflow-tools": "../editor/",
    "python-analysis-with-jedi": "../editor/",
    "reading-code-and-imports": "../editor/",
    "reference-editor": "../editor/",
    "references": "../composition/",
    "reload-source": "../editor/",
    "show-in-explorer": "../editor/",
    "signing-in": "../editor/",
    "stage": "../graphs/",
    "stage-composition": "../composition/",
    "stage-view": "../editor/",
    "stagelayer-node": "../graphs/",
    "terms-and-definitions": "../graphs/",
    "the-parts-of-the-panel": "../editor/",
    "tokens": "../graphs/",
    "using-the-editor": "../editor/",
    "why-not-houdini": "../file_format/",
    "why-not-visual-programming": "../file_format/"
  };
  var anchor = window.location.hash.slice(1);
  if (pages[anchor]) {
    window.location.replace(pages[anchor] + "#" + anchor);
  }
})();
</script>
