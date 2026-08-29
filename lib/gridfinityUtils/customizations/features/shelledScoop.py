"""Scoop for shelled bins.

The scoop is Hollow-only upstream, behind two independent gates:

    entry.py:954   binBodyInput.isSolid  = isSolid or isShelled
    entry.py:956   binBodyInput.hasScoop = has_scoop.value and isHollow

Line 956 ands the checkbox with `isHollow`, so ticking "Add scoop" on a shelled bin
resolves to False with nothing to say it was ignored. And even without that, line 954
marks shelled bins solid, so `binBodyGenerator.py:112`'s `if not input.isSolid:` skips
the whole compartment block -- which is where the scoop is built.

Same root cause as the missing compartments, so the same treatment: read the raw
checkbox rather than the suppressed `binBodyInput.hasScoop`, and fillet the bottom
front edge of the cavity afterwards.

The radius rule is upstream's (binBodyCutoutGenerator.py:60): the requested radius,
capped by how much depth there is to spend it on. It is capped again at half the cavity
depth in Y, because a fillet larger than the surface it is rolling along fails outright
rather than degrading.

With dividers present the front wall arrives already split into one face per cell, so
filleting each one gives a scoop per cell -- matching how hollow bins scoop each
compartment separately. That is why this runs after shelledDividers.
"""

import adsk.core, adsk.fusion

from . import shelledDividers
from ... import const, faceUtils, filletUtils
from .... import fusion360utils as futil

NAME = 'Shelled scoop'

SCOOP_INPUT_ID = 'bin_has_scoop'

# How close a face has to sit to the front wall to count as it.
POSITION_TOLERANCE = 0.01


def isEnabled(context) -> bool:
    commandInputs = context.commandInputs
    if context.binBodyInput is None or not shelledDividers.isShelled(commandInputs):
        return False
    # Deliberately the raw checkbox: binBodyInput.hasScoop is already forced False for
    # this bin type by entry.py:956, so reading it would always skip.
    scoop = commandInputs.itemById(SCOOP_INPUT_ID) if commandInputs else None
    return bool(scoop) and bool(scoop.value)


def _frontWallFaces(body: adsk.fusion.BRepBody, frontY: float, floor: float, top: float):
    """Interior faces of the front wall -- one per cell once dividers have split it.

    The front is the low-Y side, matching getInnerCutoutScoopFace() upstream, which takes
    the cutout face with the smallest Y.

    Selected by position, not by normal direction. `Plane.normal` is the surface's own
    normal and says nothing about which way the face is oriented within the solid -- that
    needs isParamReversed. Measured on a shelled bin, the front interior wall reports
    n.y = -1 and the back wall n.y = +1, the opposite of what "points into the cavity"
    would suggest. Position is unambiguous: the wall is the only face sitting at
    y = shell thickness.
    """
    found = []
    for face in body.faces:
        surface = face.geometry
        if not isinstance(surface, adsk.core.Plane):
            continue
        if abs(abs(surface.normal.y) - 1.0) > 1e-6:
            continue
        box = face.boundingBox
        if abs(box.minPoint.y - frontY) > POSITION_TOLERANCE:
            continue
        if box.maxPoint.z <= floor or box.minPoint.z >= top:
            continue
        found.append(face)
    return found


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
    footprintWidth = float(binInput.baseWidth) * float(binInput.binWidth) - float(binInput.xyClearance) * 2.0
    footprintLength = float(binInput.baseLength) * float(binInput.binLength) - float(binInput.xyClearance) * 2.0

    top = target.boundingBox.maxPoint.z
    floor = shelledDividers.cavityFloor(
        target, shell, footprintWidth - shell, shell, footprintLength - shell, top)
    if floor is None:
        futil.log('%s: could not locate the cavity floor, skipping' % NAME)
        return

    faces = _frontWallFaces(target, shell, floor, top)
    if not faces:
        futil.log('%s: no front wall face found, skipping' % NAME)
        return

    edges = []
    for face in faces:
        try:
            edges.append(faceUtils.getBottomHorizontalEdge(face.edges))
        except Exception as err:
            futil.log('%s: no bottom edge on one front face (%s)' % (NAME, err))
    if not edges:
        futil.log('%s: no bottom edges to fillet, skipping' % NAME)
        return

    # Bound by the wall the fillet actually has to roll along, not by the cavity: the
    # wall stops at the lip, well below the rim. A radius equal to the face height is
    # degenerate and fails outright, so leave a little margin.
    cavityDepth = footprintLength - shell * 2.0
    wallTop = min(face.boundingBox.maxPoint.z for face in faces)
    wallBottom = max(face.boundingBox.minPoint.z for face in faces)
    wallHeight = wallTop - wallBottom
    radius = min(float(binInput.scoopMaxRadius), wallHeight * 0.95, cavityDepth / 2.0)
    if radius <= const.DEFAULT_FILTER_TOLERANCE:
        futil.log('%s: no room for a scoop, skipping' % NAME)
        return

    filletUtils.createFillet(edges, radius, False, component).name = 'Shelled scoop'
    futil.log('%s: scooped %d front edge(s) at radius %.4f' % (NAME, len(edges), radius))
