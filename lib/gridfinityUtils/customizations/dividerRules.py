"""How tall a compartment divider is allowed to be, in one place.

A divider that reaches the rim crosses the lip opening, which is where the base feet of
the bin above have to seat. It only fits if it sits in the groove *between* two of those
feet -- and that groove is at its narrowest exactly at our rim:

* two neighbouring feet meet at a knife edge at the top of the base, `2 * xyClearance`
  apart, because `createBaseBodyPattern` (baseGenerator.py:377) replicates a full-size
  foot at exactly `baseWidth` spacing and `cutBaseClearance` only trims the outer
  perimeter;
* our rim sits `BIN_LIP_TOP_RECESS_HEIGHT` below the underside of the bin above
  (`BIN_LIP_EXTRA_HEIGHT + BIN_LIP_TOP_RECESS_HEIGHT == BIN_BASE_HEIGHT`), and the foot's
  top section is chamfered at 45 degrees, so the groove has opened by that much per side.

    groove at the rim = 2 * (xyClearance + BIN_LIP_TOP_RECESS_HEIGHT)  =  1.7 mm

A 1.2 mm wall centred on a unit boundary clears it by 0.25 mm per side. A wall anywhere
else fouls, which is why height has to depend on *position*: a divider separating a whole
number of gridfinity units may reach the rim, and one that does not stops at the top of
the label plate.

That cap is not an invented number either -- it is the clearance shelf upstream already
shaves off the whole inner top whenever there is more than one compartment
(binBodyGenerator.py:164), and the height the label tab is built to
(binBodyTabGenerator.py:41). So on the hollow path "capped" means *leave it alone*.

**Equal-fraction dividers are never exactly on a boundary.** Upstream cuts the cavity
into equal fractions from `minX = wallThickness`, and asking a wall centred there to also
be centred on `k * baseWidth - xyClearance` has no solution for positive `minX`. What is
left over is

    hollow:   xyClearance + wallThickness / 2 - (m / units) * (2 * xyClearance + wallThickness)
    shelled:  wallThickness * (1 / 2 - k / count)

for the divider that passes `m` whole units -- 0.28 mm on a 3u bin at stock dimensions,
zero on a 2u one, and under a wall thickness in the worst case. That is treated as
alignment anyway: it is the same order as the 0.25 mm of slack the groove already
carries, and closing it would mean either moving upstream's compartments -- an edit to
`binBodyGenerator.py`, which this fork exists to avoid -- or making the compartments
unequal, which is worse than the problem.
"""

from .. import const

# Divider height modes, as shown in the dialog dropdown.
MODE_AUTO = 'Automatic'
MODE_CAP = 'Cap at label plate'
MODE_FULL = 'Extend to bin top'

MODES = [MODE_AUTO, MODE_CAP, MODE_FULL]


def bodyTopZ(binInput) -> float:
    """Top of the bin body, where the lip starts.

    Computed rather than measured: the same expression the generator extrudes the body
    to at binBodyGenerator.py:36. A bounding box would give the top of the *lip*, which
    is BIN_LIP_EXTRA_HEIGHT higher and not where the cavity ends.
    """
    return ((float(binInput.binHeight) - 1) * float(binInput.heightUnit)
            + max(0.0, float(binInput.heightUnit) - float(const.BIN_BASE_HEIGHT)))


def cappedTopZ(binInput) -> float:
    """Top of the label plate: as high as a divider can go and still stack."""
    return bodyTopZ(binInput) - float(const.BIN_TAB_TOP_CLEARANCE)


def isGridAligned(cellsBefore, count, units) -> bool:
    """True when the compartments in front of a divider add up to a whole number of
    gridfinity units, so the divider lands on a unit boundary.

    `cellsBefore` is 1-based: the divider after the first compartment passes 1. With
    equal-fraction cells that boundary sits at `cellsBefore * units / count` units, hence
    the modulo. On a 1u axis only `cellsBefore == count` would satisfy it and the last
    compartment has no divider behind it, so nothing on a 1u axis is ever aligned.
    """
    count = int(count)
    if count <= 0:
        return False
    return (int(cellsBefore) * int(units)) % count == 0


def isFullHeight(mode, aligned) -> bool:
    if mode == MODE_FULL:
        return True
    if mode == MODE_CAP:
        return False
    return bool(aligned)


def maxStackingThickness(xyClearance) -> float:
    """Widest divider the groove between the feet above can swallow at the rim."""
    return 2.0 * (float(xyClearance) + float(const.BIN_LIP_TOP_RECESS_HEIGHT))
