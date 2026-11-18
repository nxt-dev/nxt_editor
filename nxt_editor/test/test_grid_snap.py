"""Snapping to the grid goes to the nearest grid line."""
# Builtin
import unittest

# Internal
from nxt import GRID_SIZE
from nxt_editor.stage_model import StageModel


class SnapsToTheNearestLine(unittest.TestCase):

    def snap(self, x, y):
        return StageModel.snap_pos_to_grid((x * GRID_SIZE, y * GRID_SIZE))

    def test_just_short_of_a_line_goes_up_to_it(self):
        self.assertEqual([GRID_SIZE, 2 * GRID_SIZE], self.snap(.9, 1.8))

    def test_just_past_a_line_goes_back_to_it(self):
        self.assertEqual([GRID_SIZE, 2 * GRID_SIZE], self.snap(1.2, 2.3))

    def test_negative_positions_go_to_the_nearest_too(self):
        self.assertEqual([-GRID_SIZE, 0], self.snap(-.9, -.2))

    def test_half_way_goes_up_both_sides_of_zero(self):
        self.assertEqual([GRID_SIZE, 0], self.snap(.5, -.5))

    def test_on_a_line_stays_there(self):
        self.assertEqual([3 * GRID_SIZE, -2 * GRID_SIZE], self.snap(3, -2))


if __name__ == '__main__':
    unittest.main()
