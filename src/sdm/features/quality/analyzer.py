import os
import json
import eyed3
import subprocess
import pandas as pd
from typing import Tuple

def compute_audio_properties(file_path: os.PathLike) -> Tuple[float, float]:
    command = [
        "ffprobe",
        "-v", "error",
        "-show_entries",
        "stream=sample_rate,duration",
        "-of", "json",
        file_path,
    ]
    result = subprocess.run(command, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    data = result.stdout
    details = json.loads(data)
    stream = details["streams"][0]
    duration = float(stream["duration"])
    sample_rate = int(stream["sample_rate"])
    command_pcm = [
        "ffmpeg",
        "-i", file_path,
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ar", str(sample_rate),
        "-ac", "2",
        "-",
    ]
    process = subprocess.Popen(command_pcm, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL)
    raw_audio_data = process.stdout.read()
    process.stdout.close()
    process.wait()
    raw_audio_size = len(raw_audio_data)
    actual_bitrate = (raw_audio_size * 8) / duration

    return sample_rate, actual_bitrate

def compare_and_report(directory: os.PathLike):
    data = []
    for filename in os.listdir(directory):
        if filename.endswith('.mp3'):
            file_path = os.path.join(directory, filename)
            actual_sample_rate, actual_bitrate = \
                compute_audio_properties(file_path)
            audio = eyed3.load(file_path)
            metadata_sample_rate = audio.info.sample_freq if audio else None
            metadata_bitrate = audio.info.bit_rate[1] if audio else None
            sample_rate_diff = actual_sample_rate - metadata_sample_rate
            bitrate_diff = actual_bitrate - metadata_bitrate
            data.append([filename, actual_sample_rate,
                         metadata_sample_rate, sample_rate_diff,
                         actual_bitrate, metadata_bitrate,
                         bitrate_diff])
    df = pd.DataFrame(data, columns=['Filename', 'Actual Sample Rate',
                                     'Metadata Sample Rate', 'Sample Rate Diff',
                                     'Actual Bitrate', 'Metadata Bitrate',
                                     'Bitrate Diff'])
    return df
