# Tidy plugin

Build **"put everything away"** games in Fio: books back on the shelf, tidy up
the museum, clear the warehouse floor. The player walks up to objects, picks
them up one at a time, and stows them in the right place until a goal is met —
scaling to **thousands** of objects.

Try it: open **`maps/Tidy_Test.json`** and hit Play. Look at a book, press
**E** to pick it up, face the shelf, press **E** to put it away. The HUD shows
`Tidied: N / 42`.

---

## Entities

Place these from the 2D view's right-click menu under **Plugins ▸ tidy**.

### Tidy Object
A single carryable prop. Renders as a real 3D model in play mode (ships with a
small book-shaped model; swap it via the **Model** picker in the Properties
panel — any `.obj`/`.glb` works).

| Property | Meaning |
|----------|---------|
| `category` | Logical group (`book`, `cup`, `bone`…). A receptacle only takes objects whose category it accepts. |
| `model_path` | 3D model to render (defaults to the bundled box). |
| `scale`, `rotation` | Standard model transform. |
| `no_collision` | `True` by default so thousands of props stay cheap and walk-through. |

Outputs: `OnPickedUp`, `OnDropped`, `OnTidied`.
Inputs: `Reset` (send home), `Enable`, `Disable`.

### Tidy Receptacle (shelf / bin)
A drop-zone. When the player places an object here it snaps into the next free
slot, arranged in a neat grid.

| Property | Meaning |
|----------|---------|
| `accepts` | Category it takes, or `any`. |
| `capacity` | Max objects it holds. |
| `slot_cols` | Objects per row before stacking upward. |
| `slot_spacing` | `[x, y, z]` spacing between slots (X across a row, Y per shelf). |
| `slot_offset` | `[x, y, z]` offset of the first slot from the receptacle origin. |
| `reach` | How close/aligned the player must be to place into it. |

Outputs: `OnObjectPlaced` (parameter = new count), `OnFull`.
Inputs: `Reset` (empty it), `Enable`, `Disable`.

The receptacle itself has no geometry — put it just above a shelf brush (or a
bin model) so placed objects visually land on the surface. Tune `slot_offset`
and `slot_spacing` to match your shelf.

### Tidy Goal
Invisible logic entity that tracks progress and ends the round.

| Property | Meaning |
|----------|---------|
| `target` | `all` (every object) or an integer count. |
| `category` | Restrict the goal to one category, or `any`. |
| `show_hud` | Show the live `Tidied: N / M` counter. |

Outputs: `OnProgress` (parameter = `done/need`, fired on every stow),
`OnComplete` (fired once when the target is reached).
Inputs: `Enable`, `Disable`.

Wire `OnComplete` to a `LevelChanger`, a `Speaker`, a door, a light — whatever
should happen when the room is tidy.

---

## Controls

- **E** (use/interact) — pick up the object under the crosshair.
- **E** again — place into the shelf you're facing, or drop it if none is in
  reach.

The HUD prompts contextually (`[E] Pick up Book`, `[E] Put away (Shelf)`,
`[E] Drop`) and shows live progress when idle.

---

## Recipes

**Books back on the shelf.** Scatter `Tidy Object`s (`category: book`) on the
floor. Put one `Tidy Receptacle` (`accepts: book`) above a shelf brush with
`slot_cols` matching how many fit per shelf. Add a `Tidy Goal` (`target: all`).

**Tidy up the museum (sorting).** Give objects different categories
(`fossil`, `painting`, `pot`). Add one receptacle per category, each with its
`accepts` set. Use a single `Tidy Goal` (`category: any, target: all`), or one
goal per category to fire per-section rewards.

**Thousands of objects.** Just place (or procedurally generate) more `Tidy
Object`s — the runtime indexes available objects in a spatial hash, so the
per-frame "what am I looking at" check stays fast no matter how many exist.
Keep `no_collision` on (the default). Give receptacles generous `capacity`.

---

## How it works (for the curious)

- `entities.py` — the three `Thing` subclasses (data only).
- `runtime.py` — `TidySession`: carry/place logic, a `SpatialHash` over
  available objects, receptacle slot maths, goal tracking, and the HUD line.
- `plugin.py` — registration, I/O handlers, and the play lifecycle wiring.
- `assets/tidy_object.obj` — the default carryable model.

Regenerate the demo map with:

```bash
QT_QPA_PLATFORM=offscreen python plugins/tidy/tools/make_example_map.py
```
