"""Extra command-dialog inputs for this fork.

Kept here rather than in commands/commandCreateBin/entry.py so upstream files stay
almost untouched. Defaults are registered lazily: initUiState() has already run and any
saved configuration has already been loaded by the time these are added, so a value the
user has saved wins and initValue only fills in what is genuinely absent.
"""

import adsk.core, adsk.fusion

# Defaults live here rather than in const.py so no upstream file is touched.
# Fusion internal length unit is cm: 0.5 == 5 mm.
CORNER_RELIEF_DIAMETER_DEFAULT = 0.5

CUSTOM_GROUP_ID = 'custom_group'
CORNER_RELIEF_ENABLED_ID = 'custom_corner_relief'
CORNER_RELIEF_DIAMETER_ID = 'custom_corner_relief_diameter'


def _ensureDefault(commandUIState, inputId, value, classType):
    if inputId not in commandUIState.inputState:
        commandUIState.initValue(inputId, value, classType)


def addBinInputs(commandUIState, inputs: adsk.core.CommandInputs):
    app = adsk.core.Application.get()
    defaultLengthUnits = app.activeProduct.unitsManager.defaultLengthUnits

    _ensureDefault(commandUIState, CUSTOM_GROUP_ID, True,
                   adsk.core.GroupCommandInput.classType())
    _ensureDefault(commandUIState, CORNER_RELIEF_ENABLED_ID, False,
                   adsk.core.BoolValueCommandInput.classType())
    _ensureDefault(commandUIState, CORNER_RELIEF_DIAMETER_ID, CORNER_RELIEF_DIAMETER_DEFAULT,
                   adsk.core.ValueCommandInput.classType())

    group = inputs.addGroupCommandInput(CUSTOM_GROUP_ID, 'Customizations')
    group.isExpanded = commandUIState.getState(CUSTOM_GROUP_ID)
    commandUIState.registerCommandInput(group)

    enabled = group.children.addBoolValueInput(
        CORNER_RELIEF_ENABLED_ID, 'Add corner relief', True, '',
        commandUIState.getState(CORNER_RELIEF_ENABLED_ID))
    enabled.tooltip = (
        'Cut a vertical relief at each of the four corners of the bin footprint, '
        'through the full height. Use it to clear the rounded internal corners or '
        'corner posts of a box the bin has to sit in.')
    commandUIState.registerCommandInput(enabled)

    diameter = group.children.addValueInput(
        CORNER_RELIEF_DIAMETER_ID, 'Corner relief diameter', defaultLengthUnits,
        adsk.core.ValueInput.createByReal(commandUIState.getState(CORNER_RELIEF_DIAMETER_ID)))
    diameter.minimumValue = 0.01
    diameter.isMinimumInclusive = True
    commandUIState.registerCommandInput(diameter)


def isCornerReliefEnabled(commandInputs: adsk.core.CommandInputs) -> bool:
    if commandInputs is None:
        return False
    enabled = commandInputs.itemById(CORNER_RELIEF_ENABLED_ID)
    return bool(enabled) and bool(enabled.value)


def cornerReliefDiameter(commandInputs: adsk.core.CommandInputs) -> float:
    diameter = commandInputs.itemById(CORNER_RELIEF_DIAMETER_ID) if commandInputs else None
    return diameter.value if diameter else CORNER_RELIEF_DIAMETER_DEFAULT
