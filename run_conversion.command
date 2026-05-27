#!/bin/bash
# Double-click to run the guided conversion (macOS / Linux).
# Activates the `traj` conda environment, then runs the tool. Loops on the
# experiment-id prompt so several experiments can be processed without
# re-activating, matching run_conversion.bat.

# Remove the macOS Gatekeeper quarantine flag from this script so future
# double-clicks don't re-trigger the "downloaded from the internet" prompt.
# Silent no-op on Linux or when not quarantined.
xattr -d com.apple.quarantine "$0" 2>/dev/null || true

cd "$(dirname "$0")" || exit 1

# --- Try to activate the `traj` conda environment -------------------------
# Make `conda activate` available in this non-interactive shell.
ACTIVATED=0
for base in "$HOME/miniconda3" "$HOME/anaconda3" "/opt/miniconda3" "/opt/anaconda3"; do
  if [ -f "$base/etc/profile.d/conda.sh" ]; then
    # shellcheck disable=SC1091
    source "$base/etc/profile.d/conda.sh"
    if conda activate traj 2>/dev/null; then
      ACTIVATED=1
    fi
    break
  fi
done

# --- Fallback: use whatever Python is on PATH if it has the packages ------
WARN_UNVERIFIED=0
if [ "$ACTIVATED" -eq 0 ]; then
  if command -v python >/dev/null 2>&1 && \
     python -c "import numpy, scipy, pandas, openpyxl, cv2, matplotlib" 2>/dev/null; then
    WARN_UNVERIFIED=1
  else
    echo
    echo "Could not activate the 'traj' conda environment, and the active"
    echo "Python is missing required packages."
    echo
    echo "One-time setup:"
    echo "  1. Install Miniconda:  https://docs.conda.io/en/latest/miniconda.html"
    echo "  2. From a terminal in this folder, run:"
    echo "        conda env create -f environment.yml"
    echo "  3. Double-click this file again."
    echo
    read -r -p "Press Enter to close."
    exit 1
  fi
fi

# --- Main loop -------------------------------------------------------------
while true; do
  if [ "$WARN_UNVERIFIED" -eq 1 ]; then
    echo
    echo "WARNING: 'traj' env not found; using the active Python."
    echo "Arena detection may differ slightly (OpenCV version drift)."
    echo "Setup: conda env create -f environment.yml"
    echo
  fi

  read -r -p "Enter the experiment id (start date, e.g. 2025-01-21): " EXPERIMENT
  python -m src.convert "$EXPERIMENT" "$@"

  echo
  read -r -p "Process another experiment? [y/n] " AGAIN
  case "$AGAIN" in
    [Yy]*) continue ;;
    *) break ;;
  esac
done

exit 0
