"""Record on every generated bin the settings that produced it.

Answers "which settings made this?" from the design itself, so it does not matter where
a preset file ended up or whether one was saved at all. Stored as a design attribute,
which round-trips reliably and travels with the file when it syncs.

Read them back from a script with:

    design.attributes.itemByName('GridfinityGenerator', 'settings').value
"""

import json

import adsk.core, adsk.fusion

from .. import inputs as customInputs
from .. import state as customState
from .... import fusion360utils as futil

NAME = 'Settings stamp'

ATTRIBUTE_GROUP = 'GridfinityGenerator'
ATTRIBUTE_NAME = 'settings'


def isEnabled(context) -> bool:
    # Always on: it adds no geometry, only a record of how the geometry was made.
    return True


def _stamp(context):
    design = context.design
    if design is None:
        return
    uiState = customState.commandUiState()
    if uiState is None:
        return
    try:
        # The preset controls describe the preset machinery, not the bin.
        payload = json.dumps(
            uiState.toDict(ignoreKeys=list(customInputs.PRESET_CONTROL_IDS)),
            sort_keys=True)
    except Exception as err:
        futil.log('%s: could not serialise settings: %s' % (NAME, err))
        return
    try:
        design.attributes.add(ATTRIBUTE_GROUP, ATTRIBUTE_NAME, payload)
        futil.log('%s: recorded %d characters of settings' % (NAME, len(payload)))
    except Exception as err:
        futil.log('%s: could not write attribute: %s' % (NAME, err))


def applyToBin(context):
    _stamp(context)
