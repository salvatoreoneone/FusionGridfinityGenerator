"""Extra command-dialog inputs for this fork.

Kept here rather than in commands/commandCreateBin/entry.py so upstream files stay
almost untouched. Defaults are registered lazily: initUiState() has already run and any
saved configuration has already been loaded by the time these are added, so a value the
user has saved wins and initValue only fills in what is genuinely absent.
"""

import adsk.core, adsk.fusion

from .. import const
from . import dividerRules
from . import presets
from . import state as customState

# Defaults live here rather than in const.py so no upstream file is touched.
# Fusion internal length unit is cm: 0.5 == 5 mm.
CORNER_RELIEF_DIAMETER_DEFAULT = 0.5

CUSTOM_GROUP_ID = 'custom_group'
CORNER_RELIEF_ENABLED_ID = 'custom_corner_relief'
CORNER_RELIEF_DIAMETER_ID = 'custom_corner_relief_diameter'
DIVIDER_HEIGHT_ID = 'custom_divider_height'
SOLID_BASE_ID = 'custom_solid_base'
DIVIDER_WARNING_ID = 'custom_divider_warning'

# Upstream input ids this module reads to work out whether a bin will still stack.
# Duplicated rather than imported: lib/ must not depend on commands/.
BIN_TYPE_INPUT_ID = 'bin_type'
BIN_TYPE_HOLLOW = 'Hollow'
BIN_TYPE_SHELLED = 'Shelled'
BIN_WIDTH_INPUT_ID = 'bin_width'
BIN_LENGTH_INPUT_ID = 'bin_length'
BIN_GRID_WIDTH_INPUT_ID = 'compartments_grid_w'
BIN_GRID_LENGTH_INPUT_ID = 'compartments_grid_l'
BIN_WALL_THICKNESS_INPUT_ID = 'bin_wall_thickness'
BIN_XY_CLEARANCE_INPUT_ID = 'bin_xy_tolerance'
BIN_WITH_LIP_INPUT_ID = 'with_lip'

PRESET_GROUP_ID = 'custom_preset_group'
PRESET_SELECT_ID = 'custom_preset_select'
PRESET_NAME_ID = 'custom_preset_name'
PRESET_SAVE_ID = 'custom_preset_save'
PRESET_DELETE_ID = 'custom_preset_delete'
PRESET_STATUS_ID = 'custom_preset_status'
PRESET_PATH_ID = 'custom_preset_path'

STATUS_IDLE = 'No preset loaded.'

# Transient feedback, not a setting: it must never reach the defaults file or a preset.
TRANSIENT_CONTROL_IDS = frozenset([DIVIDER_WARNING_ID])

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
    _ensureDefault(commandUIState, DIVIDER_HEIGHT_ID, dividerRules.MODE_AUTO,
                   adsk.core.DropDownCommandInput.classType())
    _ensureDefault(commandUIState, SOLID_BASE_ID, False,
                   adsk.core.BoolValueCommandInput.classType())

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

    _addDividerInputs(commandUIState, group)
    _addPresetInputs(commandUIState, inputs)
    updateDividerWarning(inputs)


def _addDividerInputs(commandUIState, group: adsk.core.GroupCommandInput):
    dividerHeight = group.children.addDropDownCommandInput(
        DIVIDER_HEIGHT_ID, 'Divider height',
        adsk.core.DropDownStyles.LabeledIconDropDownStyle)
    selected = commandUIState.getState(DIVIDER_HEIGHT_ID)
    for name in dividerRules.MODES:
        dividerHeight.listItems.add(name, name == selected, '')
    dividerHeight.tooltip = (
        'How tall the compartment dividers are. '
        'Automatic: a divider separating a whole number of gridfinity units runs to the '
        'top of the bin, because it lands in the groove between the base feet of the bin '
        'above; every other divider stops at the top of the label plate, so the bin still '
        'stacks. '
        'Cap at label plate: every divider stops there, on a boundary or not. '
        'Extend to bin top: every divider runs to the rim, and one that is not on a unit '
        'boundary will stop another bin seating on top of this one.')
    commandUIState.registerCommandInput(dividerHeight)

    solidBase = group.children.addBoolValueInput(
        SOLID_BASE_ID, 'Remove notches from the base grid', True, '',
        commandUIState.getState(SOLID_BASE_ID))
    solidBase.tooltip = (
        'Fill the V grooves between the gridfinity units on the underside, so the base is '
        'one continuous foot instead of a grid of them. The outer profile is unchanged, so '
        'the bin still seats on a baseplate, but with the grooves gone it can no longer sit '
        'over the full-height dividers of the bin below.')
    commandUIState.registerCommandInput(solidBase)

    # Deliberately not registered, for the same two reasons as the preset status line:
    # it is transient feedback, and staying unregistered keeps forceUIRefresh() from
    # writing a stale message back over it.
    warning = group.children.addTextBoxCommandInput(DIVIDER_WARNING_ID, 'Stacking', '', 2, True)
    warning.isFullWidth = True


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


def forgetPresetControls(commandUIState):
    """Drop the preset controls from saved UI state, keeping the group itself.

    Upstream registers every child of a group when it is expanded
    (commandCreateBin/entry.py, command_input_changed). That pulls the status and path
    text boxes and the two buttons into saved state, after which forceUIRefresh() writes
    a stale message over the status line and the controls leak into the defaults file.
    The group's own expansion is worth keeping; its children are not.
    """
    if commandUIState is None:
        return
    for inputId in PRESET_CONTROL_IDS:
        if inputId != PRESET_GROUP_ID:
            commandUIState.removeValue(inputId)


