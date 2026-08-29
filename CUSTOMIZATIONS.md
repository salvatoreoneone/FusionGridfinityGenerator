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

### `commands/commandCreateBin/entry.py` — 5 lines

| Lines | Change |
|---|---|
| import block | `from ...lib.gridfinityUtils import customizations` |
| after `originalTimelineCount = des.timeline.count` | `customizations.beginGeneration(des)` |
| end of `generateBin`, before the timeline-group creation | `customizations.applyBinCustomizations(des, gridfinityBinComponent, inputs, binBodyInput, baseGeneratorInput)` |

Placed *before* `des.timeline.timelineGroups.add(...)` so custom features land inside
the plugin's own timeline group rather than dangling after it.

### `commands/commandCreateBaseplate/entry.py` — 5 lines

| Lines | Change |
|---|---|
| import block | `from ...lib.gridfinityUtils import customizations` |
| after `originalTimelineCount = des.timeline.count` | `customizations.beginGeneration(des)` |
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

**The tracer needs a pre-generation hook.** It works by observing the arithmetic of the
generators, so unlike ordinary customizations it cannot be installed from the
post-generation hook. `install()` also tears down any session left open by a failed
generation, since both generator functions swallow exceptions into
`executeFailedMessage` and would otherwise leak patched globals.

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

## Parametrisation: Python formulas -> Fusion parameters

`lib/gridfinityUtils/customizations/` — `symbolic.py` and `parametrization.py`.

The generators compute every dimension in Python and hand Fusion the *result* via
`ValueInput.createByReal()`, so the model is fully dimensioned but with baked numbers:
`d21` reads `7.75 mm`, not `screwHolesOffset - xyClearance`. The derivations exist only
in the source.

This makes them real Fusion expressions, so generated models rebuild from named
parameters. While a generation runs it:

1. replaces the numeric constants in `const` with symbolic equivalents,
2. wraps the generator-input property setters so dialog values become symbolic,
3. intercepts `ValueInput.createByReal()` and emits `createByString(<expression>)`,
4. wraps `sketchUtils.createRectangle`, whose dimensions come from geometry rather
   than a `ValueInput` and so cannot be caught at (3).

**Why a tracer instead of a lookup table.** The expressions come from executing the
plugin's own arithmetic, not from a hand-written mapping. When upstream changes a
formula, the translation follows automatically. A transcribed table would rot on every
upstream merge — the opposite of what this fork needs.

Disable with `PARAMETRIZATION_ENABLED = False` in `registry.py`.

### Safety properties

Both write paths verify before committing, so a wrong expression can never move
geometry — it degrades to a baked number plus a log line:

* `createByReal` — the expression is evaluated with `unitsManager.evaluateExpression`
  and compared to the Python value before use.
* sketch dimensions — the expression is written, the measured value re-read, and the
  original restored if it moved.

Verified: bins at 1x1x2, 2x1x3, 3x2x6, 5x4x4 and 2x2x3 (with and without lip, solid and
hollow) all produce geometry **identical to stock** — same bounding box, volume, face
and edge counts. Turning `baseWidth` from 42 to 50 mm moves the model correctly.

### Known gaps

* **Angles are excluded.** The generators pass them through `math.radians()`, which
  returns a plain float and breaks the symbolic chain. An angle parameter would be
  created but would drive nothing, so it is better absent. Needs the tracer to
  understand `math.radians()`.
* **Values that pass through `Point3D` are baked.** `Point3D.create()` is native and
  stores plain doubles, so reading `.x`/`.z` back loses the symbol. Feature *positions*
  therefore stay numeric even when their *sizes* are driven -- editing `binHeight` grows
  the bin body but leaves the lip at its original Z. Editing lengths that come from
  sketch rectangles (`baseWidth`, `baseLength`) works correctly.
* **Circle-sketch dimensions are still baked** — screw and magnet positions
  (`7.75 mm`), diameters (`6.5 mm`). These come from `createCircleAtPointSketch` and
  `shapeUtils.simpleCylinder`, which position geometry by `Point3D` coordinates; the
  symbolic values are lost at the native boundary. Needs adapters like the
  `createRectangle` one.
* Roughly a quarter of the remaining numeric parameters are genuine constants
  (`0 deg` taper, `0 mm` offsets, fillet flags) and need no expression.

### Name collisions

Constants and input fields can want the same parameter name while holding different
values — `BIN_CORNER_FILLET_RADIUS` is 4 mm while the `binCornerFilletRadius` input is
3.75 mm. The second gets a numeric suffix (`binCornerFilletRadius2`). The same
mechanism stops a second generation in one document from retuning the first.


## Registered customizations

None yet. With `REGISTERED` empty the post-generation hooks are inert.
