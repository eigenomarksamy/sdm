# legacy

Superseded code, kept for reference. Nothing here is imported by `sdm`, and
none of it is expected to run against the current layout.

- `main_sorter.py` — the first version of the catalog exporter. Hardcoded to one
  folder (`FOLDER_NAME`), argparse commented out, no cross-validation. Replaced
  by `sdm catalog` (`src/sdm/features/catalog/`).

The untracked `deprecated/` folder at the repo root holds older entry points
still and is gitignored.
