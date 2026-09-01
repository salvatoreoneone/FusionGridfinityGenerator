import adsk.core, adsk.fusion, traceback

from . import parametrization
from . import inputs as customInputs
from . import presets
from .features import cornerRelief
from .features import fullHeightDividers
from .features import settingsStamp
from .features import shelledDividers
from .features import shelledScoop
from .features import solidBase
from ... import fusion360utils as futil

# Translate the Python-coded parametrisation of the generators into live Fusion
# parameters, so generated models rebuild from named expressions rather than baked
# numbers. Set to False to get byte-identical upstream output.
PARAMETRIZATION_ENABLED = True

# Registered customizations, applied in registration order.
#
# Each entry is a module exposing:
#   NAME                      - str, used in log output
#   isEnabled(context)        - bool
#   applyToBin(context)       - called after the bin geometry is built
#   applyToBaseplate(context) - called after the baseplate geometry is built
#
# Empty by default: with nothing registered the hooks are inert and the add-in
# produces byte-identical output to upstream.
REGISTERED = [
    shelledDividers,
    # After the dividers: they split the front wall into one face per cell, so the
    # scoop then lands per cell the way hollow bins scoop each compartment.
    shelledScoop,
    # The hollow counterpart: brings its dividers up to the rim, where the shelled
    # ones already finish. Independent of the two above -- each is gated on its own
    # bin type -- and before the relief, which cuts through whatever is there.
    fullHeightDividers,
    # Independent of the dividers entirely: it works on the base rather than the cavity.
    # Still before the relief, which has to cut through the material it adds.
    solidBase,
    cornerRelief,
    settingsStamp,
]


class CustomizationContext():
    """Everything a customization needs from the host command.

    Deliberately does NOT carry the generated body. In commands/commandCreateBin/entry.py
    `binBody` is only assigned when the 'Generate body' input is checked (it is a bare
    annotation otherwise), so passing it unconditionally would raise UnboundLocalError.
    Customizations look bodies up from `targetComponent.bRepBodies` instead.
    """

    def __init__(
        self,
        design: adsk.fusion.Design,
        targetComponent: adsk.fusion.Component,
        commandInputs: adsk.core.CommandInputs,
        binBodyInput=None,
        baseGeneratorInput=None,
        baseplateGeneratorInput=None,
    ):
        self.design = design
        self.targetComponent = targetComponent
        self.commandInputs = commandInputs
        self.binBodyInput = binBodyInput
        self.baseGeneratorInput = baseGeneratorInput
        self.baseplateGeneratorInput = baseplateGeneratorInput


def _apply(context: CustomizationContext, handlerName: str):
    # Exceptions are intentionally not caught here. Both generateBin and
    # generateBaseplate already wrap their body in a try/except that reports failure
    # through args.executeFailedMessage, so letting errors propagate surfaces them in
    # the UI instead of silently producing wrong geometry.
    for customization in REGISTERED:
        handler = getattr(customization, handlerName, None)
        if handler is None:
            continue
        if not customization.isEnabled(context):
            futil.log(f'Customizations skipping {customization.NAME} (disabled)')
            continue
        futil.log(f'Customizations applying {customization.NAME}')
        handler(context)


def addBinInputs(commandUIState, commandInputs):
    """Append this fork's inputs to the bin dialog."""
    customInputs.addBinInputs(commandUIState, commandInputs)


# Upstream excludes these from saved defaults; a preset should not carry them either.
_PRESET_EXCLUDED = frozenset(['show_preview', 'show_preview_manual'])


def _presetPayload(commandUIState):
    ignore = list(customInputs.PRESET_CONTROL_IDS
                  | customInputs.TRANSIENT_CONTROL_IDS
                  | _PRESET_EXCLUDED)
    return commandUIState.toDict(ignoreKeys=ignore)


