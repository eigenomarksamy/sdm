import os

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
