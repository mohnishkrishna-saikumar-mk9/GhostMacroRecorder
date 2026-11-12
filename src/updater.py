"""Update check and one-click update from GitHub Releases.

The only network traffic the app makes. It asks GitHub's public releases API which
version is newest (nothing about the user or their macros is sent), and, only when the
user clicks Update, downloads the installer over HTTPS and runs it.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Callable, Optional
import urllib.request

from src.app_paths import APP_SLUG, APP_VERSION

REPO = "mohnishkrishna-saikumar-mk9/GhostMacroRecorder"
ASSET = "GhostMacroRecorder-Setup.exe"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
USER_AGENT = f"{APP_SLUG}-updater/{APP_VERSION}"
CHECK_EVERY = 20 * 3600  # seconds between automatic checks


@dataclass
class UpdateInfo:
    version: str
    notes: str
    page_url: str
    download_url: str
    size: int


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.10' -> (1, 2, 10). Anything that isn't a number is ignored."""
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(latest: str, current: str = APP_VERSION) -> bool:
    a, b = parse_version(latest), parse_version(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def short_notes(body: str, limit: int = 4) -> str:
    lines = []
    for line in (body or "").splitlines():
        line = re.sub(r"^[#>*\-\s]+", "", line).strip()
        if line and not re.match(r"(?i)^(full changelog|what's changed|new contributors)", line):
            lines.append(line)
        if len(lines) >= limit:
            break
    return "\n".join(f"• {l}" for l in lines)


def _get(url: str, timeout: float = 8.0):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - fixed https URL


def check_latest() -> Optional[UpdateInfo]:
    """Return the newest release if it is newer than this app, else None. Raises on network errors."""
    with _get(API_LATEST) as res:
        data = json.loads(res.read().decode("utf-8"))
    tag = str(data.get("tag_name", ""))
    if not tag or data.get("draft") or data.get("prerelease") or not is_newer(tag):
        return None
    asset = next((a for a in data.get("assets", []) if a.get("name") == ASSET), None)
    if not asset:
        return None
    url = str(asset.get("browser_download_url", ""))
    if not url.startswith(f"https://github.com/{REPO}/releases/download/"):
        return None
    return UpdateInfo(
        version=tag.lstrip("vV"),
        notes=short_notes(str(data.get("body", ""))),
        page_url=str(data.get("html_url") or RELEASES_PAGE),
        download_url=url,
        size=int(asset.get("size") or 0),
    )


def download(info: UpdateInfo, on_progress: Callable[[float], None], should_stop: Callable[[], bool] = lambda: False) -> Path:
    """Download the installer to a fresh temp folder; returns its path. Checks the size."""
    folder = Path(tempfile.mkdtemp(prefix=f"{APP_SLUG}-update-"))
    target = folder / ASSET
    got = 0
    with _get(info.download_url, timeout=30) as res, open(target, "wb") as out:
        total = int(res.headers.get("Content-Length") or info.size or 0)
        while True:
            if should_stop():
                raise RuntimeError("Download cancelled.")
            chunk = res.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            got += len(chunk)
            if total:
                on_progress(min(1.0, got / total))
    if info.size and got != info.size:
        target.unlink(missing_ok=True)
        raise RuntimeError("The download was incomplete. Try again.")
    return target


def run_installer(path: Path) -> None:
    """Start the installer quietly; it closes this app, updates it and opens it again."""
    args = [str(path), "/SILENT", "/SP-", "/NOCANCEL", "/CLOSEAPPLICATIONS", "/NORESTART"]
    if os.name == "nt":
        import ctypes

        # ShellExecute so Windows shows the normal admin (UAC) prompt for Program Files.
        params = subprocess.list2cmdline(args[1:])
        rc = ctypes.windll.shell32.ShellExecuteW(None, "open", args[0], params, str(path.parent), 1)
        if rc <= 32:
            raise RuntimeError("Windows did not start the installer.")
    else:  # pragma: no cover - the app is Windows-only
        subprocess.Popen(args)
