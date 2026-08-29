import adsk.core, adsk.fusion, traceback

from ... import fusion360utils as futil

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
REGISTERED = []


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


def applyBinCustomizations(
    design: adsk.fusion.Design,
    targetComponent: adsk.fusion.Component,
    commandInputs: adsk.core.CommandInputs,
    binBodyInput=None,
    baseGeneratorInput=None,
):
    if not REGISTERED:
        return
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


def applyBaseplateCustomizations(
    design: adsk.fusion.Design,
    targetComponent: adsk.fusion.Component,
    commandInputs: adsk.core.CommandInputs,
    baseplateGeneratorInput=None,
):
    if not REGISTERED:
        return
    _apply(
        CustomizationContext(
            design,
            targetComponent,
            commandInputs,
            baseplateGeneratorInput=baseplateGeneratorInput,
        ),
        'applyToBaseplate',
    )
