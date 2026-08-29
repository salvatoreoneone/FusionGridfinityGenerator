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

import adsk.core, adsk.fusion

from .. import inputs as customInputs
from .. import parametrization
from ... import const, shapeUtils, combineUtils, commonUtils
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

    tools = []
    for cornerX, cornerY in corners:
        tool = shapeUtils.simpleCylinder(
            component.xYConstructionPlane,
            bottom,
            height,
            diameter / 2,
            adsk.core.Point3D.create(cornerX, cornerY, bottom),
            component,
        )
        tool.name = 'Corner relief tool'
        tools.append(tool)

    combineUtils.cutBody(target, commonUtils.objectCollectionFromList(tools), component)
    futil.log('%s: cut %d corners on %r' % (NAME, len(tools), target.name))
