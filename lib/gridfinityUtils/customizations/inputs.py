"""Extra command-dialog inputs for this fork.

Kept here rather than in commands/commandCreateBin/entry.py so upstream files stay
almost untouched. Defaults are registered lazily: initUiState() has already run and any
saved configuration has already been loaded by the time these are added, so a value the
user has saved wins and initValue only fills in what is genuinely absent.
"""

import adsk.core, adsk.fusion

from . import presets
from . import state as customState

# Defaults live here rather than in const.py so no upstream file is touched.
# Fusion internal length unit is cm: 0.5 == 5 mm.
CORNER_RELIEF_DIAMETER_DEFAULT = 0.5

CUSTOM_GROUP_ID = 'custom_group'
CORNER_RELIEF_ENABLED_ID = 'custom_corner_relief'
CORNER_RELIEF_DIAMETER_ID = 'custom_corner_relief_diameter'

PRESET_GROUP_ID = 'custom_preset_group'
PRESET_SELECT_ID = 'custom_preset_select'
PRESET_NAME_ID = 'custom_preset_name'
PRESET_SAVE_ID = 'custom_preset_save'
PRESET_DELETE_ID = 'custom_preset_delete'
PRESET_STATUS_ID = 'custom_preset_status'
PRESET_PATH_ID = 'custom_preset_path'

STATUS_IDLE = 'No preset loaded.'

# The preset controls describe the preset machinery itself, so they must never be
# captured into a preset or restored from one.
PRESET_CONTROL_IDS = frozenset([
    PRESET_GROUP_ID, PRESET_SELECT_ID, PRESET_NAME_ID,
    PRESET_SAVE_ID, PRESET_DELETE_ID, PRESET_STATUS_ID, PRESET_PATH_ID,
])


def _ensureDefault(commandUIState, inputId, value, classType):
    if inputId not in commandUIState.inputState:
        commandUIState.initValue(inputId, value, classType)


def addBinInputs(commandUIState, inputs: adsk.core.CommandInputs):
    customState.setCommandUiState(commandUIState)

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

    _addPresetInputs(commandUIState, inputs)


def _addPresetInputs(commandUIState, inputs: adsk.core.CommandInputs):
    _ensureDefault(commandUIState, PRESET_GROUP_ID, True,
                   adsk.core.GroupCommandInput.classType())

    group = inputs.addGroupCommandInput(PRESET_GROUP_ID, 'Presets')
    group.isExpanded = commandUIState.getState(PRESET_GROUP_ID)
    commandUIState.registerCommandInput(group)

    selector = group.children.addDropDownCommandInput(
        PRESET_SELECT_ID, 'Preset', adsk.core.DropDownStyles.LabeledIconDropDownStyle)
    populateSelector(selector)
    selector.tooltip = 'Pick a saved preset to load every dialog value from it.'

    nameInput = group.children.addStringValueInput(PRESET_NAME_ID, 'Save as', '')
    nameInput.tooltip = (
        'Name to save the current settings under. Reusing an existing name overwrites '
        'that preset.')

    saveButton = group.children.addBoolValueInput(PRESET_SAVE_ID, 'Save preset', False, '', False)
    saveButton.text = 'Save'
    deleteButton = group.children.addBoolValueInput(PRESET_DELETE_ID, 'Delete preset', False, '', False)
    deleteButton.text = 'Delete selected'

    # Deliberately not registered with commandUIState: it is transient feedback, and
    # leaving it unregistered also keeps forceUIRefresh() from overwriting the message
    # right after a preset is applied.
    status = group.children.addTextBoxCommandInput(PRESET_STATUS_ID, 'Status', STATUS_IDLE, 1, True)
    status.isFullWidth = True

    path = group.children.addTextBoxCommandInput(PRESET_PATH_ID, 'Stored in', presets.presetsPath(), 2, True)
    path.isFullWidth = True


def setPresetStatus(commandInputs: adsk.core.CommandInputs, message: str):
    """Show what just happened. Selecting a preset otherwise applies it silently, which
    gives no sign the dialog values have been replaced."""
    if commandInputs is None:
        return
    status = commandInputs.itemById(PRESET_STATUS_ID)
    if status is not None:
        status.formattedText = message


def populateSelector(selector: adsk.core.DropDownCommandInput, selected: str = None):
    """(Re)fill the preset dropdown, keeping the given entry selected if it still exists."""
    if selector is None:
        return
    if selected is None:
        current = selector.selectedItem
        selected = current.name if current else presets.NONE_LABEL
    items = selector.listItems
    items.clear()
    names = [presets.NONE_LABEL] + presets.names()
    if selected not in names:
        selected = presets.NONE_LABEL
    for name in names:
        items.add(name, name == selected, '')


def selectedPreset(inputs: adsk.core.CommandInputs):
    selector = inputs.itemById(PRESET_SELECT_ID) if inputs else None
    item = selector.selectedItem if selector else None
    name = item.name if item else presets.NONE_LABEL
    return None if name == presets.NONE_LABEL else name


def isCornerReliefEnabled(commandInputs: adsk.core.CommandInputs) -> bool:
    if commandInputs is None:
        return False
    enabled = commandInputs.itemById(CORNER_RELIEF_ENABLED_ID)
    return bool(enabled) and bool(enabled.value)


def cornerReliefDiameter(commandInputs: adsk.core.CommandInputs) -> float:
    diameter = commandInputs.itemById(CORNER_RELIEF_DIAMETER_ID) if commandInputs else None
    return diameter.value if diameter else CORNER_RELIEF_DIAMETER_DEFAULT
