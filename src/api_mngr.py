import os
import re
import urllib
import logging
import requests
from typing import Tuple
from dataclasses import dataclass
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, error
from src.cfg_mngr import Cfg
from src.dir_mngr import (check_existing_files, remove_empty_files,
                             resolve_path, get_unique_name_of_folder)

@dataclass(init=True, eq=True, frozen=True)
class Song:
    title: str
    artists: str
    album: str
    cover: str
    link: str

class SpotifyDownloadManager:

    CUSTOM_HEADER = {
    'Host': 'api.spotifydown.com',
    'Referer': 'https://spotifydown.com/',
    'Origin': 'https://spotifydown.com',
    }
    DOWNLOAD_API = "https://api.spotifydown.com/download/"
    TRACK_NAME_REGEX = re.compile(r"[<>:\"/\\|?*\x00-\x1F\x7F\u2000-\u206F\u2190-\u21FF\u2600-\u26FF]")

    def __init__(self, naming_convention: Cfg.NamingConventions,
                 output_directory: os.PathLike) -> None:
        self.tn_convention = naming_convention
        self.output_directory = output_directory

def check_existing_tracks(song_list_dict: dict,
                          output_directory: os.PathLike) -> dict:
    return check_existing_files(song_list_dict, output_directory, "mp3")

def sanitize_track_id(track_id: str) -> str:
    track_id = re.sub(r'[<>:"/\\|?*]', '', track_id)
    return track_id

def get_track_info(link: str) -> any:
    track_id = link.split("/")[-1].split("?")[0]
    track_id = sanitize_track_id(track_id)
    track_id = urllib.parse.quote(track_id)
    response = requests.get(f"{SpotifyDownloadManager.DOWNLOAD_API}{track_id}",
                            headers=SpotifyDownloadManager.CUSTOM_HEADER)
    if response.status_code != 200:
        print(f"HTTP Response Code: {response.status_code}")
        return {'success': False, 'message': f"HTTP {response.status_code}: Error occurred"}
    response_json = response.json()
    return response_json

def create_unique_dict(song_list: list[Song], tnc: Cfg.NamingConventions) -> Tuple[dict, list]:
    unique_songs = {}
    duplicate_songs = []
    for song in song_list:
        tn = f"{song.title} - {song.artists}"
        if tnc == Cfg.NamingConventions.ARTIST_TRACK:
            tn = f"{song.artists} - {song.title}"
        if (unique_songs.get(tn)):
            duplicate_songs.append(tn)
        else:
            unique_songs.setdefault(tn, song)
    return unique_songs, duplicate_songs

def make_unique_song_objects(track_list: list[dict],
                             tn_con: Cfg.NamingConventions) -> dict:
    song_list = []
    for track in track_list:
        if 'cover' in track:
            song_list.append(
                Song(
                    title=re.sub(SpotifyDownloadManager.TRACK_NAME_REGEX, "_", track['title']),
                    artists=re.sub(SpotifyDownloadManager.TRACK_NAME_REGEX, "_", track['artists']),
                    album=track['album'],
                    cover=track['cover'],
                    link=f"https://open.spotify.com/track/{track['id']}"
                )
            )
        else:
            song_list.append(
                Song(
                    title=re.sub(SpotifyDownloadManager.TRACK_NAME_REGEX, "_", track['title']),
                    artists=re.sub(SpotifyDownloadManager.TRACK_NAME_REGEX, "_", track['artists']),
                    album=track['album'],
                    cover=None,
                    link=f"https://open.spotify.com/track/{track['id']}"
                )
            )
    unique_songs, duplicate_songs = create_unique_dict(song_list, tn_con)
    if (len(duplicate_songs)):
        print("\tDuplicate songs: ", len(duplicate_songs))
        for index, song_name in enumerate(duplicate_songs, 1):
            print(f"\t\t{index}: {song_name}")
    print("\n\tUnique Songs in playlist: ", len(unique_songs))
    for index, song_name in enumerate(unique_songs.keys(), 1):
        print(f"\t\t{index}: {song_name}")
    return unique_songs

def get_playlist_info(link: str, nc: Cfg.NamingConventions) -> Tuple[dict, str]:
    playlist_id = link.split("/")[-1].split("?")[0]
    response = requests.get(f"https://api.spotifydown.com/metadata/playlist/{playlist_id}",
                            headers=SpotifyDownloadManager.CUSTOM_HEADER)
    response = response.json()
    playlist_name = response['title']
    if response['success']:
        print("-" * 40)
        print(f"Name: {playlist_name} by {response['artists']}")
    print("Getting songs from playlist (this might take a while ...)")
    track_list = []
    response = requests.get(f"https://api.spotifydown.com/tracklist/playlist/{playlist_id}",
                            headers=SpotifyDownloadManager.CUSTOM_HEADER)
    response = response.json()
    track_list.extend(response['trackList'])
    next_offset = response['nextOffset']
    while next_offset:
        response = requests.get(f"https://api.spotifydown.com/tracklist/playlist/{playlist_id}?offset={next_offset}",
                                headers=SpotifyDownloadManager.CUSTOM_HEADER)
        response = response.json()
        track_list.extend(response['trackList'])
        next_offset = response['nextOffset']
    song_list_dict = make_unique_song_objects(track_list, nc)
    return song_list_dict, playlist_name

