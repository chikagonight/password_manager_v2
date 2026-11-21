import io
import json
import unittest
from email.message import Message
from unittest.mock import patch
from urllib.error import HTTPError

from password_safe.updates import Release, UpdateChecker, UpdateError
from utils.github_releases import GitHubReleases


class UpdateCheckerTests(unittest.TestCase):
    def check(self, tag, *, has_installer=True):
        release = Release(tag, "https://example.test/releases", has_installer)
        return UpdateChecker("1.9.0", lambda: release).check()

    def test_returns_newer_release_using_numeric_comparison(self):
        update = self.check("v1.10.0")
        assert update is not None
        self.assertEqual("v1.10.0", update.tag)

    def test_ignores_equal_and_older_releases(self):
        for tag in ("v1.9.0", "v1.8.9", "1.9.0"):
            with self.subTest(tag=tag):
                self.assertIsNone(self.check(tag))

    def test_rejects_non_release_tags(self):
        for tag in ("v1.10.0-rc1", "v01.10.0", "v2.0.0/../../", "v1.10.0\n"):
            with self.subTest(tag=tag), self.assertRaises(UpdateError):
                self.check(tag)

    def test_reports_a_new_release_without_an_installer(self):
        with self.assertRaisesRegex(UpdateError, "passwordSafe-Setup.exe"):
            self.check("v2.0.0", has_installer=False)


class ReleaseResponse(io.BytesIO):
    def __init__(self, data: bytes, url: str):
        super().__init__(data)
        self._url = url

    def geturl(self) -> str:
        return self._url


class GitHubReleasesTests(unittest.TestCase):
    def setUp(self):
        self.source = GitHubReleases()
        self.api_url = "https://api.github.com/repos/chikagonight/password_manager_v2/releases/latest"
        self.release = {
            "tag_name": "v2.0.0",
            "draft": False,
            "prerelease": False,
            "html_url": "https://untrusted.example/",
            "assets": [{"name": "passwordSafe-Setup.exe", "state": "uploaded", "size": 100}],
        }
        self.open = self.enterContext(patch("utils.github_releases.urlopen"))

    def serve(self, data, *, url=None):
        self.open.return_value = ReleaseResponse(data, url or self.api_url)

    def test_reads_release_using_only_the_official_repository(self):
        self.serve(json.dumps(self.release).encode())
        release = self.source.latest_release()
        self.assertEqual(
            Release("v2.0.0", "https://github.com/chikagonight/password_manager_v2/releases/tag/v2.0.0", True),
            release,
        )
        request = self.open.call_args.args[0]
        self.assertEqual(self.api_url, request.full_url)
        self.assertIsNone(request.get_header("Authorization"))
        self.assertGreater(self.open.call_args.kwargs["timeout"], 0)

    def test_ignores_unfinished_or_incompatible_assets(self):
        self.release["assets"] = [
            {"name": "passwordSafe-Setup.exe", "state": "new", "size": 100},
            {"name": "passwordSafe-Setup.exe", "state": "uploaded", "size": 0},
            {"name": "other.exe", "state": "uploaded", "size": 100},
        ]
        self.serve(json.dumps(self.release).encode())
        self.assertFalse(self.source.latest_release().has_installer)

    def test_rejects_draft_or_prerelease(self):
        for field in ("prerelease", "draft"):
            with self.subTest(field=field), self.assertRaises(UpdateError):
                self.serve(json.dumps(self.release | {field: True}).encode())
                self.source.latest_release()

    def test_rejects_payloads_outside_the_expected_schema_or_size(self):
        for data in (b"invalid JSON", b"[]", b"{}", b'{"assets": []}', b" " * (2**20 + 1)):
            with self.subTest(length=len(data)), self.assertRaises(UpdateError):
                self.serve(data)
                self.source.latest_release()

    def test_rejects_a_redirect_outside_the_release_endpoint(self):
        self.serve(json.dumps(self.release).encode(), url="https://untrusted.example/")
        with self.assertRaises(UpdateError):
            self.source.latest_release()

    def test_404_is_not_treated_as_up_to_date(self):
        self.open.side_effect = HTTPError(self.api_url, 404, "Not Found", Message(), io.BytesIO())
        with self.assertRaisesRegex(UpdateError, "закрытым"):
            self.source.latest_release()

    def test_handles_network_timeout(self):
        self.open.side_effect = TimeoutError
        with self.assertRaisesRegex(UpdateError, "подключиться"):
            self.source.latest_release()
