import os
import re
import logging
import requests
import argparse
from typing import Tuple
from dataclasses import dataclass
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, error

CUSTOM_HEADER = {
    'Host': 'api.spotifydown.com',
    'Referer': 'https://spotifydown.com/',
    'Origin': 'https://spotifydown.com',
}
TRACKNAME_REGEX = re.compile(r"[<>:\"\/\\|?*]")

@dataclass(init=True, eq=True, frozen=True)
class Song:
    title: str
    artists: str
    album: str
    cover: str
    link: str

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CLI Program to download track from Spotify.")
    parser.add_argument("--link", "-l", nargs="+", dest='link',
                        help="URL of the spotify track or playlist.")
    parser.add_argument("--output", "-o", nargs="?", default=os.getcwd(),
                        help="Path to save the downloaded track(s).")
    parser.add_argument("--sync", "-s", nargs="?", const="sync.json",
                        help="Path of sync.json file to sync local playlists "
                             "folders with Spotify playlists.")
    parser.add_argument("--folder", nargs="?", default=True, dest='destination',
                        help="Create a folder for the playlist "
                             "(default: True).")
    parser.add_argument('--tf', action='store_true', dest='track_name_convention',
                        help='Select naming convention (default: Artist - Track).')
    return parser.parse_args()

def resolve_path(output_path: os.PathLike,
                 create_playlist_folder: bool = False) -> None:
    if not os.path.exists(output_path):
        if not create_playlist_folder:
            user_create_folder = input(
                "Directory specified does not exist. "
                "Do you want to create it? (y/n): ")
        if create_playlist_folder or user_create_folder.lower() == "y":
            os.makedirs(output_path)
        else:
            print("Exiting program.")
            exit()

def create_unique_dict(song_list: list,
                       track_name_convention: int) -> Tuple[dict, list]:
    unique_songs = {}
    duplicate_songs = []
    for song in song_list:
        trackname = f"{song.title} - {song.artists}"
        if track_name_convention == 2:
            trackname = f"{song.artists} - {song.title}"
        if (unique_songs.get(trackname)):
            duplicate_songs.append(trackname)
        else:
            unique_songs.setdefault(trackname, song)
    return unique_songs, duplicate_songs

def make_unique_song_objects(track_list: list,
                             track_name_convention: int) -> dict:
    song_list = []
    for track in track_list:
        song_list.append(
            Song(
                title=re.sub(TRACKNAME_REGEX, "_", track['title']),
                artists=re.sub(TRACKNAME_REGEX, "_", track['artists']),
                album=track['album'],
                cover=track['cover'],
                link=f"https://open.spotify.com/track/{track['id']}"
            )
        )
    unique_songs, duplicate_songs = create_unique_dict(song_list,
                                                       track_name_convention)
    if (len(duplicate_songs)):
        print("\tDuplicate songs: ", len(duplicate_songs))
        for index, song_name in enumerate(duplicate_songs, 1):
            print(f"\t\t{index}: {song_name}")
    print("\n\tUnique Songs in playlist: ", len(unique_songs))
    for index, song_name in enumerate(unique_songs.keys(), 1):
        print(f"\t\t{index}: {song_name}")
    return unique_songs

def check_existing_tracks(song_list_dict: dict, output_path: os.PathLike) -> dict:
    existing_tracks = os.listdir(output_path)
    for track in existing_tracks:
        if track.endswith(".mp3"):
            track = track.split(".mp3")[0]
            if song_list_dict.get(track):
                song_list_dict.pop(track)
    return song_list_dict

def  get_track_info(link: str) -> any:
    track_id = link.split("/")[-1].split("?")[0]
    response = requests.get(f"https://api.spotifydown.com/download/{track_id}",
                            headers=CUSTOM_HEADER)
    response = response.json()
    return response

def get_playlist_info(link: str, track_name_convention: int) -> Tuple[dict, str]:
    playlist_id = link.split("/")[-1].split("?")[0]
    response = requests.get(f"https://api.spotifydown.com/metadata/playlist/{playlist_id}", headers=CUSTOM_HEADER)
    response = response.json()
    playlist_name = response['title']
    if response['success']:
        print("-" * 40)
        print(f"Name: {playlist_name} by {response['artists']}")
    print("Getting songs from playlist (this might take a while ...)")
    track_list = []
    response = requests.get(f"https://api.spotifydown.com/tracklist/playlist/{playlist_id}", headers=CUSTOM_HEADER)
    response = response.json()
    track_list.extend(response['trackList'])
    next_offset = response['nextOffset']
    while next_offset:
        response = requests.get(f"https://api.spotifydown.com/tracklist/playlist/{playlist_id}?offset={next_offset}", headers=CUSTOM_HEADER)
        response = response.json()
        track_list.extend(response['trackList'])
        next_offset = response['nextOffset']
    song_list_dict = make_unique_song_objects(track_list, track_name_convention)
    return song_list_dict, playlist_name

