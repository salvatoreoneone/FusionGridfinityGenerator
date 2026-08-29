"""Translate the Python-coded parametrisation of the generators into Fusion parameters.

The plugin computes every dimension in Python and passes the *result* to
ValueInput.createByReal(), so the design ends up fully dimensioned but with baked
numbers: `d21` reads `7.75 mm` rather than `screwHolesOffset - xyClearance`.

This module makes those derivations real Fusion expressions, without editing a single
generator call site. While a generation runs it:

  1. replaces the numeric constants in `const` with symbolic equivalents,
  2. wraps the generator-input property setters so dialog values become symbolic,
  3. intercepts ValueInput.createByReal() and, whenever it receives a symbolic value,
     emits createByString(<expression>) instead.

The untouched arithmetic of the plugin then produces the expressions. Nothing here
transcribes a formula by hand, so when upstream changes one, the translation follows
automatically -- which is the point.

Everything is restored in `uninstall()`, including on failure.
"""

import sys

import adsk.core, adsk.fusion

from .symbolic import Sym, isSym
from .. import const
from ..baseGeneratorInput import BaseGeneratorInput
from ..binBodyGeneratorInput import BinBodyGeneratorInput, BinBodyCompartmentDefinition
from ..baseplateGeneratorInput import BaseplateGeneratorInput
from ... import fusion360utils as futil

UNIT_LENGTH = 'mm'
UNIT_ANGLE = 'deg'
UNIT_SCALAR = ''

# Constants that must never become parameters.
#   DEFAULT_FILTER_TOLERANCE is a comparison epsilon, not a dimension.
#   The angle constants are excluded because the generators pass them through
#   math.radians(), which returns a plain float and so breaks the symbolic chain --
#   an angle parameter would be created but would drive nothing. Better absent than
#   misleading. Supporting angles means teaching the tracer about math.radians().
CONST_EXCLUDED = frozenset([
    'DEFAULT_FILTER_TOLERANCE',
    'BIN_TAB_OVERHANG_ANGLE',
    'BIN_TAB_LABEL_ANGLE',
])

# Constants measured in degrees rather than millimetres.
CONST_ANGLES = frozenset(['BIN_TAB_OVERHANG_ANGLE', 'BIN_TAB_LABEL_ANGLE'])

# Constants that const.py itself derives from other constants. Re-evaluated after
# seeding so the derivation survives instead of being flattened.
#   const.py:9   BIN_BASE_HEIGHT        = TOP + MID + BOTTOM
#   const.py:13  BIN_LIP_WALL_THICKNESS = TOP - BIN_XY_CLEARANCE
CONST_DERIVED = {
    'BIN_BASE_HEIGHT': lambda c: (
        c.BIN_BASE_TOP_SECTION_HEIGH + c.BIN_BASE_MID_SECTION_HEIGH + c.BIN_BASE_BOTTOM_SECTION_HEIGH
    ),
    'BIN_LIP_WALL_THICKNESS': lambda c: c.BIN_BASE_TOP_SECTION_HEIGH - c.BIN_XY_CLEARANCE,
}

# Readable names for constants whose mechanical camelCase is awkward
# (upstream spells the base-section constants "HEIGH").
CONST_NAME_OVERRIDES = {
    'BIN_BASE_TOP_SECTION_HEIGH': 'binBaseTopSectionHeight',
    'BIN_BASE_MID_SECTION_HEIGH': 'binBaseMidSectionHeight',
    'BIN_BASE_BOTTOM_SECTION_HEIGH': 'binBaseBottomSectionHeight',
}

# Generator-input fields that are counts or multipliers, not lengths. Everything else
# on the patched classes is treated as a length.
FIELDS_SCALAR = frozenset([
    'binWidth', 'binLength', 'binHeight',
    'baseplateWidth', 'baseplateLength',
    'compartmentsByX', 'compartmentsByY',
    'tabLength', 'tabPosition',
    'positionX', 'positionY', 'width', 'length',
])
# Excluded for the same reason as the angle constants above: math.radians() flattens
# them, so the parameter would never drive anything.
FIELDS_ANGLE = frozenset(['tabOverhangAngle'])
FIELDS_EXCLUDED = frozenset(['tabOverhangAngle'])

# Only the classes fed directly from the command dialog are patched. Intermediate
# inputs (lip, tab, cutout) receive values that are already symbolic and must pass
# through untouched -- re-wrapping them would flatten the derivation to a leaf.
PATCHED_INPUT_CLASSES = (
    BaseGeneratorInput,
    BinBodyGeneratorInput,
    BinBodyCompartmentDefinition,
    BaseplateGeneratorInput,
)


