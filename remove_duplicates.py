import os
import hashlib

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

directory_to_check = 'C:\\Users\\omark\\Music\\library'
find_and_delete_duplicates(directory_to_check)
