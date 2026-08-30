"""Long sessions, run off the request thread.

A grand prix is minutes of arithmetic: the engine simulates every car on every
lap, and that is the reason its results are worth having.  It is not something
to hold an HTTP connection open for, so qualifying and races are started as
jobs and polled.

Deliberately a thread pool and not a queue, a broker or a worker fleet.  The
game is one process with one game in it, the work is CPU-bound Python that
cannot be usefully spread across threads anyway, and the pool is here to keep
the request thread free rather than to go faster.  When a season needs to run
faster than one race at a time, this is the seam to replace -- and until then
adding a broker would be infrastructure with nothing to do.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

__all__ = ["Job", "JobRunner", "JobStatus"]


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    """One piece of work, and what became of it."""

    id: str
    kind: str
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    """0 to 1, when the work can say.  A race reports the laps it has run."""

    detail: str = ""
    result: Any = None
    error: str = ""
    error_code: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "status": self.status.value,
            "progress": round(self.progress, 4),
            "detail": self.detail,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
        if self.status is JobStatus.DONE:
            payload["result"] = self.result
        if self.status is JobStatus.FAILED:
            payload["error"] = self.error
            payload["code"] = self.error_code
        return payload


class JobRunner:
    """Starts jobs and remembers them."""

    def __init__(self, *, max_workers: int = 2, keep: int = 40) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="sim")
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._keep = keep
        self._lock = threading.Lock()

    def submit(
        self,
        kind: str,
        work: Callable[[Job], Any],
        *,
        detail: str = "",
    ) -> Job:
        """Start ``work``, handing it the job so it can report progress."""
        job = Job(id=uuid.uuid4().hex, kind=kind, detail=detail)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._forget_old()

        def run() -> None:
            job.status = JobStatus.RUNNING
            try:
                job.result = work(job)
                job.progress = 1.0
                job.status = JobStatus.DONE
            except Exception as error:  # noqa: BLE001 - reported, not swallowed
                job.status = JobStatus.FAILED
                job.error = str(error) or error.__class__.__name__
                job.error_code = getattr(error, "code", error.__class__.__name__)
                job.detail = traceback.format_exc(limit=3)
            finally:
                job.finished_at = time.time()

        self._pool.submit(run)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def recent(self, limit: int = 10) -> list[Job]:
        with self._lock:
            ids = self._order[-limit:][::-1]
        return [self._jobs[i] for i in ids if i in self._jobs]

    def wait(self, job_id: str, timeout: float | None = None) -> Job | None:
        """Block until a job finishes.  For tests and for a synchronous client."""
        job = self.get(job_id)
        if job is None:
            return None
        deadline = None if timeout is None else time.time() + timeout
        while job.status in (JobStatus.PENDING, JobStatus.RUNNING):
            if deadline is not None and time.time() > deadline:
                break
            time.sleep(0.02)
        return job

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _forget_old(self) -> None:
        while len(self._order) > self._keep:
            self._jobs.pop(self._order.pop(0), None)
