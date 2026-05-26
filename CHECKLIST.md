# Data Preparation Checklist

Use this checklist to prepare your experiment's data for processing into `.mat` files. 

`(enforced)` marks items the pipeline checks and will stop on if they are wrong. Unmarked items
will not block the pipeline — some it will warn about — and the final say is yours.

---

## Checklist

- [ ] Experiment is named as its start date, `YYYY-MM-DD`. No other experiment should share the same date. 
- [ ] In Ethovision, check each trial's nose point tracks correctly and sits on the target before export & trials follow the naming convention (see Trial Naming and Numbering). 
- [ ] In Ethovision, get the target coordinates per entrance. 
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
- Number repeats with a space: `Habituation 1`, `Habituation 2`, not `habit1`. A single one is
  just `Habituation`.
- Do not abbreviate: `Habituation`, not `Habit`.

The tool warns when names deviate, but does not stop you. So `habit1`, `habit2` is allowed — your
downstream analysis just needs a selector that matches them (e.g. `habit*`) instead of `Habituation*`.

Essential:
- **Number trials sequentially, including around named trials: `1, 2, 3, Probe, 4, 5`.** A skipped number usually means a trial is mis-numbered or missing, so the tool flags it prominently — you can still proceed if the gap is intentional.
- **No two trials for the same mouse can share a name** — they would write to the same output file and overwrite each other. *(enforced)*

### Target coordinates

- Record each target by its entrance: `NW entrance -> reward at (x, y)`. Get coordinates by mousing over the target in the Ethovision Arena Setup tab.
- Anchor on the entrance, not the mouse. If a mouse's target changes, still give the per-entrance coordinates.
- No target at `(0, 0)`; it is treated as missing. *(enforced)*

### Entrance codes

- Recommended set: `NW`, `SW`, `SE`, `NE`. The labels must match what you recorded in Ethovision. *(enforced: must match)*
- They are room directions, not camera directions. The `NW` entrance might not be the top-left of the image. That is ok as long as it is consistent within the experiment.


## 2. Arena screenshot
- Open a trial video in VLC, scroll to when the arena is clear, and take a snapshot using `Video --> Take Snapshot`. The image should be saved in your Pictures folder. Rename the image with the experiment name and place it in the `2_background_images/` folder.
- Pick a video near the **middle** of the experiment, preferably the Probe; the arena can drift slightly as the experiment runs if you accidentally bumped it. 
- Arena clear, fully in frame, evenly lit. Nothing else in the arena — no wires, mice, or objects; these can be counted as extra holes.
- All holes empty and visible; a food-filled hole can be missed.
- Boost brightness contrast if needed (e.g. in Photoshop) so the edge and holes stand out.
- If you can't get a clear image, get the best image you can and edit out the obstructions (e.g in Photoshop).
- Must yield exactly one arena and 100 holes. *(enforced)*


## 3. Info for the CSV files

### Experiment description
Free text in `experiment_list.csv`. Include:

- The protocol setup.
- When shifts occur — e.g. the target changes after trial 20, or a probe runs after trial 30.
- Special trial conditions — opto, lights out, barriers — and a brief note on any specially-named trials.
- Mouse sex: goes in its own column. Set `mouse_sex = mixed` if the cohort has both sexes, then add one row per mouse to `3_config/mouse_map.csv` (REQUIRED whenever sex is `mixed`).
- Mouse strain/condition (e.g. `WT`, `ATRX-KO`): (optional), leave the column blank if not relevant, set it experiment-wide if all mice share a strain, or per-mouse overrides go in `3_config/mouse_map.csv` if it varies (WT vs KO).


CSVs open in Excel, Numbers, or LibreOffice, which may automatically reformat entries (dates, leading
zeros, scientific notation). After editing, check the `experiment` column still reads as text
like `2025-01-21` and that mouse IDs are intact, and save as `.csv`, not `.xlsx`.
