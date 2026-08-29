"""Compartment dividers for shelled bins.

Shelled bins never get compartments: entry.py sets `isSolid = isSolid or isShelled`, and
binBodyGenerator.py:112 builds compartments only `if not input.isSolid`. So the Grid
width/length inputs are silently inert for this bin type -- present in the dialog, doing
nothing. This makes them work, adding divider walls where the hollow path cuts
compartment cavities.

Translated from a hand-built model: a Rib on a midplane between the two outer side
faces, drawn from a line at the top of the bin and grown down until it met material.

Ribs cannot be reproduced directly -- adsk.fusion.RibFeatures exposes only count/item
/itemByName, with no createInput or add, and there is no RibFeatureInput class at all.
The same wall is therefore built as a solid box and joined.

Spacing mirrors the hollow path exactly (binBodyGenerator.py:118-122), so the two bin
types divide identically. On the hand-built 2x1 bin that formula lands the wall at
3.115..3.235 cm, which is precisely where the rib measured.

Two deliberate margins, both relying on a join being a no-op where material already
exists:

* the walls run the full footprint in their perpendicular direction rather than stopping
  at the cavity, so no sliver of gap is left where the cavity wall fillets curve away;
* they extend one shell thickness below the cavity floor, so they always merge into the
  floor slab rather than risking a hairline gap under the wall.

The top is *not* padded: material above the bin would break stacking.
"""

import adsk.core, adsk.fusion

from .. import parametrization
from ... import const, shapeUtils, combineUtils, commonUtils, geometryUtils, faceUtils
from .... import fusion360utils as futil

NAME = 'Shelled dividers'

BIN_TYPE_INPUT_ID = 'bin_type'
BIN_TYPE_SHELLED = 'Shelled'


def _isShelled(commandInputs) -> bool:
    if commandInputs is None:
        return False
    dropdown = commandInputs.itemById(BIN_TYPE_INPUT_ID)
    item = dropdown.selectedItem if dropdown else None
    return bool(item) and item.name == BIN_TYPE_SHELLED


def isEnabled(context) -> bool:
    binInput = context.binBodyInput
    if binInput is None or not _isShelled(context.commandInputs):
        return False
    try:
        return float(binInput.compartmentsByX) > 1 or float(binInput.compartmentsByY) > 1
    except Exception:
        return False


def _targetBody(component: adsk.fusion.Component):
    solids = [body for body in component.bRepBodies if body.isSolid]
    return max(solids, key=lambda body: body.volume) if solids else None


def _cavityFloor(body: adsk.fusion.BRepBody, minX, maxX, minY, maxY, top):
    """Z of the floor the dividers stand on.

    Found by rule rather than derived: the shell floor depends on the shell operation
    and on whether a lip is present, and measuring it is both simpler and less likely to
    drift than reproducing that chain. The largest horizontal face lying inside the
    cavity footprint, above the gridfinity base and below the rim, is the floor.

    The base bound matters. The bin body is built from z = 0 upward and the base foot
    hangs below it, and the foot's chamfered underside is horizontal, sits inside the
    cavity footprint and is large -- so without this it wins on area and the dividers get
    driven a shell thickness below the bin.
    """
    candidates = []
    for face in body.faces:
        if not geometryUtils.isHorizontal(face):
            continue
        box = face.boundingBox
        if box.minPoint.z <= const.DEFAULT_FILTER_TOLERANCE:
            continue
        if box.minPoint.z >= top - const.DEFAULT_FILTER_TOLERANCE:
            continue
        if (box.minPoint.x < minX - 0.01 or box.maxPoint.x > maxX + 0.01
                or box.minPoint.y < minY - 0.01 or box.maxPoint.y > maxY + 0.01):
            continue
        candidates.append(face)
    if not candidates:
        return None
    return faceUtils.maxByArea(candidates).boundingBox.minPoint.z


def _wallPositions(cavityMin, cavityMax, count, thickness):
    """Start coordinates of the dividing walls, mirroring binBodyGenerator.py:121."""
    count = int(count)
    if count < 2:
        return []
    cellSize = (cavityMax - cavityMin - (count - 1) * thickness) / count
    return [cavityMin + index * cellSize + (index - 1) * thickness
            for index in range(1, count)]


def applyToBin(context):
    binInput = context.binBodyInput
    component = context.targetComponent
    if binInput is None or component is None:
        return

    target = _targetBody(component)
    if target is None:
        futil.log('%s: no solid body, skipping' % NAME)
        return

    thickness = binInput.wallThickness
    # Shelled bins are hollowed to wallThickness - xyClearance (entry.py:1017).
    shell = binInput.wallThickness - binInput.xyClearance

    footprintWidth = binInput.baseWidth * binInput.binWidth - binInput.xyClearance * 2.0
    footprintLength = binInput.baseLength * binInput.binLength - binInput.xyClearance * 2.0

    top = target.boundingBox.maxPoint.z
    floor = _cavityFloor(target,
                         float(shell), float(footprintWidth) - float(shell),
                         float(shell), float(footprintLength) - float(shell),
                         top)
    if floor is None:
        futil.log('%s: could not locate the cavity floor, skipping' % NAME)
        return

    # Never below the bin itself: overshooting the floor would push material out of the
    # underside, which the bounding box would show and a print would not forgive.
    bottom = max(floor - float(shell), target.boundingBox.minPoint.z)
    height = top - bottom
    if height <= 0:
        futil.log('%s: no room between floor and rim, skipping' % NAME)
        return

    walls = []
    # Across the width: walls running the full length.
    for x in _wallPositions(shell, footprintWidth - shell,
                            binInput.compartmentsByX, thickness):
        walls.append((x, 0, thickness, footprintLength))
    # Along the length: walls running the full width.
    for y in _wallPositions(shell, footprintLength - shell,
                            binInput.compartmentsByY, thickness):
        walls.append((0, y, footprintWidth, thickness))

    if not walls:
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
        wall.name = 'Divider wall'
        bodies.append(wall)

    combineUtils.joinBodies(target, commonUtils.objectCollectionFromList(bodies), component)
    futil.log('%s: added %d divider walls (grid %sx%s)'
              % (NAME, len(bodies), int(binInput.compartmentsByX), int(binInput.compartmentsByY)))
