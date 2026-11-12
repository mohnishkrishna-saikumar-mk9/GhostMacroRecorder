from src import updater


def test_parse_version():
    assert updater.parse_version("v1.2.10") == (1, 2, 10)
    assert updater.parse_version("1.0") == (1, 0)
    assert updater.parse_version("") == (0,)


def test_is_newer():
    assert updater.is_newer("v1.0.2", "1.0.1")
    assert updater.is_newer("v1.1", "1.0.9")
    assert updater.is_newer("2.0.0", "1.9.9")
    assert not updater.is_newer("v1.0.1", "1.0.1")
    assert not updater.is_newer("v1.0", "1.0.0")
    assert not updater.is_newer("v1.0.0", "1.0.1")


def test_short_notes_skips_boilerplate():
    body = "## What's Changed\n- Adds updates\n* Smoother window\n\n**Full Changelog**: x"
    assert updater.short_notes(body) == "• Adds updates\n• Smoother window"


def test_check_latest_ignores_foreign_download_urls(monkeypatch):
    import io
    import json

    data = {
        "tag_name": "v99.0.0",
        "assets": [{"name": updater.ASSET, "browser_download_url": "https://evil.example/x.exe", "size": 1}],
    }

    class Res(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(updater, "_get", lambda url, timeout=8.0: Res(json.dumps(data).encode()))
    assert updater.check_latest() is None

    data["assets"][0]["browser_download_url"] = (
        f"https://github.com/{updater.REPO}/releases/download/v99.0.0/{updater.ASSET}"
    )
    info = updater.check_latest()
    assert info is not None and info.version == "99.0.0"
