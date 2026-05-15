import os
import csv
import eyed3


def list_mp3_files(
    directory,
    output_csv
):
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
                "filepath": filepath,
                "filename": filename,
                "title": title,
                "artist": artist
            })

    with open(output_csv, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["#", "filepath", "filename", "track name", "artist"])

        for index, row in enumerate(rows, start=1):
            writer.writerow([
                index,
                row["filepath"],
                row["filename"],
                row["title"],
                row["artist"]
            ])

    return {
        "tracks_written": len(rows),
        "metadata_errors": errors
    }


def validate_mp3_csv(directory, csv_path):
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

    with open(csv_path, mode="r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            filepath = os.path.abspath(row["filepath"])

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

FOLDER_NAME = "postmodern"

directory = fr"C:\Users\omark\Music\{FOLDER_NAME}"
output_csv = f"./mp3_file_list_{FOLDER_NAME}.csv"

export_result = list_mp3_files(directory, output_csv)

validation = validate_mp3_csv(directory, output_csv)

print(export_result)
print(validation)