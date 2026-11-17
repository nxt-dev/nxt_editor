"""Laying out top level nodes by the order they run in.

Each exec chain runs left to right, one column per step. Where a node has
more than one node after it, the first carries on along the same row and
the others start rows of their own below, each laid out the same way.
Nodes on no chain sit in a row each, in the order they are given.

Only where things go is worked out here, in plain numbers, so it can be
tested without a graph. See StageView.layout_nodes for the graph side.
"""

#: Room left between columns and between rows, in scene units.
GAP_X = 80.0
GAP_Y = 40.0


def grid(paths, exec_in):
    """Which column and row each node goes in.

    :param paths: the nodes, in the order rows are given out: the first
        node of a chain or a branch earlier in the list gets the higher row
    :param exec_in: {path: the node it runs after, or None}
    :return: {path: (column, row)}
    """
    chosen = set(paths)
    followers = dict((path, []) for path in paths)
    heads = []
    for path in paths:
        source = exec_in.get(path)
        if source in chosen and source != path:
            followers[source].append(path)
        else:
            heads.append(path)
    cells = {}
    next_row = [0]

    def walk(start):
        # Depth first, without recursion so a long chain cannot run out of
        # stack. A branch's row is given out when it is reached, so
        # everything that branches off the first branch comes before the
        # second.
        stack = [(start, 0, None)]
        while stack:
            path, column, row = stack.pop()
            if path in cells:
                continue
            if row is None:
                row = next_row[0]
                next_row[0] += 1
            cells[path] = (column, row)
            after = [p for p in followers[path] if p not in cells]
            for index in reversed(range(len(after))):
                stack.append((after[index], column + 1,
                              row if index == 0 else None))
    for head in heads:
        walk(head)
    # A loop of exec connections has no head. Its nodes start where they
    # are first met.
    for path in paths:
        if path not in cells:
            walk(path)
    return cells


def arrange(paths, exec_in, sizes, gap_x=GAP_X, gap_y=GAP_Y):
    """Where the top left of each node goes, from (0, 0).

    Each column is as wide as its widest node and each row as tall as its
    tallest, so nothing overlaps whatever their sizes.

    :param paths: see grid
    :param exec_in: see grid
    :param sizes: {path: (width, height)}
    :return: {path: (x, y)}
    """
    cells = grid(paths, exec_in)
    widths = {}
    heights = {}
    for path, (column, row) in cells.items():
        width, height = sizes.get(path, (0.0, 0.0))
        widths[column] = max(widths.get(column, 0.0), width)
        heights[row] = max(heights.get(row, 0.0), height)
    xs = {}
    x = 0.0
    for column in sorted(widths):
        xs[column] = x
        x += widths[column] + gap_x
    ys = {}
    y = 0.0
    for row in sorted(heights):
        ys[row] = y
        y += heights[row] + gap_y
    return dict((path, (xs[column], ys[row]))
                for path, (column, row) in cells.items())
