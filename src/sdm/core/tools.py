"""Running the audio tools — fpcalc, ffprobe, ffmpeg — in one place, so a front end can change how.

`duplicates` and `rekordbox` fingerprint with fpcalc (`core/fingerprint.py`),
and `quality` probes with ffprobe and decodes with ffmpeg (`measure.py`).
Natively each is a process. A browser tab has no processes, so `sdm.browser`
sets `runner` to one that runs WebAssembly builds of the same programs
(`wasm/build.sh`, instantiated by `frontend/src/browser/tools.ts`), and nothing
that calls `run` changes: the same argv, the same stdout, the same stderr.

**stdout is streamed, never collected, when the caller asks for it**: a decoded
track is ~150 MB of samples. `on_stdout` receives exactly `chunk_size` bytes per
call, except the last, however the tool happened to write them. That is
load-bearing for `quality`, whose spectrum is summed over whole FFT frames per
chunk: the same chunks give the same report, byte for byte, from a pipe or
from WebAssembly. stderr is returned whole; it is text, and callers parse it.

Like `core.spotify`'s `transport`, the hook is set by the browser build and
nothing else. Do not branch on "am I in a browser" in callers instead.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, Optional, Protocol, Sequence


@dataclass(frozen=True)
class Completed:
    returncode: int
    stdout: bytes  # empty when the caller took it through `on_stdout`
    stderr: bytes


class Tracker(Protocol):
    """Starts processes and is told when each ends: `quality`'s `Decoders`, which kills them on cancel."""

    def start(self, command: list[str], **kwargs) -> subprocess.Popen: ...

    def finished(self, proc: subprocess.Popen) -> None: ...


#: `(argv, on_stdout)` -> `Completed`; `on_stdout` is None to collect stdout.
#: Raises FileNotFoundError, as `Popen` does, for a tool it does not have.
Runner = Callable[[list[str], Optional[Callable[[bytes], None]]], Completed]

#: How a tool runs. None: as a process. Set by `sdm.browser` and nothing else.
runner: Optional[Runner] = None


def available(tool: str) -> bool:
    """Whether `tool` ("fpcalc", "ffprobe", "ffmpeg") can be run at all."""
    return runner is not None or shutil.which(tool) is not None


def run(
    argv: Sequence[str],
    *,
    on_stdout: Optional[Callable[[bytes], None]] = None,
    chunk_size: int = 1 << 16,
    tracker: Optional[Tracker] = None,
    timeout: Optional[float] = None,
) -> Completed:
    """Run `argv` to the end. stdout to `on_stdout` in `chunk_size` pieces, or collected.

    An exception from `on_stdout` (Ctrl-C included) stops the tool before it
    propagates: a decode must not outlive the run that wanted it. `timeout`
    applies to a collected run, as in `subprocess.run`: the process is killed
    and `subprocess.TimeoutExpired` raised. A runner has no clock to watch.
    """
    argv = list(argv)
    if runner is not None:
        if on_stdout is None:
            return runner(argv, None)
        chunks = _Rechunk(on_stdout, chunk_size)
        completed = runner(argv, chunks.write)
        chunks.flush()
        return completed

    start = tracker.start if tracker is not None else subprocess.Popen
    proc = start(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        if on_stdout is None:
            try:
                out, err = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise
            return Completed(proc.returncode, out, err)
        returncode, err = _stream(proc, on_stdout, chunk_size)
        return Completed(returncode, b"", err)
    finally:
        if tracker is not None:
            tracker.finished(proc)


def _stream(proc: subprocess.Popen, on_stdout: Callable[[bytes], None], chunk_size: int) -> tuple[int, bytes]:
    """`run`'s process half: stdout through `on_stdout`; the exit code and the whole stderr."""
    # stderr is drained on its own thread: ffmpeg's verbose output runs to
    # several KB before the first sample, more than a pipe buffers, and ffmpeg
    # would block on it while this thread blocks on stdout.
    err: list[bytes] = []
    drain = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
    drain.start()
    try:
        while True:
            data = proc.stdout.read(chunk_size)  # exactly chunk_size, until the end
            if not data:
                break
            on_stdout(data)
    finally:
        # On an exception — Ctrl-C included — the tool must not outlive the run.
        if proc.poll() is None and not proc.stdout.closed:
            proc.stdout.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        drain.join()
    return proc.returncode, b"".join(err)


class _Rechunk:
    """Regroup whatever sizes a tool writes into `size`-byte pieces, as a pipe read gives them."""

    def __init__(self, sink: Callable[[bytes], None], size: int) -> None:
        self.sink = sink
        self.size = size
        self.pending = bytearray()

    def write(self, data: bytes) -> None:
        self.pending += data
        while len(self.pending) >= self.size:
            piece = bytes(self.pending[: self.size])
            del self.pending[: self.size]
            self.sink(piece)

    def flush(self) -> None:
        if self.pending:
            piece = bytes(self.pending)
            self.pending.clear()
            self.sink(piece)
