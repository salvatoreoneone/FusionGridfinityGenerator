"""Scoop for shelled bins.

The scoop is Hollow-only upstream, behind two independent gates:

    entry.py:954   binBodyInput.isSolid  = isSolid or isShelled
    entry.py:956   binBodyInput.hasScoop = has_scoop.value and isHollow

Line 956 ands the checkbox with `isHollow`, so ticking "Add scoop" on a shelled bin
resolves to False with nothing to say it was ignored. And even without that, line 954
marks shelled bins solid, so `binBodyGenerator.py:112`'s `if not input.isSolid:` skips
the whole compartment block -- which is where the scoop is built. Same root cause as the
missing compartments, so this reads the raw checkbox rather than the suppressed
`binBodyInput.hasScoop`.

**The scoop is a joined solid, not a fillet.** The first version filleted the concave
corner between the front cavity wall and the floor, which is how you would draw it by
hand on a hollow bin. A shelled bin has no such corner: the shell hollows the *base feet*
as well, so each gridfinity unit's interior is a tub bottoming out at `bodyBottom + shell`
and rising through the foot's chamfer profile to meet the vertical wall. Measured on a
1x3x1 at a 25 mm height unit, the tub floor sits at z = -0.405 and the wall starts at
z = 0.0144, leaving a 45 degree ramp 2.15 mm long for an 18.86 mm radius to roll along.
Fusion reported success and returned a trimmed sliver spanning y 0.095..0.31,
z -0.2006..0.6739, with the front of the floor consumed. Sizing the radius down to what
that ramp can carry would give a 2 mm scoop, which is not worth having.

So the ramp is built instead: a box the height and depth of the radius, with a cylinder of
that radius cut out of it, joined to the bin. It lands on the tub floor, so the scoop
sweeps from the deepest point of the interior up to the top of the wall with no ledge to
lift parts over -- which is the whole reason to shell a bin rather than hollow it.

Two things the construction has to respect:

* **Nothing may be added outside the gridfinity envelope.** A wedge spanning the full
  footprint would otherwise reach past the corner fillets, past the foot chamfers and into
  the V grooves between feet, and the bin would no longer seat on a baseplate or under
  another bin. The wedge is therefore intersected with a corner-filleted prism of the real
  footprint and cut by a negative carrying the imprint of the base feet.
* **The full footprint width is deliberate**, the same reasoning as `shelledDividers`: a
  join is a no-op where material already exists, so running the wedge through the dividers
  and into the side walls leaves no sliver where the cavity's corner fillets curve away.
  The dividers, which run first, split the result into one scoop per cell.

Every compartment row is scooped, not just the front one, matching how hollow bins scoop
each compartment. Rows come from the dividers that were actually built rather than from
`compartmentsByY`, which is clamped to the unit count.
"""

import adsk.core, adsk.fusion

from . import shelledDividers
from ... import (const, baseGenerator, combineUtils, commonUtils, extrudeUtils,
                 filletUtils, shapeUtils)
from .... import fusion360utils as futil

NAME = 'Shelled scoop'

SCOOP_INPUT_ID = 'bin_has_scoop'


def isEnabled(context) -> bool:
    commandInputs = context.commandInputs
    if context.binBodyInput is None or not shelledDividers.isShelled(commandInputs):
        return False
    # Deliberately the raw checkbox: binBodyInput.hasScoop is already forced False for
    # this bin type by entry.py:956, so reading it would always skip.
    scoop = commandInputs.itemById(SCOOP_INPUT_ID) if commandInputs else None
    return bool(scoop) and bool(scoop.value)


def wallTopZ(binInput):
    """Top of the vertical cavity wall, where the lip starts.

    Computed, not measured: it is the same expression the generator extrudes the body to
    at binBodyGenerator.py:36. The body's own bounding box would give the top of the lip
    instead, which is 4.4 mm higher and not where the cavity ends.
    """
    return ((float(binInput.binHeight) - 1) * float(binInput.heightUnit)
            + max(0.0, float(binInput.heightUnit) - float(const.BIN_BASE_HEIGHT)))