def save_audio(track_name: str, link, output_path: os.PathLike) -> bool:
    track_name = re.sub(TRACKNAME_REGEX, "_", track_name)
    if os.path.exists(os.path.join(output_path, f"{track_name}.mp3")):
        logging.info(f"{track_name} already exists in the directory ({output_path}). "
                     "Skipping download!")
        print("\t This track already exists in the directory. Skipping download!")
        return False
    audio_response = requests.get(link)
    if audio_response.status_code == 200:
        with open(os.path.join(output_path, f"{track_name}.mp3"), "wb") as file:
            file.write(audio_response.content)
        return True

def attach_cover_art(track_name: str, cover_art: bytes,
                     output_path: os.PathLike) -> None:
    track_name = re.sub(TRACKNAME_REGEX, "_", track_name)
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

def remove_empty_files(output_path: os.PathLike) -> None:
    for file in os.listdir(output_path):
        if os.path.getsize(os.path.join(output_path, file)) == 0:
            os.remove(os.path.join(output_path, file))

def download_track(track_link: str, output_path: os.PathLike,
                   track_name_convention: int, max_attempts: int = 3) -> None:
    print("\nTrack link identified")
    resp = get_track_info(track_link)
    if resp['success'] == False:
        print(f"Error: {resp['message']}")
        logging.error(f"Error: {resp['message']}")
        return
    track_name = f"{resp['metadata']['title']} - {resp['metadata']['artists']}"
    if track_name_convention == 2:
        track_name = f"{resp['metadata']['artists']} - {resp['metadata']['title']}"
    print(f"\nDownloading {track_name} to ({output_path})")
    for attempt in range(max_attempts):
        try:
            save_status = save_audio(track_name, resp['link'], output_path)
            if save_status:
                cover_art = requests.get(resp['metadata']['cover']).content
                attach_cover_art(track_name, cover_art, output_path)
            break
        except Exception as e:
            logging.error(f"Attempt {attempt+1} - {track_name} --> {e}")
            print(f"\tAttempt {attempt+1} failed with error: ", e)
    remove_empty_files(output_path)

def download_playlist_tracks(playlist_link: str, output_path: os.PathLike,
                             create_folder: bool, track_name_convention: int,
                             max_attempts: int = 3) -> None:
    print("\nPlaylist link identified")
    song_list_dict, playlist_name = get_playlist_info(playlist_link,
                                                      track_name_convention)
    if create_folder == True:
        output_path = os.path.join(output_path, playlist_name)
    if os.path.exists(output_path):
        song_list_dict = check_existing_tracks(song_list_dict, output_path)
    if not song_list_dict:
        print(f"\nAll tracks from {playlist_name} already exist "
              f"in the directory ({output_path}).")
        return
    print(f"\nDownloading {len(song_list_dict)} new track(s) "
          f"from {playlist_name} to ({output_path})")
    print("-" * 40 )
    for index, trackname in enumerate(song_list_dict.keys(), 1):
        print(f"{index}/{len(song_list_dict)}: {trackname}")
        for attempt in range(max_attempts):
            try:
                resp = get_track_info(song_list_dict[trackname].link)
                resolve_path(output_path, playlist_folder=True)
                save_status = save_audio(trackname, resp['link'], output_path)
                if save_status:
                    cover_art = requests.get(song_list_dict[trackname].cover).content
                    attach_cover_art(trackname, cover_art, output_path)
                    break
            except Exception as e:
                logging.error(f"Attempt {attempt+1} - {playlist_name}: {trackname} --> {e}")
                print(f"\t\tAttempt {attempt+1} failed with error: ", e)
    remove_empty_files(output_path)

def check_track_playlist(link: str, output_path: os.PathLike,
                         create_folder: bool,
                         track_name_convention: bool) -> None:
    explicit_name_convention = 2
    if track_name_convention:
        explicit_name_convention = 1
    resolve_path(output_path)
    if re.search(r".*spotify\.com\/track\/", link):
        download_track(link, output_path, explicit_name_convention)
    elif re.search(r".*spotify\.com\/playlist\/", link):
        download_playlist_tracks(link, output_path, create_folder,
                                 explicit_name_convention)
    else:
        logging.error(f"{link} is not a valid Spotify track or playlist link")
        print(f"\n{link} is not a valid Spotify track or playlist link")
