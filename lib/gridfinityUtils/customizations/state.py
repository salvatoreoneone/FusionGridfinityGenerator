"""Handle on the host command's UI state object.

addBinInputs() already receives it, so stashing it here saves threading it through
every later hook. Set per command invocation; read by customizations that need the
full dialog state (presets, the settings stamp).
"""

_commandUiState = None


def setCommandUiState(state):
    global _commandUiState
    _commandUiState = state


def commandUiState():
    return _commandUiState