def save_audio(track_name: str, link, output_path: os.PathLike) -> bool:
    track_name = re.sub(SpotifyDownloadManager.TRACK_NAME_REGEX, "_", track_name)
    if os.path.exists(os.path.join(output_path, f"{track_name}.mp3")):
        logging.info(f"{track_name} already exists in the directory ({output_path}). "
                    "Skipping download!")
        print("\t This track already exists in the directory. Skipping download!")
        return False
    audio_response = requests.get(link, timeout=10)
    if audio_response.status_code == 200:
        with open(os.path.join(output_path, f"{track_name}.mp3"), "wb") as file:
            file.write(audio_response.content)
        return True

def add_metadata(track_name: str, cover_art: bytes,
                 output_path: os.PathLike) -> None:
    track_name = re.sub(SpotifyDownloadManager.TRACK_NAME_REGEX, "_", track_name)
    filepath = os.path.join(output_path, f"{track_name}.mp3")
    try:
        audio = MP3(filepath, ID3=ID3)
    except error as e:
        logging.error(f"Error loading MP3 file from {filepath} --> {e}")
        print(f"\t Error loading MP3 file --> {e}")
        return
    if audio.tags is None:
        try:
            audio.add_tags()
        except error as e:
            logging.error(f"Error adding ID3 tags to {filepath} --> {e}")
            print(f"\tError adding ID3 tags --> {e}")
            return 
    audio.tags.add(
        APIC(
            encoding=1,
            mime='image/jpeg',
            type=3,
            desc=u'Cover',
            data=cover_art)
        )
    audio.save(filepath, v2_version=3, v1=2)

def download_track(track_link: str, cfg: Cfg) -> bool:
    ret_flag = True
    if not cfg.quiet:
        print("\nTrack link identified")
    resp = get_track_info(track_link)
    if resp['success'] == False:
        if not cfg.quiet:
            print(f"Error: {resp['message']}")
        if not cfg.disable_log:
            logging.error(f"Error: {resp['message']}")
        ret = {'status': 1,
               'details': f"Error: {resp['message']}"}
        return False
    track_name = f"{resp['metadata']['title']} - {resp['metadata']['artists']}"
    if cfg.naming_convention == Cfg.NamingConventions.ARTIST_TRACK:
        track_name = f"{resp['metadata']['artists']} - {resp['metadata']['title']}"
    if not cfg.quiet:
        print(f"\nDownloading {track_name} to ({cfg.directory})")
    for attempt in range(cfg.max_attempts):
        ret_flag = True
        try:
            save_status = save_audio(track_name, resp['link'], cfg.directory)
            if save_status:
                cover_art = requests.get(resp['metadata']['cover']).content
                add_metadata(track_name, cover_art, cfg.directory)
            break
        except Exception as e:
            if not cfg.disable_log:
                logging.error(f"Attempt {attempt+1} - {track_name} --> {e}")
            if not cfg.quiet:
                print(f"\tAttempt {attempt+1} failed with error: ", e)
                ret = {'status': 1,
                       'details': f"Attempt {attempt+1} - {track_name} --> {e}"}
            ret_flag = False
    remove_empty_files(cfg.directory)
    return ret_flag

def download_playlist_tracks(playlist_link: str, cfg: Cfg) -> dict:
    ret_dict = {}
    print("\nPlaylist link identified")
    song_list_dict, playlist_name = get_playlist_info(playlist_link,
                                                      cfg.naming_convention)
    print(playlist_name)
    valid_name = True
    for c in playlist_name:
        valid_name &= True if c.isalnum() or c == " " else False
    if not valid_name:
        playlist_name = get_unique_name_of_folder(cfg.directory)
    if cfg.create_pl_folder == True:
        output_path = os.path.join(cfg.directory, playlist_name)
    if os.path.exists(output_path):
        song_list_dict = check_existing_tracks(song_list_dict, output_path)
    if not song_list_dict:
        print(f"\nAll tracks from {playlist_name} already exist "
              f"in the directory ({output_path}).")
        return
    resolve_path(output_path, create_pl_folder=True)
    cfg.directory = output_path
    print(f"\nDownloading {len(song_list_dict)} new track(s) "
          f"from {playlist_name} to ({output_path})")
    print("-" * 40 )
    for index, tn in enumerate(song_list_dict.keys(), 1):
        ret_dict[tn] = download_track(song_list_dict[tn].link, cfg)
        print(f"{index}/{len(song_list_dict)}: {tn} -- Status: {ret_dict[tn]}")
    remove_empty_files(output_path)
    return ret_dict
