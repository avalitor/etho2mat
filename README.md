# etho2mat — Ethovision → `.mat` conversion

Converts Ethovision Excel trial exports into validated `.mat` files (one per trial) for downstream analysis. It is **config-driven**: onboarding a new experiment means filling in CSVs and dropping files in folders.

If something goes wrong, the tool should stop and tell you which file, place, and what it expected. Read the message, fix, and run again.

---

## One-time Setup

A *conda environment* is a private folder of Python libraries this tool needs; creating it once prevents version conflicts with anything else on your computer. You do this once, then forget about it — the launcher activates the environment for you on every run.

1. **Install Miniconda.** Download the installer for your platform from <https://docs.conda.io/en/latest/miniconda.html> (pick the right one: Windows, macOS Intel, or macOS Apple Silicon). Run the installer and accept the defaults.

2. **Open a terminal.**
     - **Windows:** open *Anaconda Prompt* from the Start menu (installed alongside Miniconda).
     - **macOS:** open *Terminal* (Applications → Utilities → Terminal).

3. **Navigate to this project folder.** Use the `cd` command. 
> [!TIP] 
> instead of typing the path, type `cd ` (with a trailing space) and then drag the project folder into the terminal window — the full path is pasted automatically. Then press Enter. 
Example: (your path will differ)
     ```
     cd /Users/yourname/Documents/etho2mat
     ```

4. **Create the environment.** type and press Enter:
     ```
     conda env create -f environment.yml
     ```
   This downloads and installs everything (takes a few minutes). When it finishes you'll see `done`.

5. **Verify it worked:**
     ```
     conda activate traj
     python -c "import cv2; print('ok')"
     ```
   You should see `ok`. The environment is ready.

---

## Quickstart (onboarding one experiment)

1. **Read `CHECKLIST.md`** and prepare what it lists. Items marked *(enforced)* will stop the run if wrong; the rest only warn.

