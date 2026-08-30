"""Raise the compartment dividers of a hollow bin to the rim.

Hollow and shelled bins disagree about how tall a divider is:

* shelled -- `shelledDividers` builds each wall as a box up to the top of the body, so
  the dividers finish flush with the lip rim;
* hollow -- upstream cuts the compartments from `binBodyTotalHeight` downwards, which
  already stops the dividers at the bottom of the lip, and then
  `binBodyGenerator.py:164` shaves another `BIN_TAB_TOP_CLEARANCE` off the whole inner
  top whenever there is more than one compartment.

On a 3x1 bin with a lip that is a 4.3 mm step: the shelled dividers reach z = 2.38 and
the hollow ones stop at 1.95. This closes the gap from the hollow side, joining a wall
of material over each divider from the shaved shelf up to the top of the bin.

Additive, like the rest of this fork: upstream still cuts its clearance slab, and this
fills it back in along with the void the lip leaves above. A join is a no-op where
material already exists, so the walls run the full footprint in their perpendicular
direction rather than stopping at the compartment bounds -- no sliver is left where the
lip's inner chamfer curves away.

**This gives up stacking.** The raised wall crosses the lip opening, which is where the
base feet of the bin above would seat. That is what upstream's clearance slab protects,
and matching the shelled bins means accepting the same trade.

Custom compartment layouts are respected: a compartment that spans two cells of the grid
has no wall between them, and raising one there would bridge its top. Grid lines a
compartment crosses are therefore raised row by row, skipping the rows it covers.
"""

import adsk.core, adsk.fusion

from ... import const, shapeUtils, combineUtils, commonUtils
from .... import fusion360utils as futil

NAME = 'Full-height dividers'

BIN_TYPE_INPUT_ID = 'bin_type'
BIN_TYPE_HOLLOW = 'Hollow'


def isHollow(commandInputs) -> bool:
    if commandInputs is None:
        return False
    dropdown = commandInputs.itemById(BIN_TYPE_INPUT_ID)
    item = dropdown.selectedItem if dropdown else None
    return bool(item) and item.name == BIN_TYPE_HOLLOW


def isEnabled(context) -> bool:
    binInput = context.binBodyInput
    if binInput is None or not isHollow(context.commandInputs):
        return False
    # Upstream only shaves the divider tops when there is more than one compartment
    # (binBodyGenerator.py:164), and with a single compartment there is no divider to
    # raise either way.
    try:
        return len(binInput.compartments) > 1
    except Exception:
        return False


def targetBody(component: adsk.fusion.Component):
    solids = [body for body in component.bRepBodies if body.isSolid]
    return max(solids, key=lambda body: body.volume) if solids else None


class _Grid():
    """The compartment grid, on the generator's own terms.

    Every number here is copied from binBodyGenerator.py:113-122 rather than measured,
    so the walls land exactly where the compartment cutouts left them.
    """

    def __init__(self, binInput):
        self.wallThickness = float(binInput.wallThickness)
        self.bodyWidth = (float(binInput.baseWidth) * float(binInput.binWidth)
                          - float(binInput.xyClearance) * 2.0)
        self.bodyLength = (float(binInput.baseLength) * float(binInput.binLength)
                           - float(binInput.xyClearance) * 2.0)

        self.minX = self.wallThickness
        self.maxX = self.bodyWidth - self.wallThickness
        self.minY = (float(const.BIN_LIP_WALL_THICKNESS) - float(binInput.xyClearance)) \
            if (binInput.hasLip and binInput.hasScoop) else self.wallThickness
        self.maxY = self.bodyLength - self.wallThickness

        self.countX = max(1, int(binInput.compartmentsByX))
        self.countY = max(1, int(binInput.compartmentsByY))
        self.unitWidth = (self.maxX - self.minX
                          - (self.countX - 1) * self.wallThickness) / self.countX
        self.unitLength = (self.maxY - self.minY
                           - (self.countY - 1) * self.wallThickness) / self.countY
        self.compartments = list(binInput.compartments)

    def cellX(self, column):
        return self.minX + column * (self.unitWidth + self.wallThickness)

    def cellY(self, row):
        return self.minY + row * (self.unitLength + self.wallThickness)

    def spansColumns(self, column, row):
        """True when one compartment covers both `column` and `column + 1` on `row`, so
        there is no wall on the grid line between them."""
        for c in self.compartments:
            if (int(c.positionX) <= column and int(c.positionX) + int(c.width) >= column + 2
                    and int(c.positionY) <= row < int(c.positionY) + int(c.length)):
                return True
        return False

    def spansRows(self, row, column):
        for c in self.compartments:
            if (int(c.positionY) <= row and int(c.positionY) + int(c.length) >= row + 2
                    and int(c.positionX) <= column < int(c.positionX) + int(c.width)):
                return True
        return False