def constantToParameterName(constName: str) -> str:
    if constName in CONST_NAME_OVERRIDES:
        return CONST_NAME_OVERRIDES[constName]
    words = [word for word in constName.lower().split('_') if word]
    return words[0] + ''.join(word.capitalize() for word in words[1:])


def unitFor(name: str, isConstant: bool) -> str:
    if isConstant:
        return UNIT_ANGLE if name in CONST_ANGLES else UNIT_LENGTH
    if name in FIELDS_ANGLE:
        return UNIT_ANGLE
    if name in FIELDS_SCALAR:
        return UNIT_SCALAR
    return UNIT_LENGTH


class _Session():
    """State for one generation run."""

    def __init__(self, design: adsk.fusion.Design):
        self.design = design
        self.originalConstants = {}
        self.originalSetters = {}
        self.originalCreateByReal = None
        self.originalCreateRectangle = []
        self.names = {}
        self.emitted = 0
        self.baked = 0

    def ensureParameter(self, name: str, value: float, unit: str) -> str:
        """Create (or reuse) a user parameter and return the name actually used.

        A second generation in the same document must not silently retune the geometry
        of the first, so a clashing name holding a different value gets a suffix.

        The cache is keyed by name *and* value. Distinct quantities really do collide:
        const BIN_CORNER_FILLET_RADIUS and the binCornerFilletRadius input field both
        want this name while holding different values (4 mm vs 3.75 mm), and caching on
        the name alone silently hands the second one the first one's parameter.
        """
        key = (name, round(float(value), 9))
        if key in self.names:
            return self.names[key]

        userParameters = self.design.userParameters
        candidate = name
        index = 1
        while True:
            existing = userParameters.itemByName(candidate)
            if existing is None:
                break
            if abs(existing.value - float(value)) < 1e-9:
                self.names[key] = candidate
                return candidate
            index += 1
            candidate = '%s%d' % (name, index)

        userParameters.add(
            candidate,
            adsk.core.ValueInput.createByReal(float(value)),
            unit,
            'Gridfinity generator',
        )
        self.names[key] = candidate
        return candidate

    def seed(self, name: str, value, unit: str, isLength: bool) -> Sym:
        return Sym(self.ensureParameter(name, value, unit), value, isLength=isLength)


_session = None


def isActive() -> bool:
    return _session is not None


def install(design: adsk.fusion.Design):
    """Begin translating.

    A still-open session means the previous generation raised before its hook could
    close it (both generator functions swallow exceptions into executeFailedMessage).
    Tear it down first rather than leaving patched constants and a patched ValueInput
    in place for the rest of the Fusion session.
    """
    global _session
    if _session is not None:
        futil.log('Parametrisation: discarding session left open by a failed generation')
        _restore(_session)
        _session = None
    session = _Session(design)
    try:
        _installConstants(session)
        _installInputSetters(session)
        _installSketchAdapters(session)
        _installValueInput(session)
    except Exception:
        _restore(session)
        raise
    _session = session
    futil.log('Parametrisation: tracing installed')


def uninstall():
    global _session
    session = _session
    _session = None
    if session is None:
        return None
    _restore(session)
    futil.log('Parametrisation: %d expressions written, %d values left numeric'
              % (session.emitted, session.baked))
    return session


def _restore(session: _Session):
    for name, value in session.originalConstants.items():
        setattr(const, name, value)
    for key, prop in session.originalSetters.items():
        setattr(key[0], key[1], prop)
    for module, function in session.originalCreateRectangle:
        module.createRectangle = function
    if session.originalCreateByReal is not None:
        adsk.core.ValueInput.createByReal = session.originalCreateByReal


