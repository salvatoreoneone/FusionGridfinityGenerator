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

Dividers sit on gridfinity **unit boundaries** while there are units enough to go round.
A bin is a whole number of units and a divider separates whole units, so the boundary
after k units is at `k * baseWidth - xyClearance`. On a 2u bin with a 32 mm base that is
3.175, and a 1.2 mm wall centred there spans 3.115..3.235 — precisely where the
hand-built rib measured. Compartment sizes are whole units, the remainder going to the
leading compartments: a 5u bin split into 2 gives 3u then 2u.

**More compartments than units falls back to equal fractions of the cavity**, the rule
the hollow path uses. It used to clamp instead, which is why a bin **1u across produced
no dividers at all**: `clampedCount(1, n)` collapsed the count to 1, and one compartment
has no divider behind it. That was the bug — the Grid inputs looked live and did nothing.

The fallback places a wall so it *ends* where the next compartment starts, one thickness
before `cavityMin + k * (cell + thickness)`, the same relation upstream's cutouts have
(`binBodyGenerator.py:125`). Getting that off by one thickness makes the compartments
unequal and is invisible in a screenshot.

Which walls may then reach the rim is `dividerRules`' decision, not this module's — see
**Divider height** below.

Three details worth keeping:

* Walls run the **full footprint** in their perpendicular direction rather than stopping
  at the cavity, so no sliver of gap is left where the cavity wall fillets curve away. A
  join is a no-op where material already exists.
* They stand on the **tub floor**, the deepest point of the interior. `simpleShell`
  hollows the whole solid including the base feet, so every gridfinity unit's interior
  bottoms out at `bodyBottom + shell` — on a 25 mm height unit that is z = -0.405, well
  below zero. This is the same floor the scoop lands its ramps on.
* The top is **not** padded. Material above the rim would break stacking.

**The floor used to be searched for, and the search was wrong.** `cavityFloor()` took the
lowest horizontal face above `z = 0`, which on a shelled bin is a 0.095 sliver at the rim
of the shell — the scoop's own notes had already said so and refused to reuse it. The
walls therefore started at z = 0 and hung the full 5 mm depth of the base above the floor,
with a gap underneath wide enough to lose parts through. It is now computed, and the
function is gone.

Reaching below `z = 0` is what makes the clip necessary: down there the bin is no longer a
prism but a set of chamfered feet with V grooves between them, and a wall running the full
footprint would fill the grooves and the flanks. Each wall is therefore trimmed with
`binEnvelope` before being joined — exactly as the scoop trims its ramps. Above `z = 0`
nothing needs trimming, so it only runs when there is a base at all.

Verified with a **tab present** on a 2x1x1 at 32x49 mm, 25 mm height unit: walls stand at
z = -0.405 and the bounding box is unchanged against the same bin with no dividers, in
every case tried — 1u, 3u, 2u split four ways, both axes, with and without a lip.

### Envelope clipping — `binEnvelope.py`

Shared by the scoop and the dividers, both of which add material below `z = 0`.

Anything joined on down there has to respect the base: the corner fillets, the chamfered
flanks of each foot, and the V grooves where two feet meet. Put material in any of those
and the bin no longer seats on a baseplate or under another bin — and a bounding box will
not tell you, because all of it is *inside* the box.

Two negatives, and both are needed. `footprintPrism` is the outer footprint over the whole
height with corner fillets, which also brings the feet down to the xyClearance size that
`createBaseBodyPattern` does not apply on its own. `baseImprint` is everything below the
body that is *not* foot, so cutting with it leaves the flanks and grooves alone; the feet
are rebuilt from the same `baseGeneratorInput` the bin was made with, so the profile
matches exactly.

Bodies are clipped **one at a time, against kept tool bodies**. A Fusion Join of *disjoint*
solids leaves them separate rather than merging, so clipping several as one body silently
drops all but the first — which is how the scoop lost every row but the front one before
this was understood.

### Divider height — `dividerRules.py`

Both divider features ask one module how tall a wall may be, so hollow and shelled cannot
drift apart again.

