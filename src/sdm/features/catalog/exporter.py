"""Catalog a folder of MP3s into an auditable CSV.

"Auditable" is the point: alongside the CSV the export writes a sidecar listing
every file path it visited, then re-walks the directory and set-diffs the two.
A clean run proves nothing was missed, dropped, or invented.
"""
import csv
import os
from collections import defaultdict

from sdm.core.report import read_lines, write_csv, write_lines
from sdm.core.tags import read_basic_tags
from sdm.core.text import normalize_loose, normalize_text


def list_mp3_files(
    directory,
    output_csv,
    x_val_path
):

    rows_x_val = []
    rows = []
    errors = []

    for root, _, files in os.walk(directory):
        for filename in files:
            if not filename.lower().endswith(".mp3"):
                continue

            filepath = os.path.join(root, filename)

            title, artist, error = read_basic_tags(filepath)

            if error is not None:
                errors.append({
                    "filepath": filepath,
                    "error": error
                })

            rows.append({
                "filename": filename,
                "title": title,
                "artist": artist
            })

            rows_x_val.append({"filepath": filepath})

    write_csv(
        output_csv,
        ["#", "filename", "track name", "artist"],
        (
            [index, row["filename"], row["title"], row["artist"]]
            for index, row in enumerate(rows, start=1)
        ),
    )

    write_lines(x_val_path, (row["filepath"] for row in rows_x_val))

    return {
        "tracks_written": len(rows),
        "metadata_errors": errors
    }


def validate_mp3_csv(directory, txt_path):
    # All actual MP3 files in the directory
    actual_files = set()

    for root, _, files in os.walk(directory):
        for filename in files:
            if filename.lower().endswith(".mp3"):
                filepath = os.path.abspath(os.path.join(root, filename))
                actual_files.add(filepath)

    # All MP3 files recorded in the CSV
    csv_files = set()
    duplicate_csv_entries = []

    files_from_txt = read_lines(txt_path)

    for filepath in files_from_txt:
        if filepath in csv_files:
            duplicate_csv_entries.append(filepath)
        csv_files.add(filepath)

    missing_from_csv = actual_files - csv_files
    extra_in_csv = csv_files - actual_files

    result = {
        "actual_mp3_count": len(actual_files),
        "csv_mp3_count": len(csv_files),
        "missing_from_csv_count": len(missing_from_csv),
        "extra_in_csv_count": len(extra_in_csv),
        "duplicate_csv_entries_count": len(duplicate_csv_entries),
        "missing_from_csv": sorted(missing_from_csv),
        "extra_in_csv": sorted(extra_in_csv),
        "duplicate_csv_entries": sorted(duplicate_csv_entries),
        "is_valid": (
            len(missing_from_csv) == 0
            and len(extra_in_csv) == 0
            and len(duplicate_csv_entries) == 0
        )
    }

    return result


def find_repeated(csv_path):
    """Group rows of the exported CSV that normalize to the same (title, artist).

    Uses the loose normalizer, so "Track (Original Mix)" and "Track" collapse
    together — see `sdm.core.text` for why this feature wants that and the
    Rekordbox one does not.
    """

    def make_track_key(row):
        title = normalize_loose(row.get("track name", ""))
        artist = normalize_text(row.get("artist", ""))

        return title, artist

    seen = {}
    duplicates = defaultdict(list)

    with open(csv_path, mode="r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for line_number, row in enumerate(reader, start=2):
            key = make_track_key(row)

            entry = {
                "line": line_number,
                "track name": row.get("track name", ""),
                "artist": row.get("artist", ""),
                "normalized key": key,
            }

            if key in seen:
                if not duplicates[key]:
                    duplicates[key].append(seen[key])

                duplicates[key].append(entry)
            else:
                seen[key] = entry

    return dict(duplicates)


def run(directory, output_csv=None):
    """Export, then report duplicates, then cross-validate. Returns an exit code."""
    folder_name = os.path.basename(os.path.normpath(directory))
    output_csv = output_csv or f"./mp3_file_list_{folder_name}.csv"
    x_val_path = os.path.splitext(output_csv)[0] + "_x_val.txt"

    export_result = list_mp3_files(directory, output_csv, x_val_path)
    find_repeated_result = find_repeated(output_csv)

    validation = validate_mp3_csv(directory, x_val_path)

    print(export_result)
    if len(find_repeated_result) == 0:
        print("No potential duplicates found.")
    else:
        for i in find_repeated_result:
            print(i)
    print(validation)

    return 0
