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

Dividers sit on gridfinity **unit boundaries**, not at equal fractions of the cavity. A
bin is a whole number of units and a divider separates whole units, so a 5u bin split
into 2 gives 3u then 2u, and a count above the unit count is clamped. This differs from
the hollow path, which divides the cavity evenly; the two agree only when the compartment
count equals the unit count.

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
from ... import const, shapeUtils, combineUtils, commonUtils, geometryUtils
from .... import fusion360utils as futil

NAME = 'Shelled dividers'

BIN_TYPE_INPUT_ID = 'bin_type'
BIN_TYPE_SHELLED = 'Shelled'


def isShelled(commandInputs) -> bool:
    if commandInputs is None:
        return False
    dropdown = commandInputs.itemById(BIN_TYPE_INPUT_ID)
    item = dropdown.selectedItem if dropdown else None
    return bool(item) and item.name == BIN_TYPE_SHELLED


def isEnabled(context) -> bool:
    binInput = context.binBodyInput
    if binInput is None or not isShelled(context.commandInputs):
        return False
    try:
        return float(binInput.compartmentsByX) > 1 or float(binInput.compartmentsByY) > 1
    except Exception:
        return False


def targetBody(component: adsk.fusion.Component):
    solids = [body for body in component.bRepBodies if body.isSolid]
    return max(solids, key=lambda body: body.volume) if solids else None


def cavityFloor(body: adsk.fusion.BRepBody, minX, maxX, minY, maxY, top):
    """Z of the floor the dividers stand on.

    Found by rule rather than derived: the shell floor depends on the shell operation
    and on whether a lip is present, and measuring it is both simpler and less likely to
    drift than reproducing that chain. The floor is the *lowest* horizontal face lying
    inside the cavity footprint, above the gridfinity base and below the rim.

    Lowest, not largest. A label tab puts a wide horizontal ledge high in the cavity --
    on a 2x1x1 bin that ledge measures 3.894 against the floor's 0.412 -- so picking by
    area plants the dividers on the label and leaves a stub from 1.855 to the rim instead
    of a full-height wall. Depth is what identifies a floor here; size is not.

    The base bound matters too. The bin body is built from z = 0 upward and the base foot
    hangs below it, and the foot's chamfered underside is horizontal and sits inside the
    cavity footprint, so without it the dividers get driven below the bin.
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
    return min(face.boundingBox.minPoint.z for face in candidates)


def compartmentSizes(units, count):
    """Split `units` gridfinity units into `count` compartments, as evenly as the units
    allow. The remainder goes to the leading compartments: 5u into 2 gives 3u then 2u.

    A compartment is a whole number of units, so `count` cannot exceed `units` and is
    clamped. Use clampedCount() to find out whether that happened.
    """
    units = max(1, int(units))
    count = clampedCount(units, count)
    base, remainder = divmod(units, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def clampedCount(units, count):
    return max(1, min(int(count), max(1, int(units))))


def wallPositions(units, count, baseSize, xyClearance, thickness):
    """Start coordinates of the dividing walls, centred on gridfinity unit boundaries.

    Dividers belong on unit boundaries, not at equal fractions of the cavity: a bin is a
    whole number of units and a divider separates whole units. The bin body starts one
    xyClearance inside the first unit, so the boundary after k units sits at
    k * baseSize - xyClearance in model space. On a 2u bin with a 32 mm base that is
    3.175, and a 1.2 mm wall centred there spans 3.115..3.235 -- exactly the hand-built
    rib this feature was translated from.

    Dividing the cavity into equal fractions instead only agrees with this when the
    compartment count equals the unit count. At 2 units with 3 compartments it puts walls
    at 2.13 and 4.22, aligned to nothing.
    """
    sizes = compartmentSizes(units, count)
    positions = []
    cumulative = 0
    for size in sizes[:-1]:
        cumulative += size
        boundary = cumulative * baseSize - xyClearance
        positions.append(boundary - thickness / 2.0)
    return positions


def _logClamp(axis, units, requested):
    """A compartment is a whole number of units, so more compartments than units cannot
    be built. Clamping is silent in the model; this is the only trace of it."""
    used = clampedCount(units, requested)
    if used != int(requested):
        futil.log('%s: %s asks for %d compartments but the bin is %du, using %d'
                  % (NAME, axis, int(requested), int(units), used))


def applyToBin(context):
    binInput = context.binBodyInput
    component = context.targetComponent
    if binInput is None or component is None:
        return

    target = targetBody(component)
    if target is None:
        futil.log('%s: no solid body, skipping' % NAME)
        return

    thickness = binInput.wallThickness
    # Shelled bins are hollowed to wallThickness - xyClearance (entry.py:1017).
    shell = binInput.wallThickness - binInput.xyClearance

    footprintWidth = binInput.baseWidth * binInput.binWidth - binInput.xyClearance * 2.0
    footprintLength = binInput.baseLength * binInput.binLength - binInput.xyClearance * 2.0

    top = target.boundingBox.maxPoint.z
    floor = cavityFloor(target,
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

    _logClamp('width', binInput.binWidth, binInput.compartmentsByX)
    _logClamp('length', binInput.binLength, binInput.compartmentsByY)

    walls = []
    # Across the width: walls running the full length.
    for x in wallPositions(binInput.binWidth, binInput.compartmentsByX,
                           binInput.baseWidth, binInput.xyClearance, thickness):
        walls.append((x, 0, thickness, footprintLength))
    # Along the length: walls running the full width.
    for y in wallPositions(binInput.binLength, binInput.compartmentsByY,
                           binInput.baseLength, binInput.xyClearance, thickness):
        walls.append((0, y, footprintWidth, thickness))

    if not walls:
        futil.log('%s: nothing to divide' % NAME)
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
