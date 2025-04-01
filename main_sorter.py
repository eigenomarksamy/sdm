import os
import csv
import argparse
import eyed3
import datetime

def format_duration(seconds):
    if isinstance(seconds, (int, float)):
        minutes = int(seconds) // 60
        seconds = int(seconds) % 60
        return f"{minutes:02}:{seconds:02}"
    return "Unknown"

def list_mp3_files(directory, output_csv):
    with open(output_csv, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["#", "File Path", "File Name", "Size (MBs)", "Last Modified", "Title", "Artist", "Duration (mm:ss)", "Genre"])
        count = 0
        for root, _, files in os.walk(directory):
            for filename in files:
                if filename.lower().endswith(".mp3"):
                    filepath = os.path.join(root, filename)
                    size = os.path.getsize(filepath) / 1024 / 1024
                    last_modified = datetime.datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M:%S')
                    audiofile = eyed3.load(filepath)
                    if audiofile and audiofile.tag:
                        title = audiofile.tag.title if audiofile.tag.title else "Unknown"
                        artist = audiofile.tag.artist if audiofile.tag.artist else "Unknown"
                        genre = audiofile.tag.genre.name if audiofile.tag.genre else "Unknown"
                    else:
                        title, artist, genre = "Unknown", "Unknown", "Unknown"
                    duration = format_duration(audiofile.info.time_secs) if audiofile and audiofile.info and audiofile.info.time_secs else "Unknown"
                    count += 1
                    writer.writerow([count, filepath, filename, size, last_modified, title, artist, duration, genre])

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="List all MP3 files in a directory and its subdirectories in a CSV file with metadata.")
    parser.add_argument("directory", help="Path to the directory")
    parser.add_argument("output_csv", help="Output CSV file name")
    args = parser.parse_args()
    
    list_mp3_files(args.directory, args.output_csv)
    print(f"MP3 file list saved to {args.output_csv}")