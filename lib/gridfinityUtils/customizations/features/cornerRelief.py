"""Vertical relief at each corner of the bin footprint.

Cuts a full-height cylindrical relief centred on each of the four corners of the bin's
outer footprint, so the bin clears the rounded internal corners or corner posts of the
box it has to sit in.

Translated from a hand-built model: a sketch of four circles on the XY plane whose
centres were projected from the corners of the generated body, cut two-sided through
everything.

Two deliberate departures from that model:

* The corner positions are **computed from the input parameters** rather than projected
  from model geometry. The hand model projected from 'Simple box at point sketch',
  which belongs to the *lip* -- so the relief would have silently depended on lip
  geometry and broken outright with the lip switched off. The generator already has
  these numbers (binBodyGenerator.py:33-34), so nothing has to be searched for.
* The depth is computed to span base through lip instead of a fixed 50 mm, so it stays
  a through-cut at any bin height.
"""

import math

import adsk.core, adsk.fusion

from .. import inputs as customInputs
from .. import parametrization
from ... import (const, shapeUtils, combineUtils, commonUtils, filletUtils, faceUtils,
                 geometryUtils)
from .... import fusion360utils as futil

NAME = 'Corner relief'


def isEnabled(context) -> bool:
    return customInputs.isCornerReliefEnabled(context.commandInputs)


def _targetBody(component: adsk.fusion.Component):
    """The bin: the largest solid in the component once everything is merged."""
    solids = [body for body in component.bRepBodies if body.isSolid]
    if not solids:
        return None
    return max(solids, key=lambda body: body.volume)


def applyToBin(context):
    binInput = context.binBodyInput
    component = context.targetComponent
    if binInput is None or component is None:
        return

    target = _targetBody(component)
    if target is None:
        futil.log('%s: no solid body to cut, skipping' % NAME)
        return

    diameter = parametrization.seedValue(
        'cornerReliefDiameter',
        customInputs.cornerReliefDiameter(context.commandInputs),
        parametrization.UNIT_LENGTH,
    )
    # Not float(): the traced value carries the expression the parameter is named for.
    radius = diameter / 2

    # Same expressions the body generator uses (binBodyGenerator.py:33-36), so they
    # carry the same derivations rather than re-deriving them by hand.
    footprintWidth = binInput.baseWidth * binInput.binWidth - binInput.xyClearance * 2.0
    footprintLength = binInput.baseLength * binInput.binLength - binInput.xyClearance * 2.0
    bodyHeight = ((binInput.binHeight - 1) * binInput.heightUnit
                  + max(0, binInput.heightUnit - const.BIN_BASE_HEIGHT))

    # Span the base below z=0 through the top of the lip. The lip term is included
    # unconditionally: when there is no lip it is simply headroom on a cut, which
    # costs nothing and keeps the expression free of a conditional.
    bottom = -const.BIN_BASE_HEIGHT
    height = const.BIN_BASE_HEIGHT + bodyHeight + const.BIN_LIP_EXTRA_HEIGHT

    corners = [
        (0, 0),
        (footprintWidth, 0),
        (0, footprintLength),
        (footprintWidth, footprintLength),
    ]

    # Before the cut, not after: the relief has to have a wall to cut into.
    _reinforce(component, target, corners, radius, binInput.wallThickness,
               binInput.xyClearance, footprintWidth, footprintLength,
               binInput.binCornerFilletRadius, bodyHeight)

    tools = []
    for cornerX, cornerY in corners:
        tool = shapeUtils.simpleCylinder(
            component.xYConstructionPlane,
            bottom,
            height,
            radius,
            adsk.core.Point3D.create(cornerX, cornerY, bottom),
            component,
        )
        tool.name = 'Corner relief tool'
        tools.append(tool)

    combineUtils.cutBody(target, commonUtils.objectCollectionFromList(tools), component)
    futil.log('%s: cut %d corners on %r' % (NAME, len(tools), target.name))


