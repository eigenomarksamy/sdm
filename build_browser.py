"""Builds the browser version of sdm into dist/, for sdm.eigenomar.com.

The same page `sdm web` serves, with no server behind it: `vite build --mode
browser` swaps the page's API for one that runs the commands in the visitor's
own browser, through Pyodide in a Web Worker (frontend/src/browser/, and
src/sdm/browser.py on the Python side). This script builds that page, then adds
the Python it runs:

    dist/pyodide/v<version>/   the Pyodide release - only the files the page
                               loads: runtime, standard library, numpy, packaging,
                               and what single commands load on their first run
    dist/wheels/               sdm and its pure-Python dependencies, built here
    dist/tools/<hash>/         fpcalc, ffprobe and sdm_ffmpeg as WebAssembly, for
                               duplicates, rekordbox and quality - built by
                               wasm/build.sh on Linux or in WSL, copied from
                               build/wasm-tools/
    dist/python.json           what the worker installs, and every file's size
                               for the download progress bar

Everything the page loads comes from its own origin, so nothing is fetched from
PyPI or a CDN when it runs - which is also what lets its Content-Security-Policy
(frontend/src/browser/_headers) forbid connecting anywhere else. This script
does use the network: npm, PyPI for the wheels, and jsDelivr for Pyodide's own
numpy and packaging, each checked against the hash in Pyodide's lock file.

Usage:
    python build_browser.py              # npm ci, then everything
    python build_browser.py --no-install # skip npm ci, for a rebuild
    python build_browser.py --without-tools  # no WebAssembly tools: duplicates
                                             # and quality are left offline
    npx wrangler dev                     # serve dist/ with its headers
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

#: Must match frontend/package.json, which supplies the release's core files.
PYODIDE_VERSION = "314.0.7"
PYODIDE_CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"

#: The core release files the page loads. Everything else in a release (the
#: console pages, the type declarations, ~250 packages) is left out.
PYODIDE_CORE = ("pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip")

#: From Pyodide's own builds, because pip cannot build them for WebAssembly:
#: numpy (pyrekordbox.anlz, for `analyze`), and packaging, which eyed3's
#: `deprecation` dependency imports. Not micropip: `loadPackage` installs our
#: wheels from their URLs directly.
PYODIDE_PACKAGES = ("numpy", "packaging")

#: And what single commands load on their first run, from the module that
#: decides: SQLAlchemy and pycryptodome for `rekordbox`, which nothing else
#: needs, so they are shipped but not part of the boot.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from sdm.browser import COMMAND_PACKAGES  # noqa: E402 - stdlib-only at import

#: Pure-Python wheels, pinned so a build cannot silently change what runs. All
#: --no-deps: eyed3 declares `coverage`, which it never imports, and
#: pyrekordbox declares its database stack, which `sdm.browser` keeps from
#: loading (see `_shim_pyrekordbox`). bidict is one of those and is left out.
WHEELS = (
    "mutagen==1.47.0",
    "eyed3==0.9.7",
    "filetype==1.2.0",
    "deprecation==2.1.0",
    "construct==2.10.70",
    "pyrekordbox==0.4.4",
)

#: Cloudflare Workers static assets, as of 2026-10: 25 MiB per file and 20,000
#: files per version on the free plan. Checked here so a build that would not
#: deploy fails now, with a reason.
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_FILES = 20_000

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"
DIST = ROOT / "dist"
CACHE = ROOT / "build" / "pyodide-cache"

#: What wasm/build.sh writes. It needs Emscripten and a POSIX shell, so it is
#: run on its own (on Linux, or `wsl bash wasm/build.sh` on Windows) and this
#: script ships its output. File names as frontend/src/browser/tools.ts has them.
TOOLS_BUILD = ROOT / "build" / "wasm-tools"
TOOL_FILES = ("fpcalc", "ffprobe", "sdm_ffmpeg")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--no-install", action="store_true", help="Skip `npm ci` (node_modules is current).")
    parser.add_argument("--without-tools", action="store_true",
                        help="Build without wasm/build.sh's audio tools, where they cannot be built "
                             "(no Emscripten). duplicates and quality are then offline, and "
                             "rekordbox cannot fingerprint.")
    args = parser.parse_args()

    npm = shutil.which("npm")
    if npm is None:
        sys.exit("build_browser.py: npm is not on PATH; the page needs Node to build.")
    if not args.no_install:
        run([npm, "ci"], cwd=FRONTEND)
    run([npm, "run", "build:browser"], cwd=FRONTEND)  # empties and fills dist/

    pyodide_dir = DIST / "pyodide" / f"v{PYODIDE_VERSION}"
    lock = copy_pyodide(pyodide_dir)
    packages = fetch_packages(lock, pyodide_dir, PYODIDE_PACKAGES)
    later = fetch_packages(lock, pyodide_dir, [name for names in COMMAND_PACKAGES.values() for name in names])
    wheels = build_wheels(DIST / "wheels")
    tools = None if args.without_tools else copy_tools(DIST / "tools")

    loaded = [pyodide_dir / "pyodide.asm.wasm", pyodide_dir / "python_stdlib.zip"]
    loaded += [pyodide_dir / lock["packages"][name]["file_name"] for name in packages]
    loaded += [DIST / "wheels" / name for name in wheels]
    manifest = {
        "pyodide": f"pyodide/v{PYODIDE_VERSION}/",
        "packages": packages,
        "lock": {"info": lock["info"], "packages": {name: lock["packages"][name] for name in [*packages, *later]}},
        "wheels": wheels,
        "tools": tools,
        # Only what the boot fetches; the two .mjs files are imported, which
        # a fetch counter cannot see, and are small beside the rest.
        "bytes": {"/" + path.relative_to(DIST).as_posix(): path.stat().st_size for path in loaded},
    }
    (DIST / "python.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")

    check_limits()
    total = sum(manifest["bytes"].values())
    extra = sum((pyodide_dir / lock["packages"][name]["file_name"]).stat().st_size for name in later)
    print(f"built dist/: Pyodide {PYODIDE_VERSION} + {', '.join(packages)}, "
          f"{len(wheels)} wheels, {total / 1e6:.1f} MB downloaded on a first visit; "
          f"{', '.join(later)} on demand, {extra / 1e6:.1f} MB")
    return 0


def run(command: list[str], cwd: Path) -> None:
    print("$", " ".join(Path(command[0]).name if i == 0 else c for i, c in enumerate(command)), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def copy_pyodide(dest: Path) -> dict:
    """The release's core files, from the npm package the page's lock pins."""
    source = FRONTEND / "node_modules" / "pyodide"
    version = json.loads((source / "package.json").read_text(encoding="utf-8"))["version"]
    if version != PYODIDE_VERSION:
        sys.exit(f"build_browser.py: frontend has pyodide {version}, this script pins {PYODIDE_VERSION}")
    dest.mkdir(parents=True, exist_ok=True)
    for name in PYODIDE_CORE:
        shutil.copy2(source / name, dest / name)
    return json.loads((source / "pyodide-lock.json").read_text(encoding="utf-8"))


def fetch_packages(lock: dict, dest: Path, names) -> list[str]:
    """`names` and what they depend on, downloaded once and hash-checked."""
    wanted: list[str] = []
    pending = list(names)
    while pending:
        name = pending.pop(0)
        if name not in wanted:
            wanted.append(name)
            pending += lock["packages"][name].get("depends", [])

    CACHE.mkdir(parents=True, exist_ok=True)
    for name in wanted:
        entry = lock["packages"][name]
        cached = CACHE / entry["file_name"]
        if not cached.exists() or sha256(cached) != entry["sha256"]:
            print(f"downloading {entry['file_name']}", flush=True)
            with urllib.request.urlopen(PYODIDE_CDN + entry["file_name"]) as response:
                cached.write_bytes(response.read())
            if sha256(cached) != entry["sha256"]:
                cached.unlink()
                sys.exit(f"build_browser.py: {entry['file_name']} does not match Pyodide's lock file")
        shutil.copy2(cached, dest / entry["file_name"])
    return wanted


def copy_tools(dest: Path) -> str:
    """wasm/build.sh's output, under a directory named by its hash, so it can be cached as immutable."""
    files = [TOOLS_BUILD / f"{name}{ext}" for name in TOOL_FILES for ext in (".mjs", ".wasm")]
    missing = [path.name for path in files if not path.is_file()]
    if missing:
        sys.exit(f"build_browser.py: {', '.join(missing)} not in {TOOLS_BUILD.relative_to(ROOT)}/. "
                 "Build the audio tools first, on Linux or in WSL: bash wasm/build.sh, "
                 "or build without them: --without-tools")
    digest = hashlib.sha256(b"".join(path.read_bytes() for path in files)).hexdigest()[:12]
    (dest / digest).mkdir(parents=True, exist_ok=True)
    for path in files:
        shutil.copy2(path, dest / digest / path.name)
    return f"tools/{digest}/"


def build_wheels(dest: Path) -> list[str]:
    """sdm from this checkout, and `WHEELS` from PyPI, all as wheels in `dest`."""
    dest.mkdir(parents=True, exist_ok=True)
    pip = [sys.executable, "-m", "pip", "wheel", "--no-deps", "--quiet", "--disable-pip-version-check", "-w", str(dest)]
    run(pip + [str(ROOT)], cwd=ROOT)
    run(pip + list(WHEELS), cwd=ROOT)
    return sorted(path.name for path in dest.glob("*.whl"))


def check_limits() -> None:
    files = [path for path in DIST.rglob("*") if path.is_file() and path.name not in ("_headers", "_redirects")]
    too_big = [path for path in files if path.stat().st_size > MAX_FILE_BYTES]
    if too_big or len(files) > MAX_FILES:
        sys.exit(f"build_browser.py: over Cloudflare's asset limits: {len(files)} files, too big: "
                 + ", ".join(str(path.relative_to(DIST)) for path in too_big))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    sys.exit(main())
