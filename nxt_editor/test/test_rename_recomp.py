"""Renaming a node nothing else composites against must not rebuild.

nxt.stage.set_node_name updates the comp layer in place when it safely
can, but the editor command that drives it treated NAME like any other
attribute in REQUIRES_RECOMP and rebuilt the stage regardless, throwing
that work away. Renaming a node you had just made, on the only layer
there is, went the long way round.

These count calls to build_stage rather than timing anything, so they say
what actually happened instead of how fast the machine felt.
"""
# Builtin
import os
import sys
import unittest

# External
from Qt import QtWidgets

# Internal
from nxt import nxt_path
from nxt.session import Session
from nxt_editor import stage_model
from nxt_editor.commands import RenameNode

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

# The targeted rename lives in nxt_core. Against an older released core
# these sit out rather than failing for something this repo cannot fix.
from nxt.stage import Stage  # noqa: E402

HAS_TARGETED_RENAME = hasattr(Stage, 'can_rename_targeted')
NEEDS_CORE = 'needs an nxt_core with can_rename_targeted'


class RebuildCounter(object):
    """Counts stage rebuilds over a block of work."""

    def __init__(self, model):
        self.model = model
        self.count = 0
        self._real = None

    def __enter__(self):
        self._real = self.model.stage.build_stage

        def counted(*args, **kwargs):
            self.count += 1
            return self._real(*args, **kwargs)

        self.model.stage.build_stage = counted
        return self

    def __exit__(self, *exc):
        self.model.stage.build_stage = self._real
        return False


@unittest.skipUnless(HAS_TARGETED_RENAME, NEEDS_CORE)
class RenameDoesNotRebuild(unittest.TestCase):

    def setUp(self):
        os.chdir(os.path.dirname(__file__))
        # An empty graph, so there is only ever one layer and nothing can
        # be composited against.
        self.stage = Session().new_file()
        self.model = stage_model.StageModel(self.stage)
        self.layer_path = self.model.top_layer.real_path

    def add(self, name, parent=nxt_path.WORLD):
        path = nxt_path.join_node_paths(parent, name)
        self.model.add_node(name=name, data=None, parent_path=parent,
                            layer=self.model.top_layer)
        return path

    def rename(self, path, new_name):
        command = RenameNode(path, new_name, self.model, self.layer_path)
        command.redo()
        return command

    def test_lone_node_rename_does_not_rebuild(self):
        path = self.add('lonely')
        with RebuildCounter(self.model) as counter:
            command = self.rename(path, 'renamed')
        self.assertEqual(0, counter.count,
                         'renaming a node by itself rebuilt the stage')
        self.assertIsNotNone(self.model.comp_layer.lookup('/renamed'))
        self.assertIsNone(self.model.comp_layer.lookup('/lonely'))
        self.assertEqual('/renamed', command.return_value)

    def test_child_rename_does_not_rebuild(self):
        self.add('parent')
        child = self.add('child', parent='/parent')
        with RebuildCounter(self.model) as counter:
            self.rename(child, 'renamed')
        self.assertEqual(0, counter.count,
                         'renaming a node in a hierarchy rebuilt the stage')
        self.assertIsNotNone(self.model.comp_layer.lookup('/parent/renamed'))
        self.assertIsNone(self.model.comp_layer.lookup('/parent/child'))

    def test_undo_does_not_rebuild_either(self):
        path = self.add('lonely')
        command = self.rename(path, 'renamed')
        with RebuildCounter(self.model) as counter:
            command.undo()
        self.assertEqual(0, counter.count, 'undoing a rename rebuilt')
        self.assertIsNotNone(self.model.comp_layer.lookup('/lonely'))
        self.assertIsNone(self.model.comp_layer.lookup('/renamed'))

    def test_rename_onto_an_existing_name_still_rebuilds(self):
        # get_unique_node_name makes this a rename to a free name, but the
        # guard is what decides, so check the decision directly.
        self.add('one')
        self.add('two')
        can, why = self.stage.can_rename_targeted('/one', '/two',
                                                  self.model.top_layer,
                                                  self.model.comp_layer)
        self.assertFalse(can, why)

    def test_renaming_a_parent_still_rebuilds(self):
        # Every descendant's path changes with it, which the in place
        # update does not handle, so this one has to take the long way.
        self.add('parent')
        self.add('child', parent='/parent')
        can, why = self.stage.can_rename_targeted('/parent', '/renamed',
                                                  self.model.top_layer,
                                                  self.model.comp_layer)
        self.assertFalse(can, why)
        with RebuildCounter(self.model) as counter:
            self.rename('/parent', 'renamed')
        self.assertEqual(1, counter.count,
                         'renaming a parent must still rebuild')
        self.assertIsNotNone(self.model.comp_layer.lookup('/renamed/child'))


if __name__ == '__main__':
    unittest.main()