A wall that reaches the rim crosses the lip opening, which is where the base feet of the
bin above seat. It only fits in the groove *between* two of those feet, and that groove
is narrowest exactly at our rim:

    groove at the rim = 2 * (xyClearance + BIN_LIP_TOP_RECESS_HEIGHT) = 1.7 mm

— two feet meet at a knife edge `2 * xyClearance` apart at the top of the base, and our
rim sits `BIN_LIP_TOP_RECESS_HEIGHT` below the underside of the bin above
(`BIN_LIP_EXTRA_HEIGHT + BIN_LIP_TOP_RECESS_HEIGHT == BIN_BASE_HEIGHT`), by which point
the foot's 45 degree top chamfer has opened the gap by that much per side. A 1.2 mm wall
centred on a unit boundary clears it by 0.25 mm per side. A wall anywhere else fouls.

So height depends on **position**: a divider separating a whole number of gridfinity
units may run to the rim, and one that does not stops at `cappedTopZ`, the top of the
label plate. That cap is not invented either. It is the clearance shelf upstream already
shaves off the whole inner top when there is more than one compartment
(`binBodyGenerator.py:164`) and the height the label tab is built to
(`binBodyTabGenerator.py:41`) — so on the hollow path "capped" means *leave it alone*.

**Equal-fraction dividers are never exactly on a boundary.** Asking a wall centred in
upstream's cavity to also be centred on `k * baseWidth - xyClearance` needs
`minX = -xyClearance - wallThickness / 2`, and `minX` is `wallThickness`. What is left
over is `xyClearance + wallThickness/2 - (m/units) * (2*xyClearance + wallThickness)` on
the hollow path — 0.28 mm on a 3u bin, zero on a 2u one, under a wall thickness at
worst. That is **treated as alignment anyway**, on instruction: it is the same order as
the slack the groove already carries, and closing it would mean either moving upstream's
compartments (an edit to `binBodyGenerator.py`, which this fork exists to avoid) or making
the compartments unequal, which is worse than the problem.

The **Divider height** dropdown overrides the rule in either direction — *Cap at label
plate* for every divider, *Extend to bin top* for every divider — and the **Stacking**
box beside it turns red and names the axis at fault whenever the current settings would
produce a bin nothing can sit on. It also flags a wall thicker than the groove
(`maxStackingThickness`), which the dialog otherwise allows up to 2 mm.

### Solid base — `features/solidBase.py`

Fills the V grooves between the gridfinity units on the underside, so the base is one
continuous foot.

The grooves are emergent, not authored: there is no code that draws them and no flag that
switches them off. `createBaseBodyPattern` replicates a fully chamfered foot at exactly
`baseWidth` spacing while each foot's top rectangle is the *full* unit size, so two
neighbours meet at a knife edge and each one's 2.4 mm chamfer slopes away from it.
`cutBaseClearance` only trims the outer perimeter, so the interior grooves carry no
clearance at all. Nothing to disable — the fill has to be added.

    filler = createSingleGridfinityBaseBody(footprint-sized input)
    cut(filler, createBaseBodyPattern(real feet, holes off))
    join(bin, the groove sections left over)

Two details the construction depends on:

* **The filler is built pre-trimmed** — at `baseWidth * binWidth - 2 * xyClearance` with
  the corner fillet `cutBaseClearance` uses, origin at the body corner. Its outer surface
  therefore sits at or inside the real perimeter everywhere, so it cannot add material
  outside the envelope, and a join is a no-op where material exists. No clip needed.
* **The feet subtracted from it have their screw and magnet cutouts forced off.** Those
  cutouts are voids *inside* the feet and the filler spans them, so subtracting the real
  hole-bearing feet would leave filler sitting in every hole and the join would plug them.

The result is usually several disjoint bodies — one per boundary, meeting only where two
boundaries cross — and each touches the feet either side and the body above, so joining
them all against the bin does merge. Skipped on a 1x1 bin (one foot, no grooves) and when
there is no base.

