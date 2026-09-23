import os
import hashlib

def resolve_path(output_path: os.PathLike,
                 create_pl_folder: bool = True,
                 make_dirs: bool = True) -> dict:
    ret = {'status': 0}
    if not os.path.exists(output_path):
        if create_pl_folder or make_dirs:
            os.makedirs(output_path)
        else:
            ret = {'status': 1, 'details': 'directory not found'}
    return ret

def remove_empty_files(output_path: os.PathLike) -> None:
    for file in os.listdir(output_path):
        if os.path.getsize(os.path.join(output_path, file)) == 0:
            os.remove(os.path.join(output_path, file))

def check_existing_files(file_list_dict: dict, output_path: os.PathLike,
                         extension: str) -> dict:
    existing_files = os.listdir(output_path)
    for file in existing_files:
        if file.endswith(f".{extension}"):
            file = file.split(f".{extension}")[0]
            if file_list_dict.get(file):
                file_list_dict.pop(file)
    return file_list_dict

def get_unique_name_of_folder(directory: os.PathLike) -> str:
    name_folder = 'new_folder'
    folders = os.listdir(directory)
    folders = [folder.lower() for folder in folders]
    i = 0
    while name_folder in folders:
        name_folder = f'new_folder_{i}'
        i += 1
    return name_folder

def hash_file(file_path, chunk_size=8192):
    """Generate SHA-256 hash of the file content, reading in chunks to handle large files."""
    hasher = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()

def find_and_delete_duplicates(directory):
    """Find and delete duplicate files in the given directory and its subdirectories."""
    file_hashes = {}
    print("Going through files.")
    for root, dirs, files in os.walk(directory):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            file_hash = hash_file(file_path)
            if file_hash in file_hashes:
                print(f"Duplicate found!")
                inp = ""
                inp = input("Which file do you want to keep?\n\t"
                            f"1: {file_path}\n\t"
                            f"2: {file_hashes[file_hash]}\n"
                            "Choice: ")
                if inp == "1":
                    os.remove(file_hashes[file_hash])
                    print(f"File at {file_hashes[file_hash]} was deleted.")
                elif inp == "2":
                    os.remove(file_path)
                    print(f"File at {file_path} was deleted.")
                else:
                    print("No choice, both files kept.")
            else:
                file_hashes[file_hash] = file_path

    print("Duplicate removal complete.")