def forgetTransientControls(commandUIState):
    """Drop the warning box from saved UI state.

    Upstream registers every child of a group when it is expanded
    (commandCreateBin/entry.py:741-744), which would sweep this read-only text box into
    the defaults file and into every preset saved afterwards.
    """
    if commandUIState is None:
        return
    for inputId in TRANSIENT_CONTROL_IDS:
        commandUIState.removeValue(inputId)


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


def dividerHeightMode(commandInputs: adsk.core.CommandInputs) -> str:
    dropdown = commandInputs.itemById(DIVIDER_HEIGHT_ID) if commandInputs else None
    item = dropdown.selectedItem if dropdown else None
    return item.name if item else dividerRules.MODE_AUTO


def isSolidBaseEnabled(commandInputs: adsk.core.CommandInputs) -> bool:
    if commandInputs is None:
        return False
    enabled = commandInputs.itemById(SOLID_BASE_ID)
    return bool(enabled) and bool(enabled.value)


def _value(commandInputs: adsk.core.CommandInputs, inputId, fallback=None):
    found = commandInputs.itemById(inputId) if commandInputs else None
    return found.value if found else fallback


def _count(number, noun) -> str:
    if not number:
        return ''
    return '%d %s%s' % (number, noun, '' if number == 1 else 's')


def _formatRed(text: str) -> str:
    """Same red-warning convention the compartment size readout uses
    (commandCreateBin/entry.py:323-326). Copied rather than imported: lib/ must not
    depend on commands/."""
    return "<p style='color:red'>%s</p>" % text


def axisAlignment(binType, units, count):
    """(aligned, total) dividers on one axis.

    Shelled bins distribute whole units while there are enough to go round, so every
    divider is on a boundary by construction. Every other case is equal fractions of the
    cavity, where a divider is on a boundary only when the modulo works out.
    """
    units = max(1, int(units))
    count = max(1, int(count))
    total = count - 1
    if total <= 0:
        return (0, 0)
    if binType == BIN_TYPE_SHELLED and count <= units:
        return (total, total)
    aligned = sum(1 for k in range(1, count)
                  if dividerRules.isGridAligned(k, count, units))
    return (aligned, total)


def updateDividerWarning(commandInputs: adsk.core.CommandInputs):
    """Say whether the current settings still produce a bin another bin can sit on.

    Divider height depends on where each divider lands, which is not something the
    dialog otherwise shows, so without this the trade-off is invisible until the bin is
    printed and will not stack.
    """
    if commandInputs is None:
        return
    box = commandInputs.itemById(DIVIDER_WARNING_ID)
    if box is None:
        return

    binType = commandInputs.itemById(BIN_TYPE_INPUT_ID)
    binType = binType.selectedItem.name if binType and binType.selectedItem else ''
    if binType not in (BIN_TYPE_HOLLOW, BIN_TYPE_SHELLED):
        box.formattedText = 'No compartments on this bin type.'
        return

    mode = dividerHeightMode(commandInputs)
    solidBase = isSolidBaseEnabled(commandInputs)
    alignedX, totalX = axisAlignment(
        binType, _value(commandInputs, BIN_WIDTH_INPUT_ID, 1),
        _value(commandInputs, BIN_GRID_WIDTH_INPUT_ID, 1))
    alignedY, totalY = axisAlignment(
        binType, _value(commandInputs, BIN_LENGTH_INPUT_ID, 1),
        _value(commandInputs, BIN_GRID_LENGTH_INPUT_ID, 1))

    problems = []
    notes = []

    if mode == dividerRules.MODE_FULL:
        strayX = totalX - alignedX
        strayY = totalY - alignedY
        if strayX or strayY:
            where = ' and '.join(
                part for part in [
                    _count(strayX, 'divider across the width'),
                    _count(strayY, 'divider along the length'),
                ] if part)
            problems.append(
                'Will not stack: %s %s at the rim without sitting on a gridfinity unit '
                'boundary, where the base feet of the bin above go.'
                % (where, 'is' if strayX + strayY == 1 else 'are'))
    fullHeight = (totalX + totalY) if mode == dividerRules.MODE_FULL else (
        0 if mode == dividerRules.MODE_CAP else alignedX + alignedY)

    wallThickness = _value(commandInputs, BIN_WALL_THICKNESS_INPUT_ID)
    xyClearance = _value(commandInputs, BIN_XY_CLEARANCE_INPUT_ID)
    if fullHeight and wallThickness is not None and xyClearance is not None:
        limit = dividerRules.maxStackingThickness(xyClearance)
        if wallThickness > limit + const.DEFAULT_FILTER_TOLERANCE:
            problems.append(
                'Will not stack: a %.2f mm divider is wider than the %.2f mm groove '
                'between the feet of the bin above.'
                % (wallThickness * 10, limit * 10))

    if solidBase:
        problems.append(
            'Base notches removed: this bin can no longer sit over another bin&apos;s '
            'full-height dividers.')

    hasLip = _value(commandInputs, BIN_WITH_LIP_INPUT_ID, True)
    if not hasLip:
        # Nothing seats on a bin without a lip, so how tall its dividers are cannot
        # matter. The base note survives: that one is about what this bin sits *on*.
        problems = [problem for problem in problems if problem.startswith('Base notches')]
        notes = ['No lip, so nothing stacks on this bin either way.']
    elif not problems:
        if fullHeight:
            notes.append('Stacks. %s reach the rim, on unit boundaries.'
                         % _count(fullHeight, 'divider'))
        elif totalX + totalY:
            notes.append('Stacks. Every divider stops at the top of the label plate.')
        else:
            notes.append('Stacks. No dividers on this bin.')

    box.formattedText = (_formatRed(' '.join(problems)) if problems
                         else ' '.join(notes))