**Tracing is suspended while it builds.** This is the one customization that re-runs a
generator with *different* values in the same input fields: its filler wants `baseWidth`
to mean the whole footprint, 63.5 mm, while the bin's own base already claimed that name
for 32 mm. The tracer keys parameters by field name, so it wrote the bin's expression onto
the filler's dimension. The verify-and-revert guards fired and logged
`rejected baseWidth — evaluates to 6.35, expected 3.2`, but the geometry came out wrong
anyway — a 2u bin 63.5 mm wide instead of 31.75, volume 21.19 against 13.79 — and the
upstream `RemoveBody-label tab` feature then failed to recompute, which is what a user sees
as a broken bin. `parametrization.suspended()` turns tracing off for the block and puts it
back afterwards. The cost is that the fill is dimensioned with baked numbers, which is
right for geometry nobody would want to edit by name.

**This is a deliberate departure from the gridfinity spec.** The bin still seats on a
baseplate, the outer profile being untouched, but with the grooves gone it can no longer
sit over the full-height dividers of the bin below. The tooltip and the warning box say
so.

Verified on a 3x2 with screw holes and magnets: bounding box identical, volume
58.8017 — 63.9872, one solid body, all 24 screw holes and 24 magnet cutouts still
present, and the only faces lost are 8 foot corner fillets in the interior, which is the
point. With tracing suspended the run emits exactly the same 54 expressions as the same bin
with the option off.

### Shelled scoop — `features/shelledScoop.py`

The scoop is Hollow-only upstream, behind two independent gates:

    entry.py:954   binBodyInput.isSolid  = isSolid or isShelled
    entry.py:956   binBodyInput.hasScoop = has_scoop.value and isHollow

Line 956 ands the checkbox with `isHollow`, so ticking "Add scoop" on a shelled bin
resolves to `False` with nothing to say it was ignored. And even without that, line 954
marks shelled bins solid, so `binBodyGenerator.py:112` skips the compartment block, which
is where the scoop is built. Same root cause as the missing compartments.

Reads the **raw checkbox** rather than `binBodyInput.hasScoop`, which is already forced
`False` for this bin type. Runs after the dividers, which split each ramp into one scoop
per cell, and before the corner relief, which has to cut through the new material.

### Why it is a joined solid and not a fillet

The first version filleted the concave corner between the front cavity wall and the floor
— which is how you would draw it by hand, and how upstream does it on the cutout body. It
shipped, ran, logged success, and produced nothing usable.

A shelled bin has no such corner. `simpleShell` hollows the whole solid, **base feet
included**, so each gridfinity unit's interior is a tub bottoming out at
`bodyBottom + shell` and rising through the foot's chamfer profile to meet the vertical
wall. On the reference 1x3x1 at a 25 mm height unit the tub floor is at `z = -0.405` and
the wall starts at `z = 0.0144` — a 45 degree ramp 2.15 mm long for an 18.86 mm radius to
roll along. Fusion trimmed the fillet into a sliver spanning `y 0.095..0.31`,
`z -0.2006..0.6739` and ate the front of the floor; the wall face afterwards started at
`z = 0.6739`. Bounding the radius to what that ramp can carry would give a 2 mm scoop,
which is not worth having.

So the ramp is **built** instead: a box the height and depth of the radius, with a
cylinder of that radius cut out of it, joined to the bin. `shapeUtils.simpleCylinder`
takes its plane as an argument, so passing the YZ plane gives the X axis with no new
geometry code.

It lands on the **tub floor**, not on the wall/ramp junction, so the scoop sweeps from the
deepest point of the interior up to the top of the wall with no ledge to lift parts over.
That extra depth is the reason to shell a bin rather than hollow it, and a ramp that
stopped above it would be cosmetic. Measured on the reference bin, the tub floor resumes
at exactly `y = 2.5`, where the arc lands tangentially — no step and no gap.

### Clipping to the envelope

A wedge spanning the full footprint would reach past the corner fillets, past the foot
chamfers and into the V grooves between feet, and the bin would no longer seat on a
baseplate or under another bin. Each ramp is therefore clipped with `binEnvelope` —
intersected with the footprint prism, then cut by the base imprint. Screw and magnet
cutouts are already forced off for this bin type at `entry.py:926-928`, so the rebuilt feet
match without further work.

Both are skipped when *Generate base* is off — the body starts at `z = 0`, the floor
collapses to the shell thickness and the prism alone is enough.