def scoopRows(binInput):
    """(frontY, depth) for each compartment row, front to back.

    The front wall of row 0 is the bin's own; for every row behind it, it is the back face
    of the divider in front. Positions come from `shelledDividers.wallPositions()` so the
    ramps land exactly on the walls that feature just built -- including its clamping, so
    asking for more rows than the bin has units yields as many ramps as there are rows.
    """
    shell = float(binInput.wallThickness) - float(binInput.xyClearance)
    thickness = float(binInput.wallThickness)
    footprintLength = (float(binInput.baseLength) * float(binInput.binLength)
                       - float(binInput.xyClearance) * 2.0)
    positions = [float(position) for position in shelledDividers.wallPositions(
        binInput.binLength, binInput.compartmentsByY,
        binInput.baseLength, binInput.xyClearance, binInput.wallThickness)]

    fronts = [shell] + [position + thickness for position in positions]
    backs = positions + [footprintLength - shell]
    return [(front, back - front) for front, back in zip(fronts, backs)
            if back - front > const.DEFAULT_FILTER_TOLERANCE]


def _combine(component: adsk.fusion.Component, target, tools, operation):
    """A combine that keeps its tool bodies.

    `combineUtils` always consumes them, and the clip tools have to serve one ramp per
    compartment row. Rebuilding them per row would work but costs a base pattern each time.
    """
    combines = component.features.combineFeatures
    combineInput = combines.createInput(target, commonUtils.objectCollectionFromList(tools))
    combineInput.operation = operation
    combineInput.isKeepToolBodies = True
    return combines.add(combineInput)


def _wedge(component: adsk.fusion.Component, frontY, floorZ, radius, width):
    """The ramp for one row: a box of the corner, less the arc rolled through it."""
    box = shapeUtils.simpleBox(
        component.xYConstructionPlane,
        floorZ,
        width,
        radius,
        radius,
        adsk.core.Point3D.create(0, frontY, floorZ),
        component,
    )
    box.name = 'Scoop wedge'
    # simpleCylinder takes its plane as an argument, so the YZ plane gives an axis along X
    # with no new geometry code.
    arc = shapeUtils.simpleCylinder(
        component.yZConstructionPlane,
        0,
        width,
        radius,
        adsk.core.Point3D.create(0, frontY + radius, floorZ + radius),
        component,
    )
    arc.name = 'Scoop arc'
    combineUtils.cutBody(box, commonUtils.objectCollectionFromList([arc]), component)
    return box


def _footprintPrism(component: adsk.fusion.Component, binInput, bottom, top):
    """The bin's outer footprint over its whole height, corner fillets included.

    Same construction as binBodyGenerator.py:38-57. Intersecting the wedge with this keeps
    it inside the footprint -- and brings the feet below down to the xyClearance size,
    which `createBaseBodyPattern` does not do on its own (upstream trims them afterwards
    with `cutBaseClearance`).
    """
    width = (float(binInput.baseWidth) * float(binInput.binWidth)
             - float(binInput.xyClearance) * 2.0)
    length = (float(binInput.baseLength) * float(binInput.binLength)
              - float(binInput.xyClearance) * 2.0)
    height = top - bottom
    extrude = extrudeUtils.createBoxAtPoint(
        width, length, height, component, adsk.core.Point3D.create(0, 0, bottom))
    extrude.name = 'Scoop clip prism extrude'
    filletUtils.filletEdgesByLength(
        extrude.faces,
        float(binInput.binCornerFilletRadius),
        height,
        component,
    ).name = 'Scoop clip prism fillets'
    body = extrude.bodies.item(0)
    body.name = 'Scoop clip prism'
    return body


