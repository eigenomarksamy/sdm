import librosa
import eyed3
import os
import pandas as pd

def get_actual_sample_rate(file_path):
    y, sr = librosa.load(file_path)
    return sr

def get_actual_bitrate(file_path):
    audio = eyed3.load(file_path)
    if audio:
        bitrate_info = audio.info.bit_rate
        if bitrate_info:
            return bitrate_info[1]
        else:
            return None
    else:
        return None

def compare_and_report(directory):
    data = []
    for filename in os.listdir(directory):
        if filename.endswith('.mp3'):
            file_path = os.path.join(directory, filename)
            actual_sample_rate = get_actual_sample_rate(file_path)
            actual_bitrate = get_actual_bitrate(file_path)
            audio = eyed3.load(file_path)
            metadata_sample_rate = audio.info.sample_freq if audio else None
            metadata_bitrate = audio.info.bit_rate[1] if audio else None
            sample_rate_diff = actual_sample_rate - metadata_sample_rate
            bitrate_diff = actual_bitrate - metadata_bitrate
            data.append([filename, actual_sample_rate, metadata_sample_rate, sample_rate_diff, actual_bitrate, metadata_bitrate, bitrate_diff])
    df = pd.DataFrame(data, columns=['Filename', 'Actual Sample Rate', 'Metadata Sample Rate', 'Sample Rate Diff', 'Actual Bitrate', 'Metadata Bitrate', 'Bitrate Diff'])
    return df