Three details worth keeping:

* **The full footprint width is deliberate**, the same reasoning as `shelledDividers`: a
  join is a no-op where material already exists, so running the wedge through the dividers
  and into the side walls leaves no sliver where the cavity's corner fillets curve away.
* **Every row is scooped**, not just the front one, matching how hollow bins scoop each
  compartment. Rows come from `shelledDividers.wallPositions()` — the walls that were
  actually built — so a row appears wherever a wall does, under whichever placement rule
  applied to that axis. This is also where the 1u fix reaches the scoop: a bin 1u long
  used to get no walls, and therefore a single ramp for the whole bin.
* **The ramps are clipped one at a time, against kept tool bodies** (— now
  `binEnvelope.clip`). The first version joined them into a single body first, and a Fusion
  Join of *disjoint* solids leaves them separate rather than merging: on a 3x2 grid the
  second row silently became a leftover body and never reached the bin.

The cavity top comes from `dividerRules.bodyTopZ()`, computed from
`binBodyGenerator.py:36` rather than measured: the body's own bounding box would give the
top of the *lip*, 4.4 mm higher and not where the cavity ends. The floor is
`bodyBottom + shell`, the same expression the dividers now stand on.

Verified on the reference bin (1x3x1, base 21.5 × 47.5 mm, 25 mm height unit, 1.2 mm wall,
lip, tab, grid 3x1, scoop on): three scoop faces of radius 2.405 spanning `y 0.095..2.5`
and `z -0.405..2.0`, volume 15.8541 → 22.0893, **bounding box unchanged** at
x 0..6.4 / y 0..4.7 / z -0.5..2.38 — the real test that nothing landed outside the
envelope — and one solid body. Also at grid 3x2 (two rows, six scoop faces, the second row
at `y 4.785..7.19`), without a lip, and without a base (floor collapses to 0.095, radius
1.905, feet and imprint skipped). One solid body and an unchanged bounding box in every
case.

**Not covered:** shelled + lip + *Generate base* off fails in `entry.py`'s split before any
customization runs — `faceUtils.maxByArea` picks the flat bottom face, and the split plane
never intersects the body. Pre-existing upstream, unrelated to this feature.

### Full-height dividers — `features/fullHeightDividers.py`

The hollow counterpart to the shelled dividers, and the reason both finish at the
same height. Hollow and shelled disagreed by a whole lip:

| | divider top |
|---|---|
| shelled | the rim — `shelledDividers` builds each wall as a box up to the top of the body |
| hollow | `binBodyTotalHeight`, less `BIN_TAB_TOP_CLEARANCE` |

Upstream cuts the compartments downwards from `binBodyTotalHeight`, which already stops
the dividers at the *bottom* of the lip, then `binBodyGenerator.py:164` shaves another
0.5 mm off the whole inner top whenever there is more than one compartment. On the
reference 3x1 bin that is a 4.3 mm step: shelled dividers reach 2.38, hollow ones stop at
1.95.

Additive like the rest of the fork: upstream still cuts its clearance slab, and this
joins it back in along with the void the lip leaves above. The walls run the full
footprint in their perpendicular direction, so nothing is left where the lip's inner
chamfer curves away — a join is a no-op where material already exists.

**Only the dividers that fit are raised**, per **Divider height** above: a raised wall
crosses the lip opening, so it fits only in the groove between two of the feet above, and
therefore only on a unit boundary. Every other divider is left exactly where upstream's
clearance slab put it, and the bin still stacks. The first version raised all of them
unconditionally, which is what made a bin with compartments unstackable unless the grid
happened to line up.

Wall positions are computed from the generator's own arithmetic
(`binBodyGenerator.py:113-122`), not measured, so they land exactly where the compartment
cutouts left them. **Custom layouts are respected**: a compartment spanning two cells has
no wall between them and raising one there would bridge its top, so a grid line a
compartment crosses is raised row by row, skipping the rows it covers. Grid lines nothing
crosses are raised in one piece.

