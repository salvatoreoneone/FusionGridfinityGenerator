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

### `commands/commandCreateBin/entry.py` — bug fix, 2 lines changed

**The only place upstream logic is modified rather than extended.** Everything else in
this fork is additive.

Shelled bins left a `xyClearance` gap between the label tab and the bin wall on each
side. The shell is cut at `wallThickness - xyClearance` (entry.py:1017, 1024), but the
tab was positioned at `wallThickness` and shortened by `wallThickness * 2 +
xyClearance * 2`, so it fell short of the wall by `xyClearance` per side.

| line | change |
|---|---|
| tab origin X | `wallThickness` -> `wallThickness - xyClearance` |
| tab length | dropped the `- xyClearance * 2` term |

The length simplifies exactly: `tabLength * baseWidth - 2*xyClearance -
2*(wallThickness - xyClearance)` reduces to `tabLength * baseWidth - 2*wallThickness`.

Only the shelled path is affected. The hollow path builds the tab full width and
intersects it with the compartment cutout (`binBodyGenerator.py:143`), so it cannot
drift out of alignment this way.

Verified on a 2x1x1 shelled bin with a tab at base 32x49 mm: no planar faces remain at
`wallThickness` (0.12 / 6.23), and the tab sides now coincide with the shell wall at
0.095 / 6.255, merging into it.

**If upstream fixes this themselves, drop this change rather than merging both.**

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
   than a `ValueInput` and so cannot be caught at (3),
5. records symbolic values entering `Point3D.create()` and recovers them on the way
   back out.

Step 5 matters more than it looks. `Point3D` is native and stores plain doubles, so a
value passed in comes back as a float with its derivation gone -- and feature
*positions* go through it. Without recovery, editing `binHeight` grew the bin body but
left the lip at its original Z: a model that looked driven but was only half driven. A
value seen with two different derivations is marked ambiguous and never recovered;
missing an expression is harmless, attributing the wrong one is not.

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


## Presets

`presets.py`, plus the Presets group in `inputs.py`.

Named presets for the bin dialog, stored in **one file outside the bundle**:
`~/Documents/GridfinityPresets/presets.json`. The dialog shows the full path read-only,
so where they live is never a guess. Upstream's single anonymous default set lives inside
the add-in folder and is wiped on reinstall; this is not.

Save under a name, pick from the dropdown to load every dialog value, delete the
selected one. Reusing a name overwrites.

A **Status** line reports every action — `Loaded "Tactix 32x49" — 43 settings applied`,
`Saved …`, `Deleted …` — because applying a preset silently changes a dialog full of
values with nothing to show it happened. It also guides the near-misses: saving with no
name, or deleting with nothing selected.

The status box is deliberately *not* registered with `commandUIState`. That keeps it out
of saved state, and stops `forceUIRefresh()` from wiping the message during the redraw
that loading a preset triggers. For the same reason the message is written after
`refresh()`, not before.

Not registering it is not sufficient on its own. Upstream registers **every child of a
group** when that group is expanded, so expanding Presets would pull the status and path
boxes into saved state anyway. The `custom_preset_group` event is therefore claimed by
`handleBinInputChanged`, which records the group's own expansion and then calls
`forgetPresetControls()` to drop the children. Preset actions purge as well, to clear
pollution an earlier session may already have written to the defaults file. The
Customizations group is deliberately *not* claimed — corner-relief settings are real
settings and belong in saved state.

### Why not in the Fusion project

That was the first choice, and it was measured and rejected:

| | |
|---|---|
| `DataFolder.uploadFile` | works, but takes ~5.5 s per save |
| file extension | Fusion rewrote `.json` to `ext=htm` |
| `DataFile.download` | callback-only (`missing 1 required positional argument: 'handler'`) |

A preset dropdown has to populate when the dialog opens, and it cannot do that off a
callback-only read without stalling. The extension rewriting also left it unproven that
the content survives a round-trip at all. Stamping (below) covers the same need from the
other direction.

### Shelled dividers — `features/shelledDividers.py`

Makes the compartment grid work for shelled bins. `entry.py` sets
`isSolid = isSolid or isShelled` and `binBodyGenerator.py:112` builds compartments only
`if not input.isSolid`, so **shelled bins never get compartments** — the Grid width and
length inputs sit in the dialog doing nothing. This adds divider walls where the hollow
path cuts compartment cavities. Hollow bins are untouched.

Translated from a hand-built model: a Rib on a midplane between the two outer side faces,
drawn from a line at the top and grown down until it met material.

**Ribs cannot be reproduced.** `adsk.fusion.RibFeatures` exposes only
`count`/`item`/`itemByName` — no `createInput`, no `add` — and there is no
`RibFeatureInput` class. Same for Web. The wall is therefore built as a solid box and
joined, which means computing what the rib got for free.

Spacing mirrors the hollow path exactly (`binBodyGenerator.py:118-122`), so both bin
types divide identically. On the hand-built 2x1 bin that formula lands the wall at
3.115..3.235 cm — precisely where the rib measured.

Three details worth keeping:

* Walls run the **full footprint** in their perpendicular direction rather than stopping
  at the cavity, so no sliver of gap is left where the cavity wall fillets curve away. A
  join is a no-op where material already exists.
* They extend one shell thickness **below** the cavity floor for the same reason, and the
  result is clamped to the body's own underside — overshooting would push material out of
  the bottom of the bin.
* The top is **not** padded. Material above the rim would break stacking.

The cavity floor is found by rule, not derived: it depends on the shell operation and on
whether a lip is present. It is the **lowest** qualifying horizontal face — not the
largest, and bounded to faces above `z = 0`.

