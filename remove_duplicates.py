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
    # Dictionary to store file hashes and their paths
    file_hashes = {}

    print("Going through files.")

    # Walk through the directory
    for root, dirs, files in os.walk(directory):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            file_hash = hash_file(file_path)

            if file_hash in file_hashes:
                # Duplicate found, delete the file
                print(f"Duplicate found and deleted: {file_path}")
                os.remove(file_path)
            else:
                # Store the hash and path of the unique file
                file_hashes[file_hash] = file_path

    print("Duplicate removal complete.")

# Specify the directory you want to process
directory_to_check = 'C:\\Users\\omark\\Music\\library'

# Run the duplicate finder and deleter
find_and_delete_duplicates(directory_to_check)
