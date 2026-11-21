"""Compare the installed version with a release supplied by an adapter."""

import re
from collections.abc import Callable
from dataclasses import dataclass

SETUP_FILENAME = "passwordSafe-Setup.exe"
VERSION_PATTERN = re.compile(r"v?(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})")


class UpdateError(Exception):
    """A safe, user-displayable update check failure."""


@dataclass(frozen=True, slots=True)
class Release:
    tag: str
    page_url: str
    has_installer: bool


def _version_key(value: str) -> tuple[int, int, int]:
    match = VERSION_PATTERN.fullmatch(value)
    if not match:
        raise UpdateError("Не удалось распознать версию. Ожидается формат vMAJOR.MINOR.PATCH.")
    return int(match[1]), int(match[2]), int(match[3])


class UpdateChecker:
    def __init__(self, current_version: str, latest_release: Callable[[], Release]):
        self._current_version = current_version
        self._latest_release = latest_release

    def check(self) -> Release | None:
        release = self._latest_release()
        if _version_key(release.tag) <= _version_key(self._current_version):
            return None
        if not release.has_installer:
            raise UpdateError(f"В новом релизе нет установщика {SETUP_FILENAME}.")
        return release