2. **Add data to 3 folders:**
     - `1_raw/`: Export **Ethovision Excel** trials into a folder  `1_raw/EXPDATE_Raw Trial Data/` (the trials must be contained in a folder name that starts with the experiment's start date, e.g. `2025-01-21_Raw Trial Data`).
     - `2_background_images/`: Put one clean **arena screenshot:** in here. If different cohorts of mice used physically different arenas (see *Multiple arenas in one experiment* below), put **one screenshot per arena** here.
     - `3_config/`: Edit 2 files in this folder. First, **Write a new row** to `experiment_list.csv` (double-click to edit; save as CSV — on macOS Numbers, use **File → Export To → CSV…** when done, *not* File → Save). Second, **make a copy** of  `TEMPLATE_targets.csv` and rename to `EXPDATE_targets.csv` and fill in the reward rows. Optional: **Mouse map (only if needed):** edit `mouse_map.csv` only when (a) `mouse_sex = mixed` in `experiment_list.csv`, (b) different mice in this experiment have different strains/conditions you want recorded, or (c) different cohorts of mice ran on different arenas (per-mouse `background_image` / `img_extent` columns). Otherwise leave it alone.

3. **Run** by double-clicking `run_conversion.bat` (Windows) or `run_conversion.command` (Mac). You can also run `python -m src.convert EXPDATE` in the `traj` environment.

The experiment id is always the **start date** `YYYY-MM-DD`, and it should match across the 1_raw folder, `experiment_list.csv`, and `targets/EXPDATE_targets.csv`.

---

## Confirmation Checks

1. **Arena check** — a verification image (the detected circle + holes over your screenshot) opens in `output/verification/EXPDATE_arena.png`, and the tool asks `1 arena and 100 holes — looks right? [y/n]`. Confirm the circle hugs the arena edge and every hole is marked. A wrong hole count stops the run with the likely cause (a food-filled hole was missed, or a wire/reflection was counted as an extra). If the experiment uses **multiple arenas**, you'll see one verification image and one y/n prompt per arena (`EXPDATE_arena_arena_IMAGENAME.png`), and any `n` aborts the whole run.
2. **Alignment check** — `output/verification/EXPDATE_alignment.png` shows one panel per targets rule with a few **well-trained** trajectories and the assigned target. The tool asks `paths reach the marked targets and start from the labelled entrances? [y/n]`. This plot is how you verify the targets are in the right place. If trajectories head to the wrong area, a target or entrance is mislabelled.

If you answer `n` to either, nothing will be written.

---

## After the run: the flagged-trials report

The tool prints, and writes to `output/flagged_trials.csv`, every **reward-expecting** trial whose nose never reached the target, with its closest approach. Read these:

- A near miss (e.g. 2–3 cm) is usually poor tracking.
- A gross miss (tens of cm) is a real miss, a target swap, or — if widespread — misalignment.
- `suspected_nose_tail_swap = True` means the **tail** reached the target but the nose did not; Ethovision likely swapped them. Re-export that trial with the nose tracking corrected.

Habituation and probe trials have no reward, so they are **exempt** from these alarms (configurable per experiment via the `no_reward_trials` column in `experiment_list.csv`; default `Habituation*, Probe*` — the `*` is a prefix wildcard, see *Trial selectors* below).

A high or one-entrance-wide miss rate is reported as a **likely alignment problem** — recheck the alignment image before trusting the output.

---

## Trial selectors: `*` and other shortcuts

Several places in the config (`no_reward_trials` in `experiment_list.csv`, the `trials` column in `targets/EXPDATE_targets.csv`) accept a small *selector* language for picking which trials a rule applies to:

- **`Probe`** — exact trial name. Matches `Probe` only, not `Probe2`.
- **`Probe*`** — `*` is a **prefix wildcard**. Matches `Probe`, `Probe2`, `Probe3`, …. `habit*` matches `habit1`, `habit2`, etc. Case-sensitive: `habit*` does **not** match `Habituation`.
- **`1-20`** or **`1..20`** — inclusive numeric range (digit-named trials only). Use `..` when Excel reformats `1-20` as a date.
- **`1,2,5`** — explicit list of trial numbers.
- **`all`** — every trial.
- **`!Probe*`** — `!` is negation. `1-30, !25` = trials 1–30 except 25.
- **`remaining`** — every trial for the same entrance not claimed by another row.

The comments at the top of `3_config/targets/TEMPLATE_targets.csv` show all of these with worked examples.

---

## When the arena can't be detected

If detection fails, check the diagnostic image located in `output/verification/EXPDATE_arena_[screenshot].png` to see where the failure is happening. If the edges are not well detected, fix the video screenshot. A clear, evenly-lit, fully-in-frame arena with empty holes and no wires/mice/objects is ideal (see `CHECKLIST.md` Arena Screenshot section). Boost contrast and brightness in Photoshop if the lighting isn't great.

---

## Multiple arenas in one experiment

Some experiments run different cohorts on physically different arenas — e.g. mice 1–4 on arena A, mice 5–8 on arena B. The tool handles this through `3_config/mouse_map.csv`: leave the `background_image` and `img_extent` columns blank for mice on the experiment-wide default, and fill them in for mice that ran on a different arena.

What to do:

1. Put one screenshot per arena in `2_background_images/` (e.g. `BKGDimage-20260101_arenaA.png` and `BKGDimage-20260101_arenaB.png`).
2. In `experiment_list.csv`, give the experiment-wide default (`background_image`, `img_extent`) — this is what mice with no override row will use.
3. In `mouse_map.csv`, add one row per mouse that ran on the *other* arena, filling in its `background_image` and `img_extent`. Leave them blank for mice on the default. **Mice not listed in `mouse_map.csv` automatically use the experiment-wide default from `experiment_list.csv`** — only list the mice that need an override.
4. **Target coordinates:** the two arenas usually have shifted targets, so for each arena write a separate set of reward rows in `targets/EXPDATE_targets.csv` and scope each set to its mice via the `mice` column (comma-separated mouse IDs).

Example: in `targets/2026-01-15_targets.csv`, two reward rows for entrance `NW` — one with `mice = 1,2,3,4` and arena-A coordinates, another with `mice = 5,6,7,8` and arena-B coordinates.

During the run, you'll see one arena verification image per distinct arena and one y/n prompt for each (in `output/verification/EXPDATE_arena_[screenshot].png`). After records are built, the tool also prints a **consistency warning** if any target row's `(x, y)` lands outside the arena assigned to its mouse — typically a copy-paste swap between the two arenas' coordinates. The warning never blocks the run; it just calls out the likely mistake so you can confirm via the alignment image.

---

## Where things go

- Inputs: `1_raw/` (Excel), `2_background_images/` (screenshots), `3_config/` (CSVs you edit).
- Outputs: `output/EXPDATE/hfm_EXPDATE_M[mouse]_[trial].mat`, plus `output/verification/` images and `output/flagged_trials.csv`. The contents of `1_raw/`, `2_background_images/`, and `output/` are git-ignored — data is never committed.
- To send `.mat` straight to another directory, repoint `OUTPUT_DIR` in `src/paths.py` (the place paths are defined).

Re-processing an experiment refuses to overwrite by default; re-run with `--force` to overwrite.

---

## Golden Regression Test (only used when changing the code)

`tests/test_golden.py` is the safety net: it re-runs the pipeline on a curated set of fixture trials (Excel inputs + 3 PNGs committed under `tests/fixtures/`) and asserts every produced field matches the expected signature in `tests/fixtures/golden_manifest.json`, except a short allowlist of deliberate fixes (Spec §12). Float fields are compared with a tolerance of 1e-9 so transcendental ULP noise across numpy versions doesn't trigger false alarms.

Run it after any code change to this repo:

```
pytest tests/ -v
```

- **Green** = the output contract is intact.
- **Red** names the exact field and trial that drifted — investigate before shipping.

The test is **self-contained** — it depends only on `tests/fixtures/` + the manifest, nothing else. If you DELIBERATELY change the contract (e.g. add a field, change an encoding), the test will fail until you re-generate the manifest with `python scripts/build_fixtures.py` *and* update the allowlist if the change is on the deliberate list. The point of the warning is to ask "do I really mean this? do downstream consumers and historical data need to be updated too?"

---

## Trial naming and the schema

`mouse_number`, `day`, and `trial` are stored as **strings**. `eth_file` stores the original Ethovision filename. Coordinate arrays are `(N,2)`; `time`/`velocity`/`head_direction`/`heading` are `(1,N)`. `target` is `(K,2)` — a trial with two simultaneously-baited targets stores both. A `schema_version` field marks the contract; new optional fields (`mouse_strain`, `reward_reached`) are safe because the consumer guards them.

---

## What if the config files can't express your protocol design?

If a protocol can't be described with the `targets/` file structure (selectors, per-mouse rows, multiple targets), you need a code developer. This is a deliberate boundary so this tool doesn't get used for templates it isn't designed to handle. 

**Questions? Contact:** Kelly @ kxu013@uottawa.ca