def _clamp(value, low, high):
    return max(low, min(value, high))


def wallFootprints(binInput):
    """(originX, originY, width, length) of every divider to raise.

    A grid line no compartment crosses is raised in one piece spanning the whole
    footprint, which is both cheaper and cleaner at the lip. One that is crossed is
    raised only on the rows where a wall actually exists, each extended by a wall
    thickness so the crossings with the perpendicular dividers come up too.
    """
    grid = _Grid(binInput)
    walls = []

    for column in range(grid.countX - 1):
        x = grid.cellX(column) + grid.unitWidth
        rows = [row for row in range(grid.countY) if not grid.spansColumns(column, row)]
        if not rows:
            continue
        if len(rows) == grid.countY:
            walls.append((x, 0.0, grid.wallThickness, grid.bodyLength))
            continue
        for row in rows:
            y0 = _clamp(grid.cellY(row) - grid.wallThickness, 0.0, grid.bodyLength)
            y1 = _clamp(grid.cellY(row) + grid.unitLength + grid.wallThickness,
                        0.0, grid.bodyLength)
            walls.append((x, y0, grid.wallThickness, y1 - y0))

    for row in range(grid.countY - 1):
        y = grid.cellY(row) + grid.unitLength
        columns = [c for c in range(grid.countX) if not grid.spansRows(row, c)]
        if not columns:
            continue
        if len(columns) == grid.countX:
            walls.append((0.0, y, grid.bodyWidth, grid.wallThickness))
            continue
        for column in columns:
            x0 = _clamp(grid.cellX(column) - grid.wallThickness, 0.0, grid.bodyWidth)
            x1 = _clamp(grid.cellX(column) + grid.unitWidth + grid.wallThickness,
                        0.0, grid.bodyWidth)
            walls.append((x0, y, x1 - x0, grid.wallThickness))

    return walls


def applyToBin(context):
    binInput = context.binBodyInput
    component = context.targetComponent
    if binInput is None or component is None:
        return

    target = targetBody(component)
    if target is None:
        futil.log('%s: no solid body, skipping' % NAME)
        return

    # Where upstream leaves the divider tops: the body top, less the clearance slab it
    # shaves off the whole inner region (binBodyGenerator.py:164-181).
    binHeightWithoutBase = float(binInput.binHeight) - 1
    bodyTop = (binHeightWithoutBase * float(binInput.heightUnit)
               + max(0.0, float(binInput.heightUnit) - float(const.BIN_BASE_HEIGHT)))
    bottom = bodyTop - float(const.BIN_TAB_TOP_CLEARANCE)

    # The rim, measured rather than derived: with a lip it is the lip top, without one
    # the body top, and the lip's own top recess comes off either way.
    top = target.boundingBox.maxPoint.z
    height = top - bottom
    if height <= const.DEFAULT_FILTER_TOLERANCE:
        futil.log('%s: dividers already reach the rim, nothing to do' % NAME)
        return

    walls = wallFootprints(binInput)
    if not walls:
        futil.log('%s: no dividers to raise' % NAME)
        return

    bodies = []
    for originX, originY, width, length in walls:
        wall = shapeUtils.simpleBox(
            component.xYConstructionPlane,
            bottom,
            width,
            length,
            height,
            adsk.core.Point3D.create(originX, originY, bottom),
            component,
        )
        wall.name = 'Divider extension'
        bodies.append(wall)

    combineUtils.joinBodies(target, commonUtils.objectCollectionFromList(bodies), component)
    futil.log('%s: raised %d divider(s) from %.4f to %.4f (grid %sx%s)'
              % (NAME, len(bodies), bottom, top,
                 int(binInput.compartmentsByX), int(binInput.compartmentsByY)))