Both of those bounds were learned the hard way:

* **Lowest, not largest.** A label tab puts a wide ledge high in the cavity — on a 2x1x1
  bin it measures 3.894 against the floor's 0.412 — so choosing by area plants the
  dividers *on the label*, leaving a 0.525 cm stub under the rim instead of a full-height
  wall. This shipped, because the test that "passed" ran with `hasTab = False`. Depth is
  what identifies a floor; size is not.
* **Above `z = 0`.** The base foot's chamfered underside is horizontal and sits inside the
  cavity footprint, so without the bound the dividers get driven out of the bottom of the
  bin.

Verified with a **tab present** at grid 2x1: the divider spans z 0.0744..2.3800, exactly
the range of the hand-built rib it was translated from. Also at 3x2 (three walls, both
axes). Bounding box unchanged top and bottom, single solid body in each case.

### Shelled scoop — `features/shelledScoop.py`

The scoop is Hollow-only upstream, behind two independent gates:

    entry.py:954   binBodyInput.isSolid  = isSolid or isShelled
    entry.py:956   binBodyInput.hasScoop = has_scoop.value and isHollow

Line 956 ands the checkbox with `isHollow`, so ticking "Add scoop" on a shelled bin
resolves to `False` with nothing to say it was ignored. And even without that, line 954
marks shelled bins solid, so `binBodyGenerator.py:112` skips the compartment block, which
is where the scoop is built. Same root cause as the missing compartments.

Reads the **raw checkbox** rather than `binBodyInput.hasScoop`, which is already forced
`False` for this bin type, then fillets the bottom edge of the front interior wall. Runs
after the dividers, which split that wall into one face per cell — so the scoop lands per
cell, matching how hollow bins scoop each compartment.

Two things worth keeping:

* **The wall is found by position, not by normal direction.** `Plane.normal` is the
  surface's own normal and says nothing about the face's orientation within the solid —
  that needs `isParamReversed`. Measured on a shelled bin, the front interior wall reports
  `n.y = -1` and the back wall `n.y = +1`, the opposite of what "points into the cavity"
  would suggest. The wall is the only face at `y = shell`, so position is unambiguous.
* **The radius is bounded by the wall, not the cavity.** The wall stops at the lip, well
  below the rim, so a radius sized against cavity height (2.285) exceeds the wall it has
  to roll along (1.99) and the fillet fails outright rather than degrading.

Verified at grid 1x1 (one scoop) and 2x1 (two scoops, one per cell) with the checkbox on,
and skipped cleanly with it off. Bounding box unchanged, single solid body throughout.

### Settings stamp — `features/settingsStamp.py`

Every generated bin records the settings that produced it, as a design attribute. Read
it back with:

    design.attributes.itemByName('GridfinityGenerator', 'settings').value

So "which settings made this?" is answerable from any old design, whether or not a
preset was ever saved. Re-stamping replaces rather than accumulating.

### Known limitation

Presets carry the dialog inputs, not the **custom compartments table**. Restoring that
would mean rebuilding table rows through upstream's own helpers, which is far more
coupling than the rest of this fork needs. Uniform compartment grids are covered, since
those are plain inputs.


## Registered customizations

### Corner relief — `features/cornerRelief.py`

Cuts a full-height cylindrical relief at each of the four corners of the bin footprint,
so the bin clears the rounded internal corners or corner posts of the box it sits in.
Off by default; enabled per-bin from a "Customizations" group in the dialog, with a
diameter input defaulting to 5 mm.

Translated from a hand-built model — four Ø5 mm circles on the XY plane, centres
projected from the generated body's corners, cut two-sided through everything. Verified
against that model: bounding box, volume (71.24397 cm3), face count (219) and edge
count (483) all identical.

Two deliberate departures from what was modelled by hand:

* **Corner positions are computed from parameters, not projected from geometry.** The
  hand model projected from `'Simple box at point sketch'`, which belongs to the *lip* —
  so the relief silently depended on lip geometry it has nothing to do with, and would
  have broken outright with the lip switched off. The generator already computes the
  footprint at `binBodyGenerator.py:33-34`, so nothing has to be searched for. This is
  the "computed placement from parameters" tier: it cannot select the wrong entity
  because it selects nothing.
* **Depth is computed rather than a fixed 50 mm**, spanning base through lip, so it
  stays a through-cut at any bin height.

**Reinforcement.** Notching the corner leaves less than a wall thickness between the
relief surface and the compartment cavity. The cut faces are therefore lined with a skin
one `wallThickness` thick, grown back towards the material, which restores it. The lining
follows the relief exactly and is bounded by the notch, so it cannot spill outside the
bin the way an offset cylinder would.

Two API details worth keeping:

* **Thicken rejects faces of a solid** (`input face cannot be from solid body`). The
  faces are copied out as surfaces at zero offset first — the same offset-then-thicken
  pattern as `baseGenerator.py:322-353` — and the temporary surfaces are removed after.
* **Direction is negative** (`THICKEN_DIRECTION`). A cut face points into the void it
  created, so the material side lies opposite its normal. The wrong sign fills the notch
  back in rather than lining it.

Measured on a 2x3x5 bin: stock 71.52878 cm3 -> 71.24397 after the cut -> 71.48603 after
reinforcement, with the bounding box unchanged throughout (nothing added outside the
bin) and the four relief faces still present (the notch survives). Also verified on a
solid no-lip bin and at a 12 mm diameter that cuts well past the corner fillet; one
solid body in every case.

Customizations run *before* the tracer is removed, so their geometry is parameterised on
the same terms as the generator's — the relief contributes 8 expressions of its own.
