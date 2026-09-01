"""Fill the V grooves between the gridfinity units on the underside of a bin.

The grooves are emergent, not authored -- there is no code that draws them and no flag
that switches them off. `createBaseBodyPattern` (baseGenerator.py:377-398) replicates a
fully chamfered foot at exactly `baseWidth` spacing while each foot's top rectangle is
the *full* unit size (baseGenerator.py:116-128), so two neighbours meet at a knife edge
at the top of the base and each one's 2.4 mm chamfer then slopes away from it. What is
left between them is a V groove the full 5 mm depth of the base. `cutBaseClearance`
(baseGenerator.py:400) only trims the outer perimeter, so the interior grooves carry no
clearance at all.

Nothing to disable, then: the fill has to be added. It is built as the bin's own base
profile scaled to the whole footprint, minus the feet that are already there, so what
gets joined is exactly the groove volume.

Two details the construction depends on:

* **The filler is built pre-trimmed** -- at `baseWidth * binWidth - 2 * xyClearance` with
  the corner fillet `cutBaseClearance` uses (baseGenerator.py:430), origin at the body
  corner. Its outer surface therefore sits at or inside the real perimeter everywhere, so
  it cannot add material outside the gridfinity envelope, and a join is a no-op where
  material already exists. Building it full size and clipping afterwards would work too,
  but this needs no clip.
* **The feet subtracted from it are rebuilt with screw and magnet cutouts off.** Those
  cutouts are voids *inside* the feet and the filler spans them, so subtracting the real
  hole-bearing feet would leave filler sitting in every hole and the join would plug them.

**This is a departure from the gridfinity base spec.** The bin still seats on a
baseplate -- the outer profile is untouched -- but with the grooves gone it can no longer
sit over the full-height dividers of the bin below. That is the trade the dialog's
tooltip and the stacking warning describe.
"""

import copy

import adsk.core, adsk.fusion

from .. import inputs as customInputs
from .. import parametrization
from ... import const, baseGenerator, combineUtils, commonUtils
from .... import fusion360utils as futil

NAME = 'Solid base'


def isEnabled(context) -> bool:
    if context.binBodyInput is None or context.baseGeneratorInput is None:
        return False
    return customInputs.isSolidBaseEnabled(context.commandInputs)


def targetBody(component: adsk.fusion.Component):
    solids = [body for body in component.bRepBodies if body.isSolid]
    return max(solids, key=lambda body: body.volume) if solids else None


def _fillerInput(baseInput, binInput):
    """The bin's base profile, scaled to the whole footprint and already clearance-sized."""
    filler = copy.copy(baseInput)
    filler.originPoint = adsk.core.Point3D.create(0, 0, 0)
    filler.baseWidth = (float(binInput.baseWidth) * float(binInput.binWidth)
                        - float(binInput.xyClearance) * 2.0)
    filler.baseLength = (float(binInput.baseLength) * float(binInput.binLength)
                         - float(binInput.xyClearance) * 2.0)
    filler.cornerFilletRadius = (float(baseInput.cornerFilletRadius)
                                 - float(binInput.xyClearance))
    filler.hasScrewHoles = False
    filler.hasMagnetCutouts = False
    filler.hasMagnetCutoutsTabs = False
    return filler


def _solidFeetInput(baseInput):
    """The real feet, minus their holes -- see the module docstring."""
    feet = copy.copy(baseInput)
    feet.hasScrewHoles = False
    feet.hasMagnetCutouts = False
    feet.hasMagnetCutoutsTabs = False
    return feet


def applyToBin(context):
    binInput = context.binBodyInput
    baseInput = context.baseGeneratorInput
    component = context.targetComponent
    if binInput is None or baseInput is None or component is None:
        return

    if int(binInput.binWidth) <= 1 and int(binInput.binLength) <= 1:
        futil.log('%s: a 1x1 bin has a single foot and no grooves, skipping' % NAME)
        return

    target = targetBody(component)
    if target is None:
        futil.log('%s: no solid body, skipping' % NAME)
        return

    # With 'Generate base' off the body starts at z = 0 and there is no base to fill.
    if target.boundingBox.minPoint.z > -const.DEFAULT_FILTER_TOLERANCE:
        futil.log('%s: no base on this bin, skipping' % NAME)
        return

    # Tracing off for the whole block: this reuses baseWidth / baseLength /
    # cornerFilletRadius with different values from the ones the bin itself claimed, and
    # the tracer keys parameters by field name. See parametrization.suspended().
    with parametrization.suspended():
        filler = baseGenerator.createSingleGridfinityBaseBody(
            _fillerInput(baseInput, binInput), component)
        filler.name = 'Base groove filler'

        feet = baseGenerator.createBaseBodyPattern(
            _solidFeetInput(baseInput), binInput.binWidth, binInput.binLength, component)
        cutFeature = combineUtils.cutBody(
            filler, commonUtils.objectCollectionFromList(feet), component)

    # One groove per unit boundary, and they only meet where two boundaries cross, so the
    # remainder is usually several disjoint bodies. Each one touches the feet either side
    # and the body above, so joining them all against the bin does merge.
    grooves = [body for body in cutFeature.bodies if body.isSolid]
    if not grooves:
        futil.log('%s: nothing left to fill, skipping' % NAME)
        return

    combineUtils.joinBodies(
        target, commonUtils.objectCollectionFromList(grooves), component)
    futil.log('%s: filled %d groove section(s) on a %dx%d base'
              % (NAME, len(grooves), int(binInput.binWidth), int(binInput.binLength)))
