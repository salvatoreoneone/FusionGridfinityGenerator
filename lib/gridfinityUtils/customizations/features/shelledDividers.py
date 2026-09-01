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

Dividers sit on gridfinity **unit boundaries** while there are enough units to go round:
a bin is a whole number of units and a divider separates whole units, so a 5u bin split
into 2 gives 3u then 2u. Ask for more compartments than the axis has units -- which
includes *every* split of a 1u axis -- and there is no whole-unit answer, so it falls
back to equal fractions of the cavity, the same rule the hollow path uses.

That fallback is also the fix for a bin 1u across getting no dividers at all: the count
used to be clamped to the unit count, which on a 1u axis is 1, and one compartment has no
divider behind it.

Two deliberate margins, both relying on a join being a no-op where material already
exists:

* the walls run the full footprint in their perpendicular direction rather than stopping
  at the cavity, so no sliver of gap is left where the cavity wall fillets curve away;
* they run down to the tub floor, the deepest point of the interior. A shelled bin is
  hollowed through its base feet, so each unit's interior bottoms out at
  `bodyBottom + shell` -- well below z = 0. A wall that stopped at z = 0 would leave a gap
  underneath the full depth of the base, which is what this used to do.

How tall each wall gets is `dividerRules`' decision, not this module's: a wall on a unit
boundary lands in the groove between the base feet of the bin above and may run to the
rim, and one that does not stops at the top of the label plate so the bin still stacks.
The top is never padded beyond the rim -- material above the bin would break stacking
outright.
"""

import adsk.core, adsk.fusion

from .. import binEnvelope
from .. import dividerRules
from .. import inputs as customInputs
from .. import parametrization
from ... import const, shapeUtils, combineUtils, commonUtils
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


def compartmentSizes(units, count):
    """Split `units` gridfinity units into `count` compartments, as evenly as the units
    allow. The remainder goes to the leading compartments: 5u into 2 gives 3u then 2u.

    Only valid while `count <= units`; above that there is no whole-unit split and
    wallPositions() falls back to equal fractions instead.
    """
    units = max(1, int(units))
    count = max(1, min(int(count), units))
    base, remainder = divmod(units, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def wallPositions(units, count, baseSize, xyClearance, thickness, cavityMin, cavityMax):
    """(start, isGridAligned) for each dividing wall on one axis, front to back.

    Two rules, picked by whether the units can be divided whole:

    * `count <= units` -- one wall per unit boundary, centred on it. The bin body starts
      one xyClearance inside the first unit, so the boundary after k units sits at
      `k * baseSize - xyClearance` in model space. On a 2u bin with a 32 mm base that is
      3.175, and a 1.2 mm wall centred there spans 3.115..3.235 -- exactly the hand-built
      rib this feature was translated from. Every wall is on a boundary by construction.

    * `count > units` -- equal fractions of the cavity, matching what the hollow path
      cuts. This is the only rule available on a 1u axis, and a wall then lands on a
      boundary only where the modulo happens to work out (a 2u bin split 4 ways has one
      wall on the middle boundary and two that miss).
    """
    units = max(1, int(units))
    count = max(1, int(count))
    if count <= 1:
        return []

    if count <= units:
        positions = []
        cumulative = 0
        for size in compartmentSizes(units, count)[:-1]:
            cumulative += size
            boundary = cumulative * baseSize - xyClearance
            positions.append((boundary - thickness / 2.0, True))
        return positions

    cellSize = (cavityMax - cavityMin - (count - 1) * thickness) / count
    # `cavityMin + index * (cellSize + thickness)` is where compartment `index` starts,
    # so the wall in front of it ends there and begins one thickness earlier -- the same
    # relation upstream's cutouts have (binBodyGenerator.py:125).
    return [(cavityMin + index * (cellSize + thickness) - thickness,
             dividerRules.isGridAligned(index, count, units))
            for index in range(1, count)]


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
    # The tub floor, computed rather than searched for. `simpleShell` hollows the whole
    # solid including the base feet, so the interior of every gridfinity unit bottoms out
    # one shell thickness above the underside of the bin -- the same expression the scoop
    # lands its ramps on. Looking for the lowest horizontal face instead finds a 0.095
    # sliver at the rim of the shell and leaves the walls hanging the full depth of the
    # base above the floor.
    bodyBottom = target.boundingBox.minPoint.z
    bottom = bodyBottom + float(shell)
    if top - bottom <= 0:
        futil.log('%s: no room between floor and rim, skipping' % NAME)
        return

    mode = customInputs.dividerHeightMode(context.commandInputs)
    cappedTop = dividerRules.cappedTopZ(binInput)

    walls = []
    # Across the width: walls running the full length.
    for x, aligned in wallPositions(binInput.binWidth, binInput.compartmentsByX,
                                    binInput.baseWidth, binInput.xyClearance, thickness,
                                    float(shell), float(footprintWidth) - float(shell)):
        walls.append((x, 0, thickness, footprintLength, aligned))
    # Along the length: walls running the full width.
    for y, aligned in wallPositions(binInput.binLength, binInput.compartmentsByY,
                                    binInput.baseLength, binInput.xyClearance, thickness,
                                    float(shell), float(footprintLength) - float(shell)):
        walls.append((0, y, footprintWidth, thickness, aligned))

    if not walls:
        futil.log('%s: nothing to divide' % NAME)
        return

    bodies = []
    raised = 0
    for originX, originY, width, length, aligned in walls:
        wallTop = top if dividerRules.isFullHeight(mode, aligned) else cappedTop
        height = wallTop - bottom
        if height <= const.DEFAULT_FILTER_TOLERANCE:
            continue
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
        if wallTop >= top - const.DEFAULT_FILTER_TOLERANCE:
            raised += 1

    if not bodies:
        futil.log('%s: no room for any divider, skipping' % NAME)
        return

    # Below z = 0 the walls would otherwise run straight through the chamfered flanks of
    # the feet and the V grooves between them, putting material where a baseplate or the
    # lip of the bin below has to go. Above z = 0 the body is a plain prism and nothing
    # needs trimming, so this only runs when there is a base at all.
    if bodyBottom < -const.DEFAULT_FILTER_TOLERANCE and context.baseGeneratorInput is not None:
        prism = binEnvelope.footprintPrism(component, binInput, bodyBottom, top)
        imprint = binEnvelope.baseImprint(
            component, binInput, context.baseGeneratorInput, bodyBottom)
        binEnvelope.clip(component, bodies, prism, imprint)
        binEnvelope.discard(component, prism, imprint)

    combineUtils.joinBodies(target, commonUtils.objectCollectionFromList(bodies), component)
    futil.log('%s: added %d divider walls, %d to the rim and %d capped at %.4f '
              '(grid %sx%s, mode %s)'
              % (NAME, len(bodies), raised, len(bodies) - raised, cappedTop,
                 int(binInput.compartmentsByX), int(binInput.compartmentsByY), mode))
    futil.log('%s: walls stand on the tub floor at %.4f' % (NAME, bottom))
