"""Finding files and folders inside the project.

Bricks in this module do not use OpenDSS. They only search the file system, so they can be used
for any kind of data file (.dss, .txt, .npy, .csv ...).
"""
import os
from pathlib import Path

DEFAULT_ROOT_MARKERS = (".git", ".gitignore", "requirements.txt")

def figure_path(name, figure_folder):
    return Path(figure_folder) / name if figure_folder else None


def find_project_root(start=None, markers=DEFAULT_ROOT_MARKERS):
    """Move up from 'start' (default: the folder Python runs in) until a folder contains one of
    the 'markers'. Return that folder, or 'start' itself if no marker is found."""
    start = Path(start or os.getcwd()).resolve()
    for folder in [start, *start.parents]:
        if any((folder / marker).exists() for marker in markers):
            return folder
    return start


def find_folders_with(file_name, start, folder_name=None):
    """Return every folder under 'start' that contains 'file_name' (and is called 'folder_name',
    if given). Hidden folders (.git, .venv, ...) and __pycache__ are skipped."""
    found = []
    for root, dirs, files in os.walk(start):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "__pycache__")
        if file_name in files and (folder_name is None or Path(root).name == folder_name):
            found.append(Path(root))
    return found


def locate_file(file_name, folder_name=None, start=None, markers=DEFAULT_ROOT_MARKERS, verbose=True):
    """Return the full path of 'file_name'.

    'folder_name' can be a folder name, a path relative to the project root, a full path, or None
    (search the whole project). Raises FileNotFoundError listing every folder that does contain
    the file, so the right one can be copied into 'folder_name'."""
    here = Path(start or os.getcwd()).resolve()
    root = find_project_root(here, markers)
    if folder_name:
        direct = [Path(folder_name), here / folder_name, root / folder_name]
        candidates = [c.resolve() for c in direct if (c / file_name).is_file()]
        if not candidates:
            candidates = find_folders_with(file_name, root, Path(folder_name).name)
    else:
        candidates = find_folders_with(file_name, root)

    if not candidates:
        options = find_folders_with(file_name, root)
        listing = "\n".join(f"    {p.relative_to(root).as_posix()}" for p in options) or "    (none)"
        raise FileNotFoundError(f"'{file_name}' was not found in a folder called '{folder_name}' under {root}\n"
                                f"Folders that contain '{file_name}' (relative to the project root):\n{listing}")

    unique = list(dict.fromkeys(c.resolve() for c in candidates))
    if len(unique) > 1:
        print(f"WARNING: '{file_name}' was found in {len(unique)} places, the first one is used: {unique[0]}")
    path = unique[0] / file_name
    if verbose:
        print(f"Project root: {root}\nFound:        {path}")
    return path
