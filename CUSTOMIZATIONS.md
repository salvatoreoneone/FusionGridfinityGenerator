# Customizations

This fork keeps changes to upstream files to an absolute minimum so that
`git merge upstream/master` stays trivial. Nearly all custom code lives in
`lib/gridfinityUtils/customizations/`, which upstream never touches.

**This file is the checklist to re-verify after every upstream merge.**

Baseline: upstream tag `v1.4.3.0` (commit `c82982d`). The installed bundle was
byte-identical to that tag, so `git diff v1.4.3.0` shows only our work.

---

## Edits to upstream files

The complete merge-conflict surface. Keep this list short.

### `commands/commandCreateBin/entry.py` — 4 lines

| Lines | Change |
|---|---|
| import block | `from ...lib.gridfinityUtils import customizations` |
| end of `generateBin`, before the timeline-group creation | `customizations.applyBinCustomizations(des, gridfinityBinComponent, inputs, binBodyInput, baseGeneratorInput)` |

Placed *before* `des.timeline.timelineGroups.add(...)` so custom features land inside
the plugin's own timeline group rather than dangling after it.

### `commands/commandCreateBaseplate/entry.py` — 4 lines

| Lines | Change |
|---|---|
| import block | `from ...lib.gridfinityUtils import customizations` |
| end of `generateBaseplate`, before `if des.designType == ParametricDesignType:` | `customizations.applyBaseplateCustomizations(des, gridfinityBaseplateComponent, args.command.commandInputs, baseplateGeneratorInput)` |

Placed before the `ParametricDesignType` check because that block only creates the
timeline group; the customization itself must run either way.

---

## Notes and gotchas

**`binBody` is not passed to the hook, deliberately.** In `generateBin`,
`binBody: adsk.fusion.BRepBody` is a bare annotation — it is only *assigned* when the
"Generate body" input is checked. Reading it unconditionally raises `UnboundLocalError`
when body generation is off. Customizations resolve bodies from
`context.targetComponent.bRepBodies` instead.

**The hook runs during preview as well as execute.** `generateBin` backs both
`command_execute` and `command_preview`, so customizations must be safe to run
repeatedly and must not depend on execute-only state.

**Exceptions are not caught in the registry.** Both generator functions already wrap
their body in a try/except that reports through `args.executeFailedMessage`. Letting
errors propagate surfaces them in the UI rather than silently producing wrong geometry.

**`.gitignore` is untouched.** Deployment artifacts present in the installed bundle but
absent from upstream (`docs/`, `icons/` — referenced by `../PackageContents.xml` as
`HelpFile`/`SupportPath`) are excluded via `.git/info/exclude` instead, so `.gitignore`
stays byte-identical to upstream and can never conflict.

---

## Registered customizations

None yet. With `REGISTERED` empty the hooks are inert and output is identical to stock.
