#!/bin/bash
# Double-click to run the guided conversion (macOS / Linux).
# Activates the `traj` conda environment, then runs the tool.
cd "$(dirname "$0")" || exit 1

# Make `conda activate` available in this non-interactive shell.
for base in "$HOME/miniconda3" "$HOME/anaconda3" "/opt/miniconda3" "/opt/anaconda3"; do
  if [ -f "$base/etc/profile.d/conda.sh" ]; then
    # shellcheck disable=SC1091
    source "$base/etc/profile.d/conda.sh"
    break
  fi
done

if ! conda activate traj 2>/dev/null; then
  echo
  echo "Could not activate the 'traj' conda environment."
  echo "One-time setup:  conda env create -f environment.yml"
  echo
  read -r -p "Press Enter to close."
  exit 1
fi

read -r -p "Enter the experiment id (start date, e.g. 2025-01-21): " EXPERIMENT
python -m src.convert "$EXPERIMENT" "$@"

echo
read -r -p "Press Enter to close."
