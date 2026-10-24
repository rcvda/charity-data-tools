"""Unit tests for the w3w module — all HTTP mocked; no live network, no real key."""
import csv

import pytest

from charity_data_tools.w3w import W3WClient, W3WKeyMissing, enrich_csv


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return _FakeResp(self._payload)

    def close(self):
        pass


def test_key_missing(monkeypatch):
    monkeypatch.delenv("WHAT3WORDS_API_KEY", raising=False)
    with pytest.raises(W3WKeyMissing):
        W3WClient()


def test_convert_and_cache():
    sess = _FakeSession({"words": "index.home.raft"})
    c = W3WClient(api_key="x", session=sess, delay=0)
    words, err = c.convert_to_3wa(54.5, -1.5)
    assert words == "index.home.raft" and err is None
    words2, _ = c.convert_to_3wa(54.5, -1.5)
    assert words2 == "index.home.raft"
    assert sess.calls == 1


def test_convert_error():
    sess = _FakeSession({"error": {"code": "BadCoordinates", "message": "nope"}})
    c = W3WClient(api_key="x", session=sess, delay=0)
    words, err = c.convert_to_3wa(0, 0)
    assert words is None and "BadCoordinates" in err


def test_enrich_csv(tmp_path):
    src = tmp_path / "in.csv"
    out = tmp_path / "out.csv"
    with open(src, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["name", "lat", "long"])
        w.writeheader()
        w.writerow({"name": "A", "lat": "54.5", "long": "-1.5"})
        w.writerow({"name": "B", "lat": "", "long": ""})
    sess = _FakeSession({"words": "a.b.c"})
    client = W3WClient(api_key="x", session=sess, delay=0)
    summary = enrich_csv(str(src), str(out), client=client, progress=False)
    assert summary["total"] == 2 and summary["enriched"] == 1
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert rows[0]["what3words"] == "a.b.c"
    assert rows[1]["what3words"] == ""