def _reinforce(component: adsk.fusion.Component, target: adsk.fusion.BRepBody, corners,
               reliefRadius, wallThickness, xyClearance, footprintWidth, footprintLength,
               cornerFilletRadius, bodyHeight):
    """Fill each corner with a slug of material before the relief is cut.

    The relief is centred on the *sharp* footprint corner, which sits `sqrt(2) * R - R`
    outside the filleted outer surface -- 1.553 mm at the stock 3.75 mm corner radius --
    so a relief of radius r eats `r - 0.414 * R` into the corner. All the corner has to
    give is one wall thickness, and less than that on a shelled bin, where the shell is
    `wallThickness - xyClearance` (commandCreateBin/entry.py:1019). Past that the relief
    opens straight into the cavity: a 5 mm relief cuts 0.947 mm into a 0.55 mm shelled
    wall and leaves a 2 mm wide slot running the full height of the bin.

    Filling each corner out to `relief radius + wallThickness` first, clipped to the bin's
    own outline, gives the relief a full wall thickness to cut into at any diameter.

    This replaces lining the cut faces afterwards with a thicken. A thicken can only
    follow the faces that survived the cut, and where the relief has already breached the
    cavity there is no face over the breach to follow -- so it restored a thinned corner
    but could not close an open one, which is the case that needs it. Adding material
    first needs no faces to be found at all.
    """
    cornerOffset = (math.sqrt(2) - 1) * cornerFilletRadius
    radius = reliefRadius + wallThickness

    # A relief that does not reach the outer surface cuts nothing, and a slug clipped to
    # the outline would come out empty, which a combine will not accept.
    if radius <= cornerOffset + const.DEFAULT_FILTER_TOLERANCE:
        futil.log('%s: relief does not reach the bin, nothing to reinforce' % NAME)
        return

    # The body says how far the slug runs: into the base only when a base was generated,
    # and no higher than the material itself. The bounding box is what answers both, so
    # the slug stays inside the bin whatever the dialog left switched off.
    box = target.boundingBox
    bodyTop = min(bodyHeight, box.maxPoint.z)
    if bodyTop <= const.DEFAULT_FILTER_TOLERANCE:
        futil.log('%s: nothing above the base to reinforce' % NAME)
        return
    hasBase = box.minPoint.z < -const.DEFAULT_FILTER_TOLERANCE
    bottom = -const.BIN_BASE_TOP_SECTION_HEIGH if hasBase else 0.0

    collarRadius, collarHeight = _collar(radius, wallThickness, xyClearance, cornerOffset,
                                         box.maxPoint.z - bodyTop)

    slugs = []
    for cornerX, cornerY in corners:
        slug = shapeUtils.simpleCylinder(
            component.xYConstructionPlane,
            bottom,
            bodyTop - bottom,
            radius,
            adsk.core.Point3D.create(cornerX, cornerY, bottom),
            component,
        )
        slug.name = 'Corner relief reinforcement'
        if collarHeight > const.DEFAULT_FILTER_TOLERANCE:
            collar = shapeUtils.simpleCylinder(
                component.xYConstructionPlane,
                bodyTop,
                collarHeight,
                collarRadius,
                adsk.core.Point3D.create(cornerX, cornerY, bodyTop),
                component,
            )
            collar.name = 'Corner relief collar'
            combineUtils.joinBodies(
                slug, commonUtils.objectCollectionFromList([collar]), component)
        outline = _outline(component, footprintWidth, footprintLength, cornerFilletRadius,
                           bottom, bodyTop + collarHeight - bottom, hasBase)
        combineUtils.intersectBody(
            slug, commonUtils.objectCollectionFromList([outline]), component)
        slugs.append(slug)

    combineUtils.joinBodies(target, commonUtils.objectCollectionFromList(slugs), component)
    futil.log('%s: reinforced %d corners out to %.4f, collar %.4f x %.4f'
              % (NAME, len(slugs), radius, collarRadius, collarHeight))


def _collar(radius, wallThickness, xyClearance, cornerOffset, lipHeight):
    """How far the slug carries on above the body, and how wide it may be up there.

    The wall does not simply stop at the body: the lip is thinned back to the wall where
    the two meet (`lipBottomChamferExtrude`, binBodyGenerator.py:76-84 -- a box inset by
    one `wallThickness`, chamfered at 45 degrees), so its inner face starts at
    `cornerOffset + wallThickness` from the corner and only reaches full rim thickness
    `radius - cornerOffset - wallThickness` higher up. Over that stretch the relief is
    cutting into the same thin corner it cuts through below, and stopping the slug at the
    body leaves it open again -- a slot from the body top up to where the lip's own
    material has grown past the relief. So the slug carries straight on to where the lip
    can take over, which is where its chamfer has grown out to the slug's own radius.

    The collar cannot be allowed past the **recess wall**, though: above the body the void
    it is filling is the seat the next bin's foot drops into, not the compartment. The
    recess sits at `cornerOffset + BIN_BASE_TOP_SECTION_HEIGH - 2 * xyClearance` from the
    corner (binBodyLipGenerator.py:108-122 cuts it with a base body oversized by
    `xyClearance * 2`), so clamping there keeps the foot's own clearance intact. It bites
    from about a 1.2 mm wall up, where `radius` would otherwise stand in the seat: a
    stacked pair measured 0.002016 cm3 of interference at the four corners with an
    unclamped slug running the full height.
    """
    seatLimit = cornerOffset + const.BIN_BASE_TOP_SECTION_HEIGH - xyClearance * 2
    collarRadius = min(radius, seatLimit)
    collarHeight = max(0.0, min(collarRadius - cornerOffset - wallThickness, lipHeight))
    return collarRadius, collarHeight


def _outline(component: adsk.fusion.Component, footprintWidth, footprintLength,
             cornerFilletRadius, bottom, height, hasBase):
    """The bin's outer envelope over the height a slug spans.

    The footprint, filleted the way the body itself is (binBodyGenerator.py:52-57), so a
    slug clipped to it cannot spill outside the bin the way a bare cylinder would.

    Below z=0 the base tapers away from the footprint, so the outline is chamfered by the
    base's own top section height, at the 45 degrees baseGenerator.py:151-160 chamfers it
    with. That is the tighter of the two profiles at every depth -- the real base holds
    the full footprint for the first `xyClearance` of it, because its feet are trimmed to
    the footprint by a vertical cut (baseGenerator.py:400-450) -- so the outline stays
    inside the base, which is the side to err on.
    """
    body = shapeUtils.simpleBox(
        component.xYConstructionPlane,
        bottom,
        footprintWidth,
        footprintLength,
        height,
        adsk.core.Point3D.create(0, 0, bottom),
        component,
    )
    body.name = 'Corner relief outline'

    # Picked out as the vertical edges rather than by length: the outline's height comes
    # from the body, so it could coincide with the footprint's own dimensions.
    filletUtils.createFillet(
        [edge for edge in body.edges if geometryUtils.isCollinearToZ(edge)],
        cornerFilletRadius,
        True,
        component,
    )

    if hasBase:
        filletUtils.createChamfer(
            commonUtils.objectCollectionFromList(list(faceUtils.getBottomFace(body).edges)),
            const.BIN_BASE_TOP_SECTION_HEIGH,
            component,
        )

    return body
