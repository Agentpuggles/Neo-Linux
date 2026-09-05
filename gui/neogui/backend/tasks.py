"""Background work. Nothing that can block ever runs on the UI thread.

A `Job` wraps a callable on a `QThreadPool`. It emits `progress`, `message`,
`finished` and `failed` on the UI thread, and hands the callable a `CancelToken`
if it declares one, so a running download can be stopped cleanly.
"""

from __future__ import annotations

import inspect
import traceback
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from .errors import NeoError, classify
from .models import Progress
from .service import Cancelled, CancelToken


class JobSignals(QObject):
    progress = Signal(object)  # Progress
    message = Signal(str)
    finished = Signal(object)  # result
    failed = Signal(object)  # NeoError
    cancelled = Signal()
    done = Signal()  # always, after any terminal signal


class Job(QRunnable):
    def __init__(self, fn: Callable, *args, action: str = "", **kwargs) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.action = action
        self.signals = JobSignals()
        self.cancel_token = CancelToken()
        # Qt would delete the QRunnable as soon as run() returns — but our
        # terminal signals are delivered *queued* onto the UI thread, so the
        # JobSignals object would be destroyed before they arrive and the
        # result would be silently dropped. TaskRunner owns the lifetime
        # instead and releases the job once `done` has actually been handled.
        self.setAutoDelete(False)

        params = set()
        try:
            params = set(inspect.signature(fn).parameters)
        except (TypeError, ValueError):
            pass
        if "progress" in params:
            self.kwargs.setdefault("progress", self._emit_progress)
        if "log" in params:
            self.kwargs.setdefault("log", self.signals.message.emit)
        if "cancel" in params:
            self.kwargs.setdefault("cancel", self.cancel_token)

    def _emit_progress(self, p: Progress) -> None:
        self.signals.progress.emit(p)

    def cancel(self) -> None:
        self.cancel_token.cancel()

    def _emit(self, signal, *args) -> None:
        """Emit unless Qt has already destroyed the receiver.

        A job can outlive the window during shutdown; emitting into a deleted
        QObject raises, and it is never something the user should see.
        """
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    @Slot()
    def run(self) -> None:  # pragma: no cover - thread body
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Cancelled:
            self._emit(self.signals.cancelled)
        except NeoError as exc:
            self._emit(self.signals.failed, exc)
        except Exception as exc:
            err = classify(exc, action=self.action)
            if not err.detail:
                err.detail = traceback.format_exc(limit=6)
            self._emit(self.signals.failed, err)
        else:
            self._emit(self.signals.finished, result)
        finally:
            self._emit(self.signals.done)


class TaskRunner(QObject):
    """Owns the pool and keeps references to live jobs so they can be cancelled."""

    busy_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None, max_threads: int = 6) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max_threads)
        self._live: dict = {}
        self._retained: set = set()  # jobs kept alive until `done` is delivered

    def run(
        self,
        fn: Callable,
        *args,
        action: str = "",
        key: str = "",
        on_result: Callable | None = None,
        on_error: Callable | None = None,
        on_progress: Callable | None = None,
        on_message: Callable | None = None,
        on_cancelled: Callable | None = None,
        on_done: Callable | None = None,
        **kwargs,
    ) -> Job:
        """Start `fn`. A `key` makes the job replaceable/cancellable by name."""
        if key and key in self._live:
            self._live[key].cancel()
        job = Job(fn, *args, action=action, **kwargs)
        if on_result:
            job.signals.finished.connect(on_result)
        if on_error:
            job.signals.failed.connect(on_error)
        if on_progress:
            job.signals.progress.connect(on_progress)
        if on_message:
            job.signals.message.connect(on_message)
        if on_cancelled:
            job.signals.cancelled.connect(on_cancelled)
        if on_done:
            job.signals.done.connect(on_done)
        if key:
            self._live[key] = job
            job.signals.done.connect(lambda k=key: self._release(k))
        self._retained.add(job)
        job.signals.done.connect(lambda j=job: self._retire(j))
        self._set_busy()
        job.signals.done.connect(self._set_busy)
        self.pool.start(job)
        return job

    def _retire(self, job: Job) -> None:
        """Drop our reference once the last signal has been delivered."""
        self._retained.discard(job)

    def _release(self, key: str) -> None:
        self._live.pop(key, None)

    def _set_busy(self) -> None:
        self.busy_changed.emit(bool(self._live))

    def is_running(self, key: str) -> bool:
        return key in self._live

    def cancel(self, key: str) -> None:
        job = self._live.get(key)
        if job:
            job.cancel()

    def cancel_all(self) -> None:
        for job in list(self._live.values()):
            job.cancel()

    def shutdown(self, msecs: int = 3000) -> None:
        self.cancel_all()
        self.pool.waitForDone(msecs)