def _baseImprint(component: adsk.fusion.Component, binInput, baseInput, bottom):
    """A negative carrying the imprint of the base feet: everything below the body that is
    *not* foot -- the chamfered flanks and the V grooves where two feet meet.

    Cutting the wedge with this is what stops the ramp filling the space a baseplate or the
    lip of the bin below has to occupy. The feet are rebuilt with the generator's own
    `createBaseBodyPattern` from the same `baseGeneratorInput` the bin was made with, so
    the profile matches exactly; screw and magnet cutouts are already forced off for this
    bin type at entry.py:926-928.
    """
    width = (float(binInput.baseWidth) * float(binInput.binWidth)
             - float(binInput.xyClearance) * 2.0)
    length = (float(binInput.baseLength) * float(binInput.binLength)
              - float(binInput.xyClearance) * 2.0)
    extrude = extrudeUtils.createBoxAtPoint(
        width, length, -bottom, component, adsk.core.Point3D.create(0, 0, bottom))
    extrude.name = 'Scoop base imprint extrude'
    negative = extrude.bodies.item(0)
    negative.name = 'Scoop base imprint'

    feet = baseGenerator.createBaseBodyPattern(
        baseInput, binInput.binWidth, binInput.binLength, component)
    combineUtils.cutBody(negative, commonUtils.objectCollectionFromList(feet), component)
    return negative


def applyToBin(context):
    binInput = context.binBodyInput
    component = context.targetComponent
    if binInput is None or component is None:
        return

    target = shelledDividers.targetBody(component)
    if target is None:
        futil.log('%s: no solid body, skipping' % NAME)
        return

    shell = float(binInput.wallThickness) - float(binInput.xyClearance)
    footprintWidth = (float(binInput.baseWidth) * float(binInput.binWidth)
                      - float(binInput.xyClearance) * 2.0)

    bottom = target.boundingBox.minPoint.z
    top = target.boundingBox.maxPoint.z
    # The interior floor. With a base that is the bottom of the hollowed foot; with
    # 'Generate base' off the body starts at z = 0 and it collapses to the shell thickness.
    floorZ = bottom + shell
    cavityHeight = wallTopZ(binInput) - floorZ

    # Upstream's rule (binBodyCutoutGenerator.py:60): the requested radius, capped by the
    # depth there is to spend it on.
    maxRadius = min(float(binInput.scoopMaxRadius), cavityHeight)
    if maxRadius <= const.DEFAULT_FILTER_TOLERANCE:
        futil.log('%s: no room for a scoop, skipping' % NAME)
        return

    wedges = []
    for frontY, depth in scoopRows(binInput):
        # Capped again at the row's own depth so the ramp cannot overrun its back wall.
        radius = min(maxRadius, depth)
        if radius <= const.DEFAULT_FILTER_TOLERANCE:
            continue
        wedges.append(_wedge(component, frontY, floorZ, radius, footprintWidth))

    if not wedges:
        futil.log('%s: nothing to scoop, skipping' % NAME)
        return

    # Clip every ramp to the envelope, one at a time. The ramps of separate rows do not
    # touch, and a Join of disjoint solids leaves them as separate bodies rather than
    # merging them -- clipping them as one body silently dropped every row but the first.
    prism = _footprintPrism(component, binInput, bottom, top)
    imprint = None
    if bottom < -const.DEFAULT_FILTER_TOLERANCE and context.baseGeneratorInput is not None:
        imprint = _baseImprint(component, binInput, context.baseGeneratorInput, bottom)

    for wedge in wedges:
        _combine(component, wedge, [prism],
                 adsk.fusion.FeatureOperations.IntersectFeatureOperation)
        if imprint is not None:
            _combine(component, wedge, [imprint],
                     adsk.fusion.FeatureOperations.CutFeatureOperation)

    # Every ramp touches the bin, so this join does merge.
    combineUtils.joinBodies(
        target, commonUtils.objectCollectionFromList(wedges), component)

    removeFeatures = component.features.removeFeatures
    removeFeatures.add(prism)
    if imprint is not None:
        removeFeatures.add(imprint)
    futil.log('%s: %d scoop ramp(s) at radius up to %.4f, floor %.4f'
              % (NAME, len(wedges), maxRadius, floorZ))
