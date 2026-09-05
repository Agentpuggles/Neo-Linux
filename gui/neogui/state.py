"""One cached snapshot of the world, shared by every view.

Views never fetch on their own: they call `AppState.refresh_x()` and render
whatever the matching signal delivers. That is what keeps the account chip, the
Play page and Diagnostics from ever disagreeing about the same fact.
"""

from __future__ import annotations


from PySide6.QtCore import QObject, QTimer, Signal

from .backend.errors import NeoError
from .backend.models import CacheStats, ServiceStatus, Session
from .backend.service import NeoService
from .backend.tasks import TaskRunner

STATUS_POLL_MS = 120_000


class AppState(QObject):
    session_changed = Signal(object)  # Session
    status_changed = Signal(object)  # ServiceStatus
    builds_changed = Signal(list)
    installs_changed = Signal(list)
    news_changed = Signal(list)
    friends_changed = Signal(list, str)
    cache_changed = Signal(object)  # CacheStats
    config_changed = Signal(dict)
    error = Signal(object)  # NeoError, for the toast layer
    notice = Signal(str, str)  # (tone, text)
    activity = Signal(str)  # one-line activity log entry

    def __init__(self, service: NeoService, tasks: TaskRunner, parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.tasks = tasks

        self.session: Session = Session()
        self.status: ServiceStatus = ServiceStatus()
        self.builds: list = []
        self.installs: list = []
        self.news: list = []
        self.friends: list = []
        self.friends_transport: str = ""
        self.cache: CacheStats = CacheStats()
        self.config: dict = {}
        self.launching: bool = False
        self.game_running: bool = False

        self._poll = QTimer(self)
        self._poll.setInterval(STATUS_POLL_MS)
        self._poll.timeout.connect(lambda: self.refresh_status(deep=True, quiet=True))

    # ------------------------------------------------------------------ boot
    def start(self) -> None:
        self.reload_config()
        self.refresh_session()
        self.refresh_installs()
        self.refresh_status(quiet=True)
        self.refresh_builds(quiet=True)
        self.refresh_news(quiet=True)
        self._poll.start()

    def stop(self) -> None:
        self._poll.stop()

    # ---------------------------------------------------------------- config
    def reload_config(self) -> dict:
        self.config = self.service.config()
        self.config_changed.emit(self.config)
        return self.config

    def set_config(self, key: str, value) -> bool:
        try:
            self.service.set_config(key, value)
        except NeoError as exc:
            self.error.emit(exc)
            return False
        self.reload_config()
        return True

    # --------------------------------------------------------------- session
    def refresh_session(self) -> None:
        self.session = self.service.session()
        self.session_changed.emit(self.session)
        if self.session.logged_in:
            self.tasks.run(
                self.service.account_details,
                key="account",
                action="Loading your account",
                on_result=self._set_session,
                on_error=lambda e: None,  # the chip already shows the cached name
            )

    def _set_session(self, session: Session) -> None:
        self.session = session
        self.session_changed.emit(session)

    def sign_out(self) -> None:
        self.session = self.service.logout()
        self.session_changed.emit(self.session)
        self.log_activity("Signed out")
        self.refresh_status(quiet=True)

    # ---------------------------------------------------------------- status
    def refresh_status(self, *, deep: bool = True, quiet: bool = False) -> None:
        self.tasks.run(
            self.service.service_status,
            deep=deep,
            key="status",
            action="Checking service status",
            on_result=self._set_status,
            on_error=(lambda e: None) if quiet else self.error.emit,
        )

    def _set_status(self, status: ServiceStatus) -> None:
        was_granted = self.status.fortnite_access
        self.status = status
        self.status_changed.emit(status)
        if status.fortnite_access and was_granted is False:
            self.notice.emit("success", "Game access granted — you can launch now.")
            self.log_activity("Account access granted")

    # ---------------------------------------------------------------- builds
    def refresh_builds(self, *, quiet: bool = False) -> None:
        self.tasks.run(
            self.service.builds,
            key="builds",
            action="Loading the build catalog",
            on_result=self._set_builds,
            on_error=(lambda e: None) if quiet else self.error.emit,
        )

    def _set_builds(self, builds: list) -> None:
        self.builds = builds
        self.builds_changed.emit(builds)

    # -------------------------------------------------------------- installs
    def refresh_installs(self) -> None:
        self.installs = self.service.installs()
        self.installs_changed.emit(self.installs)
        self.refresh_cache()

    def refresh_cache(self) -> None:
        self.tasks.run(
            self.service.cache_stats,
            key="cache",
            on_result=self._set_cache,
            on_error=lambda e: None,
        )

    def _set_cache(self, cache: CacheStats) -> None:
        self.cache = cache
        self.cache_changed.emit(cache)

    def preferred_install(self):
        playable = [i for i in self.installs if i.playable]
        return playable[0] if playable else (self.installs[0] if self.installs else None)

    # ------------------------------------------------------------------ news
    def refresh_news(self, *, quiet: bool = False) -> None:
        self.tasks.run(
            self.service.news,
            key="news",
            action="Loading news",
            on_result=self._set_news,
            on_error=(lambda e: None) if quiet else self.error.emit,
        )

    def _set_news(self, items: list) -> None:
        self.news = items
        self.news_changed.emit(items)

    # --------------------------------------------------------------- friends
    def refresh_friends(self, *, on_error: object | None = None) -> None:
        self.tasks.run(
            self.service.friends,
            key="friends",
            action="Loading your friends list",
            on_result=self._set_friends,
            on_error=on_error or self.error.emit,
        )

    def _set_friends(self, payload) -> None:
        friends, transport = payload
        self.friends = friends
        self.friends_transport = transport
        self.friends_changed.emit(friends, transport)

    # -------------------------------------------------------------- activity
    def log_activity(self, text: str) -> None:
        self.activity.emit(text)
