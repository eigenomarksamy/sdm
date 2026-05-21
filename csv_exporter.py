import re
import os
import csv
import eyed3
import argparse
import unicodedata
from collections import defaultdict


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

            title = "Unknown"
            artist = "Unknown"

            try:
                audiofile = eyed3.load(filepath)

                if audiofile and audiofile.tag:
                    title = audiofile.tag.title or "Unknown"
                    artist = audiofile.tag.artist or "Unknown"

            except Exception as e:
                errors.append({
                    "filepath": filepath,
                    "error": str(e)
                })

            rows.append({
                "filename": filename,
                "title": title,
                "artist": artist
            })

            rows_x_val.append({"filepath": filepath})

    with open(output_csv, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["#",
                         "filename",
                         "track name",
                         "artist"])

        for index, row in enumerate(rows, start=1):
            writer.writerow([
                index,
                row["filename"],
                row["title"],
                row["artist"]
            ])

    with open(x_val_path, mode="w", newline="", encoding="utf-8") as file:
        for row in rows_x_val:
            file.write(f"{row['filepath']}\n")

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
    files_from_txt = []

    with open(txt_path, "r", encoding="utf-8") as file:
        files_from_txt = [line.rstrip("\n") for line in file]

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
    MIX_SUFFIXES = [
        "original mix",
        # add more later if needed:
        # "extended mix",
        # "club mix",
        # "radio edit",
        # "dub mix",
    ]


    def normalize_text(value):
        value = value or ""
        value = unicodedata.normalize("NFKC", value)
        value = value.casefold()
        value = re.sub(r"\s+", " ", value)
        return value.strip()


    def normalize_title(title):
        title = normalize_text(title)

        suffix_pattern = "|".join(re.escape(suffix) for suffix in MIX_SUFFIXES)

        patterns = [
            # Track Name (Original Mix)
            rf"\s*[\(\[\{{]\s*({suffix_pattern})\s*[\)\]\}}]\s*$",

            # Track Name - Original Mix
            rf"\s*[-–—]\s*({suffix_pattern})\s*$",
        ]

        changed = True
        while changed:
            old_title = title

            for pattern in patterns:
                title = re.sub(pattern, "", title, flags=re.IGNORECASE)

            title = re.sub(r"\s+", " ", title).strip()

            changed = title != old_title

        return title


    def make_track_key(row):
        title = normalize_title(row.get("track name", ""))
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

parser = argparse.ArgumentParser()
parser.add_argument("directory")
parser.add_argument("--output-csv", default=None)
args = parser.parse_args()

directory = args.directory
folder_name = os.path.basename(os.path.normpath(directory))
output_csv = args.output_csv or f"./mp3_file_list_{folder_name}.csv"
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