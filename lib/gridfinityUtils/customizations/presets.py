"""Named presets for the bin dialog, stored in one findable file.

Upstream keeps a single anonymous set of defaults inside the add-in folder
(commands/commandCreateBin/commandConfig), which is invisible and is wiped whenever the
add-in is reinstalled. This keeps named presets outside the bundle instead, so they
survive updates, and reports the exact path in the dialog so it is never a mystery
where they live.

Storing them in the Fusion project was measured and rejected: DataFolder.uploadFile
takes about 5.5 s, Fusion rewrites the extension (.json arrived as ext=htm), and
DataFile.download is callback-only, so a preset list could not be populated when the
dialog opens without stalling it. Every generated bin is stamped with the settings that
produced it instead (see features/settingsStamp.py), which covers the same need from the
other direction: any old bin can tell you what made it.
"""

import json
import os

from ... import fusion360utils as futil

FOLDER_NAME = 'GridfinityPresets'
FILE_NAME = 'presets.json'

NONE_LABEL = '<none>'


def _baseFolder() -> str:
    home = os.path.expanduser('~')
    documents = os.path.join(home, 'Documents')
    parent = documents if os.path.isdir(documents) else home
    return os.path.join(parent, FOLDER_NAME)


def presetsPath() -> str:
    return os.path.join(_baseFolder(), FILE_NAME)


def _read() -> dict:
    path = presetsPath()
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as handle:
            data = json.load(handle)
        presets = data.get('presets') if isinstance(data, dict) else None
        return presets if isinstance(presets, dict) else {}
    except Exception as err:
        futil.log('Presets: could not read %s: %s' % (path, err))
        return {}


def _write(presets: dict) -> bool:
    path = presetsPath()
    try:
        folder = os.path.dirname(path)
        if not os.path.isdir(folder):
            os.makedirs(folder)
        with open(path, 'w') as handle:
            json.dump({'version': 1, 'presets': presets}, handle, indent=1, sort_keys=True)
        return True
    except Exception as err:
        futil.log('Presets: could not write %s: %s' % (path, err))
        return False


def names() -> list:
    return sorted(_read().keys())


def load(name: str):
    return _read().get(name)


def save(name: str, state: dict) -> bool:
    name = (name or '').strip()
    if not name or name == NONE_LABEL:
        return False
    presets = _read()
    presets[name] = state
    return _write(presets)


def delete(name: str) -> bool:
    presets = _read()
    if name not in presets:
        return False
    del presets[name]
    return _write(presets)