def handleBinInputChanged(changedInput, commandInputs, commandUIState, refresh) -> bool:
    """Handle this fork's dialog controls.

    Returns True when the event belongs to the preset controls and has been fully
    handled, so the host can return early rather than treating a button press as an
    ordinary value change.
    """
    inputId = changedInput.id

    # Whether a bin still stacks depends on where its dividers land, which nothing else
    # in the dialog shows. Recomputed on every change; the box is cheap to write.
    customInputs.updateDividerWarning(commandInputs)

    if inputId == customInputs.CUSTOM_GROUP_ID:
        # Claimed for the same reason as the preset group below: upstream registers every
        # child of an expanded group (commandCreateBin/entry.py:741-744), which would pull
        # the read-only warning box into saved defaults. The real settings in this group
        # are registered explicitly by addBinInputs, so nothing is lost by claiming it.
        commandUIState.onInputUpdate(changedInput)
        customInputs.forgetTransientControls(commandUIState)
        if refresh is not None:
            refresh()
        customInputs.updateDividerWarning(commandInputs)
        return True

    if inputId == customInputs.PRESET_GROUP_ID:
        # Claimed so upstream's group handler never registers the children. Keep the
        # group's own expansion state, which is worth persisting.
        commandUIState.onInputUpdate(changedInput)
        customInputs.forgetPresetControls(commandUIState)
        if refresh is not None:
            refresh()
        return True

    if inputId not in (customInputs.PRESET_SELECT_ID,
                       customInputs.PRESET_SAVE_ID,
                       customInputs.PRESET_DELETE_ID):
        return False

    # Clear anything a previous session's defaults may already have polluted.
    customInputs.forgetPresetControls(commandUIState)
    customInputs.forgetTransientControls(commandUIState)

    selector = commandInputs.itemById(customInputs.PRESET_SELECT_ID)
    nameInput = commandInputs.itemById(customInputs.PRESET_NAME_ID)

    status = None

    if inputId == customInputs.PRESET_SELECT_ID:
        name = customInputs.selectedPreset(commandInputs)
        if not name:
            status = 'Preset cleared. Current settings left unchanged.'
        else:
            state = presets.load(name)
            if state:
                commandUIState.initValues(state)
                commandUIState.forceUIRefresh()
                status = '<b>Loaded &quot;%s&quot;</b> &mdash; %d settings applied.' % (name, len(state))
                futil.log('Presets: loaded %r (%d settings)' % (name, len(state)))
            else:
                status = 'Could not read &quot;%s&quot;. Settings left unchanged.' % name
                futil.log('Presets: %r could not be read' % name)

    elif inputId == customInputs.PRESET_SAVE_ID:
        if not changedInput.value:
            return True
        changedInput.value = False
        name = (nameInput.value if nameInput else '').strip() or customInputs.selectedPreset(commandInputs)
        if not name:
            customInputs.setPresetStatus(
                commandInputs, 'Type a name in <i>Save as</i> first, or pick a preset to overwrite.')
            return True
        payload = _presetPayload(commandUIState)
        if presets.save(name, payload):
            if nameInput:
                nameInput.value = ''
            customInputs.populateSelector(selector, name)
            status = '<b>Saved &quot;%s&quot;</b> &mdash; %d settings.' % (name, len(payload))
            futil.log('Presets: saved %r to %s' % (name, presets.presetsPath()))
        else:
            status = 'Could not save &quot;%s&quot;. See the Text Commands log.' % name

    elif inputId == customInputs.PRESET_DELETE_ID:
        if not changedInput.value:
            return True
        changedInput.value = False
        name = customInputs.selectedPreset(commandInputs)
        if not name:
            status = 'Pick a preset to delete first.'
        elif presets.delete(name):
            customInputs.populateSelector(selector, presets.NONE_LABEL)
            status = '<b>Deleted &quot;%s&quot;.</b>' % name
            futil.log('Presets: deleted %r' % name)
        else:
            status = 'Could not delete &quot;%s&quot;.' % name

    if refresh is not None:
        try:
            refresh()
        except Exception as err:
            futil.log('Presets: refresh failed: %s' % err)

    # Set last: refresh() and forceUIRefresh() run first, so neither message is
    # overwritten by the redraw it triggers. A loaded preset can change bin size, grid or
    # divider mode, so the warning has to be recomputed here too.
    customInputs.updateDividerWarning(commandInputs)
    if status:
        customInputs.setPresetStatus(commandInputs, status)
    return True


def beginGeneration(design: adsk.fusion.Design):
    """Called before any geometry is built.

    The parametrisation tracer has to be active *while* the generators run -- it works
    by observing their arithmetic -- so it cannot be installed from the post-generation
    hook like ordinary customizations.
    """
    if not PARAMETRIZATION_ENABLED:
        return
    parametrization.install(design)


def endGeneration():
    """Called after geometry is built, before customizations run."""
    parametrization.uninstall()


def applyBinCustomizations(
    design: adsk.fusion.Design,
    targetComponent: adsk.fusion.Component,
    commandInputs: adsk.core.CommandInputs,
    binBodyInput=None,
    baseGeneratorInput=None,
):
    try:
        if REGISTERED:
            _apply(
                CustomizationContext(
                    design,
                    targetComponent,
                    commandInputs,
                    binBodyInput=binBodyInput,
                    baseGeneratorInput=baseGeneratorInput,
                ),
                'applyToBin',
            )
    finally:
        # After the customizations, not before: their geometry should be traced on the
        # same terms as the generator's.
        endGeneration()


def applyBaseplateCustomizations(
    design: adsk.fusion.Design,
    targetComponent: adsk.fusion.Component,
    commandInputs: adsk.core.CommandInputs,
    baseplateGeneratorInput=None,
):
    try:
        if REGISTERED:
            _apply(
                CustomizationContext(
                    design,
                    targetComponent,
                    commandInputs,
                    baseplateGeneratorInput=baseplateGeneratorInput,
                ),
                'applyToBaseplate',
            )
    finally:
        endGeneration()
