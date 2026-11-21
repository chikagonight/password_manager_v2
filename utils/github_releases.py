"""Read stable release metadata without credentials or downloading executables."""

import json
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from password_safe.updates import SETUP_FILENAME, Release, UpdateError

GITHUB_REPOSITORY = "chikagonight/password_manager_v2"
RELEASES_URL = f"https://github.com/{GITHUB_REPOSITORY}/releases"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
MAX_RESPONSE_BYTES = 2**20


class GitHubReleases:
    def latest_release(self) -> Release:
        request = Request(
            LATEST_RELEASE_API,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "passwordSafe"},
        )
        invalid_response = "GitHub вернул некорректные данные о релизе."
        try:
            with urlopen(request, timeout=5) as response:
                if response.geturl() != LATEST_RELEASE_API:
                    raise UpdateError(invalid_response)
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            exc.close()
            if exc.code == 404:
                raise UpdateError("Релиз недоступен: репозиторий может быть закрытым или релиз ещё не опубликован.") from None
            raise UpdateError(f"GitHub не выполнил проверку обновлений (HTTP {exc.code}).") from None
        except (OSError, HTTPException):
            raise UpdateError("Не удалось подключиться к GitHub для проверки обновлений.") from None

        if len(raw) > MAX_RESPONSE_BYTES:
            raise UpdateError(invalid_response)
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            raise UpdateError(invalid_response) from None
        if (
            not isinstance(data, dict)
            or data.get("draft") is not False
            or data.get("prerelease") is not False
            or not isinstance(tag := data.get("tag_name"), str)
            or not isinstance(assets := data.get("assets"), list)
        ):
            raise UpdateError(invalid_response)
        has_installer = any(
            isinstance(asset, dict)
            and asset.get("name") == SETUP_FILENAME
            and asset.get("state") == "uploaded"
            and type(size := asset.get("size")) is int
            and size > 0
            for asset in assets
        )
        # The use case checks the tag's numeric format before the GUI receives this link.
        return Release(tag, f"{RELEASES_URL}/tag/{quote(tag, safe='', errors='replace')}", has_installer)
