"""Commands run from the web UI, one subprocess each.

A subprocess rather than calling the handler in-process, for three reasons that
would each be enough on its own:

  - The commands report by printing, and some run for many minutes. A child's
    stdout is a stream to forward; in-process, several runs would share one
    `sys.stdout`.
  - `core.paths` keeps its roots process-global, by design, for a one-shot CLI.
    One process per run keeps that assumption true.
  - A run can be cancelled. A thread cannot be stopped; a process can be told to
    stop, and told the way Ctrl-C tells it.

**Cancelling is the part with a trap.** Killing the child outright skips its
`finally` blocks, and `core.fpcalc_fetch` relies on one to delete the fpcalc it
borrowed into tmp/. So a cancel first sends what Ctrl-C would (CTRL_BREAK on
Windows, which needs the child in its own process group; SIGINT to the group
elsewhere), `child.py` turns that into KeyboardInterrupt, and only a child still
alive after `CANCEL_GRACE` seconds is killed. The grace outlasts `_purge`'s own
retries, so a cancel during a borrowed-fpcalc run still cleans up.

Jobs live in memory and are gone when the server stops. The reports they wrote
are not: those are on disk under out/, where the report browser finds them.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import IO, Optional

from sdm.web.child import CANCELLED_EXIT
from sdm.web.schema import Invocation

#: Seconds a cancelled run gets to unwind before it is killed.
CANCEL_GRACE = 15.0

#: Log lines kept per job. `duplicates` logs every 25 fingerprint pairs, which
#: on the reference library is ~2,600 lines; this is headroom, not a target.
MAX_LINES = 20_000

#: Finished jobs kept for the job list; the oldest are dropped first.
MAX_FINISHED = 50

#: Every command announces its reports this way (`print(f"wrote {path}")`).
_WROTE = re.compile(r"^wrote (.+)$")


class Busy(RuntimeError):
    """The same command is already running. Two runs would overwrite one report."""

    def __init__(self, job: "Job"):
        super().__init__(f"sdm {job.command} is already running (job {job.id})")
        self.job = job


@dataclass
class Job:
    id: str
    command: str
    display: str
    started: float
    status: str = "running"            # running | succeeded | failed | cancelled
    exit_code: Optional[int] = None
    ended: Optional[float] = None
    cancel_requested: bool = False
    first_line: int = 0                # absolute number of lines[0], after trimming
    lines: list = field(default_factory=list)      # [stream, text] pairs
    outputs: list = field(default_factory=list)    # absolute paths, in order seen
    _proc: Optional[subprocess.Popen] = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def summary(self) -> dict:
        return {
            "id": self.id,
            "command": self.command,
            "display": self.display,
            "status": self.status,
            "exit_code": self.exit_code,
            "started": self.started,
            "ended": self.ended,
            "cancel_requested": self.cancel_requested,
        }

    def detail(self, since: int, out_root: str) -> dict:
        """The summary, plus log lines from absolute line number `since` on."""
        with self._lock:
            start = max(since - self.first_line, 0)
            lines = self.lines[start:]
            next_line = self.first_line + len(self.lines)
            dropped = max(self.first_line - since, 0)
            outputs = list(self.outputs)
        return {
            **self.summary(),
            "lines": lines,
            "next": next_line,
            "dropped": dropped,
            "outputs": [_output(path, out_root) for path in outputs],
        }

    def _append(self, stream: str, text: str) -> None:
        with self._lock:
            self.lines.append([stream, text])
            if len(self.lines) > MAX_LINES:
                drop = len(self.lines) - MAX_LINES
                del self.lines[:drop]
                self.first_line += drop
            if stream == "out":
                match = _WROTE.match(text)
                if match:
                    self._add_output(match.group(1).strip())

    def _add_output(self, path: str) -> None:
        path = os.path.abspath(path)
        if path not in self.outputs:
            self.outputs.append(path)


class JobManager:
    def __init__(self, out_root: str, tmp_root: str, cwd: str):
        self.out_root = out_root
        self.tmp_root = tmp_root
        self.cwd = cwd
        self._jobs: dict[str, Job] = {}
        self._next_id = 1
        self._lock = threading.Lock()

    def start(self, invocation: Invocation) -> Job:
        with self._lock:
            for job in self._jobs.values():
                if job.command == invocation.command and job.status == "running":
                    raise Busy(job)
            job = Job(
                id=str(self._next_id),
                command=invocation.command,
                display=invocation.display,
                started=time.time(),
            )
            self._next_id += 1
            job._proc = self._spawn(invocation)
            self._jobs[job.id] = job
            self._trim()
        threading.Thread(target=self._supervise, args=(job,), daemon=True,
                         name=f"sdm-job-{job.id}").start()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def all(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: int(j.id), reverse=True)

    def output_paths(self) -> set[str]:
        """Every path any job said it wrote, normalized for comparison."""
        with self._lock:
            jobs = list(self._jobs.values())
        return {os.path.normcase(p) for j in jobs for p in list(j.outputs)}

    def cancel(self, job: Job) -> None:
        proc = job._proc
        if job.status != "running" or proc is None or proc.poll() is not None:
            return
        job.cancel_requested = True
        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(proc.pid, signal.SIGINT)
        except OSError:
            # No console to deliver CTRL_BREAK through (e.g. under pythonw), or
            # the process just went. Nothing gentler is available.
            proc.kill()
            return
        timer = threading.Timer(CANCEL_GRACE, lambda: proc.poll() is None and proc.kill())
        timer.daemon = True
        timer.start()

    def shutdown(self) -> None:
        """Cancel every running job and wait for them, so none outlives the server.

        Needed rather than merely polite: a child in its own process group does
        not receive the Ctrl-C that stops the server.
        """
        running = [j for j in self.all() if j.status == "running"]
        for job in running:
            self.cancel(job)
        deadline = time.monotonic() + CANCEL_GRACE + 2
        for job in running:
            if job._proc is not None:
                try:
                    job._proc.wait(timeout=max(deadline - time.monotonic(), 0.1))
                except subprocess.TimeoutExpired:
                    job._proc.kill()

    # --- internals ---------------------------------------------------------

    def _spawn(self, invocation: Invocation) -> subprocess.Popen:
        command, *rest = invocation.argv
        argv = [
            sys.executable, "-u", "-m", "sdm.web.child", command,
            "--out-dir", self.out_root, "--tmp-dir", self.tmp_root, *rest,
        ]
        # UTF-8 on the pipe: a child writing to a pipe on Windows otherwise uses
        # the ANSI code page and dies on the first track name outside it.
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **kwargs,
        )

    def _supervise(self, job: Job) -> None:
        proc = job._proc
        assert proc is not None and proc.stdout is not None and proc.stderr is not None
        err_reader = threading.Thread(target=_pump, args=(job, "err", proc.stderr), daemon=True)
        err_reader.start()
        _pump(job, "out", proc.stdout)
        err_reader.join()
        code = proc.wait()

        # Not every command says "wrote": `catalog` prints its results instead.
        # Anything under its own out/<command>/ touched since the run began is
        # the run's too. (Directory names match command names by convention.)
        for path in _touched_since(os.path.join(self.out_root, job.command), job.started - 2):
            with job._lock:
                job._add_output(path)

        job.exit_code = code
        job.ended = time.time()
        if job.cancel_requested or code == CANCELLED_EXIT:
            job.status = "cancelled"
        else:
            job.status = "succeeded" if code == 0 else "failed"

    def _trim(self) -> None:
        finished = [j for j in self._jobs.values() if j.status != "running"]
        finished.sort(key=lambda j: int(j.id))
        for job in finished[: max(len(finished) - MAX_FINISHED, 0)]:
            del self._jobs[job.id]


def _pump(job: Job, stream: str, pipe: IO[str]) -> None:
    for line in pipe:
        job._append(stream, line.rstrip("\r\n"))
    pipe.close()


def _touched_since(directory: str, since: float) -> list[str]:
    found = []
    for root, _, names in os.walk(directory):
        for name in names:
            path = os.path.join(root, name)
            try:
                if os.path.getmtime(path) >= since:
                    found.append(path)
            except OSError:
                pass
    return sorted(found)


def _output(path: str, out_root: str) -> dict:
    """An output path, plus its path relative to the output root when it is under it."""
    rel = None
    try:
        if os.path.commonpath([os.path.normcase(out_root), os.path.normcase(path)]) \
                == os.path.normcase(out_root):
            rel = os.path.relpath(path, out_root).replace(os.sep, "/")
    except ValueError:  # different drives
        pass
    return {"path": path, "rel": rel, "exists": os.path.isfile(path)}
