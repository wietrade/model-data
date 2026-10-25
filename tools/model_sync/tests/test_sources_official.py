"""官方模型列表接口的回归测试（不联网，打桩 ``_get_json``）。"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from model_sync import sources  # noqa: E402


def _payload(names, token=None):
    data = {"models": [{"name": "models/" + n, "displayName": n} for n in names]}
    if token:
        data["nextPageToken"] = token
    return data


class GooglePaginationTest(unittest.TestCase):
    def test_key_goes_into_header_not_url(self):
        calls = []

        def fake_get_json(url, timeout=30, headers=None):
            calls.append((url, dict(headers or {})))
            return _payload(["gemini-4-argon"])

        with mock.patch.object(sources, "_get_json", fake_get_json):
            sources._official_google("SECRET", timeout=5)

        url, headers = calls[0]
        self.assertNotIn("SECRET", url)
        self.assertEqual(headers.get("x-goog-api-key"), "SECRET")

    def test_follows_next_page_token(self):
        pages = [
            _payload(["a-1", "a-2"], token="tok/2"),
            _payload(["b-1"]),
        ]
        urls = []

        def fake_get_json(url, timeout=30, headers=None):
            urls.append(url)
            return pages[len(urls) - 1]

        with mock.patch.object(sources, "_get_json", fake_get_json):
            out = sources._official_google("SECRET", timeout=5)

        self.assertEqual([m.source_id for m in out], ["a-1", "a-2", "b-1"])
        self.assertIn("pageToken=tok%2F2", urls[1])

    def test_stops_on_repeated_token(self):
        def fake_get_json(url, timeout=30, headers=None):
            return _payload(["x"], token="same")

        with mock.patch.object(sources, "_get_json", fake_get_json):
            out = sources._official_google("SECRET", timeout=5)

        self.assertEqual(len(out), 20)  # 循环上限，不死循环


if __name__ == "__main__":
    unittest.main()