Verified on a 3x1 with lip (dividers 1.95 -> 2.38, rim face area 1.4935 -> 2.5879), the
same bin without a lip (1.95 -> 2.00), and a custom 3x2 whose first row spans columns 0-1
— which produced segments `(2.0933, 4.70, 0.12, 4.75)`, `(4.1867, 0, 0.12, 9.45)` and
`(0, 4.70, 6.4, 0.12)`, leaving the wide compartment open. Bounding box unchanged and one
solid body in every case.

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
count (483) all identical — that is the cut on its own, before the reinforcement below,
which adds material the hand model has not got.

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

**Reinforcement.** The relief is centred on the *sharp* footprint corner, which sits
`sqrt(2) * R - R` outside the filleted outer surface — 1.553 mm at the stock 3.75 mm
corner radius — so a relief of radius r eats `r - 0.414 * R` into the corner. All the
corner has to give is one wall thickness, and less than that on a shelled bin, where the
shell is `wallThickness - xyClearance` (`commandCreateBin/entry.py:1019`). Past that the
relief opens straight into the cavity.

That is not an edge case at the default Ø5 mm: it cuts 0.947 mm into the corner, so on a
shelled bin it breaks through at any wall thinner than 1.197 mm. At 0.8 mm (0.55 mm of
shell) it leaves a 49° slot 2.07 mm across running the full height of the bin, and 1.2 mm
lands 3 µm inside the limit, which is a knife edge rather than a wall. Hollow bins have
the whole `wallThickness` and breach from Ø4.71 mm at 0.8 mm, Ø5.51 mm at 1.2 mm.

So each corner is **filled out to `relief radius + wallThickness` before the cut**,
clipped to a rebuilt bin outline, which gives the relief a full wall thickness to cut
into at any diameter. The outline is the footprint filleted the way the body itself is,
chamfered below z=0 by the base's top section height so it follows the base taper; it is
at or inside the real perimeter everywhere, so the slug cannot reach outside the bin.
How far the slug runs in z is read off the bin's bounding box rather than recomputed, so
it stays inside the material with the base or the body switched off. A join is a no-op
where material already exists, which is what a solid bin gets.

**The slug carries a collar into the lip.** The thin corner does not end at the body: the
lip is thinned back to the wall where the two meet — `lipBottomChamferExtrude`
(`binBodyGenerator.py:76-84`) is a box inset by one `wallThickness`, chamfered at 45
degrees — so the lip's inner face starts at `cornerOffset + wallThickness` from the corner
and climbs to full rim thickness only `relief radius - cornerOffset` higher up. Over that
stretch the relief cuts the same thin corner it cuts below, so the slug carries straight
on at its own radius until the lip's chamfer has grown out to meet it, and the corner
wall runs unbroken from the base into the rim. On the Ø5 mm / 0.8 mm shelled bin that is
a 0.947 mm collar at 3.3 mm radius.

**The collar is clamped to the recess wall.** Above the body, the void being filled is the
seat the next bin's foot drops into, not the compartment. The recess sits at
`cornerOffset + BIN_BASE_TOP_SECTION_HEIGH - 2 * xyClearance` from the corner —
`binBodyLipGenerator.py:108-122` cuts it with a base body oversized by `xyClearance * 2`
— so the collar stops there and the foot keeps its own clearance. The clamp starts biting
at about a 1.2 mm wall, where `relief radius + wallThickness` would otherwise stand in the
seat: a stacked pair of 1x1x3 bins at the 25 mm pitch measured 0.002016 cm3 of
interference across the four corners when the slug ran the full height unclamped, every
lump of it bounded by the cylinder at `relief radius + wallThickness`.

**Why not thicken the cut faces.** The first version lined the relief afterwards: copy
the cut faces out as surfaces at zero offset (thicken rejects faces of a solid — `input
face cannot be from solid body`), thicken them back towards the material, join. It
restores a *thinned* corner, and that is all it can do — a thicken follows the faces that
survived the cut, and where the relief has already breached the cavity there is no face
over the breach to follow. The lining came out on either side of the hole and left the
hole. Adding the material first needs no faces to be found at all, which also retires the
`_reliefFaces` search.

Customizations run *before* the tracer is removed, so their geometry is parameterised on
the same terms as the generator's, the relief's own arithmetic included.
