"""Clipping a body added below z = 0 back inside the gridfinity envelope.

Anything a customization joins on below the bin body has to respect the base: the corner
fillets, the chamfered flanks of each foot, and the V grooves where two feet meet. Put
material in any of those and the bin no longer seats on a baseplate or under another bin,
and a bounding box will not tell you, because all of it is *inside* the box.

Two negatives do the work, and both are needed:

* `footprintPrism` -- the outer footprint over the bin's whole height, corner fillets
  included. Intersecting with it also brings the feet down to the xyClearance size, which
  `createBaseBodyPattern` does not do on its own (upstream trims them afterwards with
  `cutBaseClearance`).
* `baseImprint` -- everything below the body that is *not* foot, so cutting with it leaves
  exactly the flanks and grooves untouched. The feet are rebuilt with the generator's own
  `createBaseBodyPattern` from the same `baseGeneratorInput` the bin was made with, so the
  profile matches exactly.

Shared by `shelledScoop`, whose ramps reach down to the tub floor, and `shelledDividers`,
whose walls do the same.
"""

import adsk.core, adsk.fusion

from .. import baseGenerator, combineUtils, commonUtils, extrudeUtils, filletUtils


def _footprint(binInput):
    return ((float(binInput.baseWidth) * float(binInput.binWidth)
             - float(binInput.xyClearance) * 2.0),
            (float(binInput.baseLength) * float(binInput.binLength)
             - float(binInput.xyClearance) * 2.0))


def footprintPrism(component: adsk.fusion.Component, binInput, bottom, top):
    """The bin's outer footprint over its whole height, corner fillets included.

    Same construction as binBodyGenerator.py:38-57.
    """
    width, length = _footprint(binInput)
    height = top - bottom
    extrude = extrudeUtils.createBoxAtPoint(
        width, length, height, component, adsk.core.Point3D.create(0, 0, bottom))
    extrude.name = 'Envelope prism extrude'
    filletUtils.filletEdgesByLength(
        extrude.faces,
        float(binInput.binCornerFilletRadius),
        height,
        component,
    ).name = 'Envelope prism fillets'
    body = extrude.bodies.item(0)
    body.name = 'Envelope prism'
    return body


def baseImprint(component: adsk.fusion.Component, binInput, baseInput, bottom):
    """A negative carrying the imprint of the base feet: everything below the body that is
    *not* foot -- the chamfered flanks and the V grooves where two feet meet."""
    width, length = _footprint(binInput)
    extrude = extrudeUtils.createBoxAtPoint(
        width, length, -bottom, component, adsk.core.Point3D.create(0, 0, bottom))
    extrude.name = 'Envelope base imprint extrude'
    negative = extrude.bodies.item(0)
    negative.name = 'Envelope base imprint'

    feet = baseGenerator.createBaseBodyPattern(
        baseInput, binInput.binWidth, binInput.binLength, component)
    combineUtils.cutBody(negative, commonUtils.objectCollectionFromList(feet), component)
    return negative


def combineKeepingTools(component: adsk.fusion.Component, target, tools, operation):
    """A combine that keeps its tool bodies.

    `combineUtils` always consumes them, and one clip tool has to serve every body being
    clipped. Rebuilding it per body would work but costs a base pattern each time.
    """
    combines = component.features.combineFeatures
    combineInput = combines.createInput(target, commonUtils.objectCollectionFromList(tools))
    combineInput.operation = operation
    combineInput.isKeepToolBodies = True
    return combines.add(combineInput)


def clip(component: adsk.fusion.Component, bodies, prism, imprint):
    """Trim each body back inside the envelope, one at a time.

    One at a time deliberately: the bodies of separate compartments do not touch, and a
    Fusion Join of *disjoint* solids leaves them separate rather than merging, so clipping
    them as one body silently drops all but the first.
    """
    for body in bodies:
        if prism is not None:
            combineKeepingTools(component, body, [prism],
                                adsk.fusion.FeatureOperations.IntersectFeatureOperation)
        if imprint is not None:
            combineKeepingTools(component, body, [imprint],
                                adsk.fusion.FeatureOperations.CutFeatureOperation)


def discard(component: adsk.fusion.Component, *bodies):
    removeFeatures = component.features.removeFeatures
    for body in bodies:
        if body is not None:
            removeFeatures.add(body)