def _installConstants(session: _Session):
    for name in dir(const):
        if name.startswith('_') or name in CONST_EXCLUDED or name in CONST_DERIVED:
            continue
        value = getattr(const, name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        session.originalConstants[name] = value
        unit = unitFor(name, True)
        setattr(const, name, session.seed(
            constantToParameterName(name), value, unit, unit == UNIT_LENGTH))

    # Re-derive the computed constants so their formula survives.
    for name in CONST_DERIVED:
        if not hasattr(const, name):
            continue
        session.originalConstants[name] = getattr(const, name)
        setattr(const, name, CONST_DERIVED[name](const))


def _makeSeedingSetter(originalProperty, fieldName, session):
    def setter(instance, value):
        # Values that are already symbolic keep their derivation.
        if (not isSym(value)
                and isinstance(value, (int, float))
                and not isinstance(value, bool)):
            unit = unitFor(fieldName, False)
            value = session.seed(fieldName, value, unit, unit == UNIT_LENGTH)
        originalProperty.fset(instance, value)

    return property(originalProperty.fget, setter,
                    originalProperty.fdel, originalProperty.__doc__)


def _installInputSetters(session: _Session):
    for cls in PATCHED_INPUT_CLASSES:
        for name in dir(cls):
            if name.startswith('_') or name in FIELDS_EXCLUDED:
                continue
            attribute = getattr(cls, name, None)
            if not isinstance(attribute, property) or attribute.fset is None:
                continue
            session.originalSetters[(cls, name)] = attribute
            setattr(cls, name, _makeSeedingSetter(attribute, name, session))


GEOMETRY_TOLERANCE = 1e-9


def setDimensionExpression(session: _Session, dimension, value) -> bool:
    """Drive one sketch dimension from a symbolic value. Returns True if written.

    Sketch dimensions are measured in sketch space, which is not always model space
    (sketches built on a face can be translated or flipped relative to the model). So
    the write is verified: if substituting the expression changes the measured value,
    it did not mean what we thought and the original is put back. Geometry is never
    moved by this translation -- a mismatch degrades to a baked number and a log line.
    """
    if not isSym(value):
        session.baked += 1
        return False
    parameter = None
    previousExpression = None
    try:
        parameter = dimension.parameter
        if parameter is None:
            session.baked += 1
            return False
        previousExpression = parameter.expression
        previousValue = parameter.value
        parameter.expression = value.expression
        if abs(parameter.value - previousValue) > GEOMETRY_TOLERANCE:
            parameter.expression = previousExpression
            session.baked += 1
            futil.log('Parametrisation: reverted %s -> %s (value moved %r to %r)'
                      % (parameter.name, value.expression, previousValue, parameter.value))
            return False
        session.emitted += 1
        return True
    except Exception as err:
        if parameter is not None and previousExpression is not None:
            try:
                parameter.expression = previousExpression
            except Exception:
                pass
        session.baked += 1
        futil.log('Parametrisation: sketch expression rejected (%s): %s'
                  % (value.expression, err))
        return False


def _installSketchAdapters(session: _Session):
    """Cover dimensions that never reach ValueInput.

    Sketch dimensions are created from *geometry* -- addDistanceDimension() takes two
    points, not a ValueInput -- so intercepting createByReal() cannot see them. That
    misses the most important dimensions of all (bin and baseplate width and length).

    sketchUtils.createRectangle already receives width and length as arguments, so
    wrapping it recovers them exactly. It appends the width dimension and then the
    length dimension last, after any origin-offset dimensions.
    """
    from .. import sketchUtils

    original = sketchUtils.createRectangle

    def createRectangle(width, length, startPoint, sketch):
        countBefore = sketch.sketchDimensions.count
        result = original(width, length, startPoint, sketch)
        added = [sketch.sketchDimensions.item(i)
                 for i in range(countBefore, sketch.sketchDimensions.count)]
        if len(added) >= 2:
            setDimensionExpression(session, added[-2], width)
            setDimensionExpression(session, added[-1], length)
        return result

    # Modules that did `from .sketchUtils import createRectangle` hold their own
    # reference, so rebind every one of them rather than only the defining module.
    for module in list(sys.modules.values()):
        if module is None or not getattr(module, '__name__', '').find('gridfinityUtils') >= 0:
            continue
        if getattr(module, 'createRectangle', None) is original:
            session.originalCreateRectangle.append((module, original))
            module.createRectangle = createRectangle


def _installValueInput(session: _Session):
    original = adsk.core.ValueInput.createByReal
    session.originalCreateByReal = original

    def createByReal(value):
        if isSym(value):
            try:
                # Verify before use. A wrong expression here would silently build
                # different geometry -- exactly how a name collision between a const
                # and an input field once turned 0.255 into 0.280. Fusion can evaluate
                # the text without creating anything, so mismatches degrade to the
                # plain number instead of corrupting the model.
                # The units argument says how to read a bare number in the expression,
                # so it must match the quantity: cm (Fusion internal) for lengths,
                # unitless for counts and multipliers.
                evaluated = session.design.unitsManager.evaluateExpression(
                    value.expression, 'cm' if value.isLength else '')
                if abs(evaluated - float(value)) > GEOMETRY_TOLERANCE:
                    session.baked += 1
                    futil.log('Parametrisation: rejected %s -- evaluates to %r, expected %r'
                              % (value.expression, evaluated, float(value)))
                    return original(float(value))
                result = adsk.core.ValueInput.createByString(value.expression)
                session.emitted += 1
                return result
            except Exception as err:
                # Never fail a generation over a bad expression: fall back to the
                # number so the geometry is still correct, and record it.
                session.baked += 1
                futil.log('Parametrisation: expression rejected (%s): %s'
                          % (value.expression, err))
                return original(float(value))
        session.baked += 1
        return original(value)

    adsk.core.ValueInput.createByReal = staticmethod(createByReal)
