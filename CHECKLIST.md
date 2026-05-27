# Data Preparation Checklist

Use this checklist to prepare your experiment's data for processing into `.mat` files. 

`(enforced)` marks items the pipeline checks and will stop on if they are wrong. Unmarked items
will not block the pipeline — some it will warn about — and the final say is yours.

---

## Checklist

- [ ] Experiment is named as its start date, `YYYY-MM-DD`. No other experiment should share the same date. 
- [ ] In Ethovision, check each trial's nose point tracks correctly and sits on the target before export & trials follow the naming convention (see Trial Naming and Numbering). 
- [ ] In Ethovision, get the target coordinates per entrance (See [Target Coordinates](#target-coordinates).
- [ ] In Ethovision, get the background extent coordinates (see [Image Extent](#image-extent).
- [ ] Export Excel files for every trial from Ethovision, placed in the `1_raw/` folder.
- [ ] Take an arena snapshot from a trial video and place it in the `2_background_images/` folder.
- [ ] Know the sex of every mouse, and strain/condition if relevant (each listed per mouse if they vary within the experiment).
- [ ] Prepare to write a description that notes the experiment setup, any target shifts, and any special      trial conditions.

Details for each below.

---
## 1. Ethovision Steps

### Experiment name

- The name is the start date, `YYYY-MM-DD` — e.g. `2025-01-21`. *(enforced)*
- Keep this name for the whole experiment, even as it runs across multiple days.

### Tracking quality (before exporting)

- Check each trial's tracking: the nose point should track the mouse's leading point, and on rewarded trials it should sit on the target. Ethovision sometimes swaps the nose and tail, which makes a good trial look like the mouse never reached the target. Swap them back before exporting.
- The pipeline flags suspected swaps and trials that don't reach the target.

### Trial naming and numbering

These are recommendations, not rules. If you deviate, it is on you to remember which names you actually use.

Recommended:
- Capitalize named trials: `Probe`, not `probe`.
- Number repeats with a space: `Habituation 1`, `Habituation 2`, not `habit1`. A single one is just `Habituation`.
- Do not abbreviate: `Habituation`, not `Habit`.

The tool warns when names deviate, but does not stop you. So `habit1`, `habit2` is allowed — your
downstream analysis just needs a selector that matches them (e.g. `habit*`) instead of `Habituation*`.

Essential:
- **Number trials sequentially, including around named trials: `1, 2, 3, Probe, 4, 5`.** A skipped number usually means a trial is mis-numbered or missing, so the tool flags it prominently — you can still proceed if the gap is intentional.
- **No two trials for the same mouse can share a name** — they would write to the same output file and overwrite each other. *(enforced)*

### Target Coordinates

- Record each target by its entrance: `NW entrance -> reward at (x, y)`. Get coordinates by mousing over the target in the Ethovision Arena Setup tab.
- Anchor on the entrance, not the mouse. If a mouse's target changes, still give the per-entrance coordinates.
- No target at `(0, 0)`; it is treated as missing. *(enforced)*

### Image Extent
- In Ethovision, open the arena tab and get the coordinates of the edges of the image in this order: -x-axis, +x-axis, -y-axis, +y-axis
- Hover your mouse over the very left edge and right edge to get the -x and +x coordinates. Hover your mouse over the very bottom and top edges to get the -y and +y coordinates.
- Example: `-139.27, 139.13, -78.26, 78.69`

### Entrance codes

- Recommended set: `NW`, `SW`, `SE`, `NE`. The labels must match what you recorded in Ethovision. *(enforced: must match)*
- They are room directions, not camera directions. The `NW` entrance might not be the top-left of the image. That is ok as long as it is consistent within the experiment.


## 2. Arena screenshot
- Open a trial video in VLC, scroll to when the arena is clear, and take a snapshot using `Video --> Take Snapshot`. The image should be saved in your Pictures folder. You can rename the image with the experiment name and any other reminders (e.g. `BKGD_2024-11-09_arenaA.png`) and place it in the `2_background_images/` folder.
- Pick a video near the **middle** of the experiment, preferably the Probe; the arena can drift slightly as the experiment runs if you accidentally bumped it. 
- Arena clear, fully in frame, evenly lit. Nothing else in the arena — no wires, mice, or objects; these can be counted as extra holes.
- All holes empty and visible; a food-filled hole can be missed.
- Boost brightness contrast if needed (e.g. in Photoshop) so the edge and holes stand out.
- If you can't get a clear image, get the best image you can and edit out the obstructions (e.g in Photoshop).
- Must yield exactly one arena and 100 holes. *(enforced)*
- **If different cohorts ran on different arenas** (e.g. mice 1–4 on arena A, mice 5–8 on arena B), put **one screenshot per arena** in this folder and list the per-mouse override in `3_config/mouse_map.csv` (`background_image` and `img_extent` columns). See README § *Multiple arenas in one experiment*.


## 3. Info for the CSV files

### Experiment description
Free text in `experiment_list.csv`. Include:

- The protocol setup.
- When shifts occur — e.g. the target changes after trial 20, or a probe runs after trial 30.
- Special trial conditions — opto, lights out, barriers — and a brief note on any specially-named trials.
- Mouse sex: goes in its own column. Set `mouse_sex = mixed` if the cohort has both sexes, then add one row per mouse to `3_config/mouse_map.csv` (REQUIRED whenever sex is `mixed`).
- Mouse strain/condition (e.g. `WT`, `ATRX-KO`): (optional), leave the column blank if not relevant, set it experiment-wide if all mice share a strain, or per-mouse overrides go in `3_config/mouse_map.csv` if it varies (WT vs KO).
- Multi-arena experiments: if different mice in this experiment ran on physically different arenas, add per-mouse `background_image` and `img_extent` overrides to `3_config/mouse_map.csv` and put one screenshot per arena in `2_background_images/`. Scope per-arena target coordinates via the `mice` column in `targets/<DATE>_targets.csv`. See README § *Multiple arenas in one experiment*.


CSVs open in Excel, Numbers, or LibreOffice, which may automatically reformat entries (dates, leading
zeros, scientific notation). After editing, check the `experiment` column still reads as text
like `2025-01-21` and that mouse IDs are intact, and save as `.csv`, not `.xlsx`.

**On macOS Numbers:** Numbers does not save as CSV by default — it saves a proprietary `.numbers` file the pipeline cannot read. After editing, use **File → Export To → CSV…** and overwrite the original `.csv`. Do NOT use File → Save.
