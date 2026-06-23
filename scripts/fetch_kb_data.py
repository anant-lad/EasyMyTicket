"""
One-time KB data fetcher.

Pulls content from GitHub repos, Ubuntu community wiki pages, the Ubuntu Server
docs PDF, and the AskUbuntu API.  Each raw text block is sent to an LLM (Groq
first, OpenRouter fallback) which returns a structured KB article JSON.
Valid articles are written to scripts/kb_raw_articles.json.

Usage (run from EasyMyTicket/ or project root):
    pip install requests beautifulsoup4 pypdf gitpython groq openai python-dotenv
    python scripts/fetch_kb_data.py

Reads GROQ_API_KEY and OPENROUTER_API_KEY from environment or .env file.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

# Load .env from project root (EasyMyTicket/.env)
try:
    from dotenv import load_dotenv
    _env = pathlib.Path(__file__).parent.parent / ".env"
    if _env.exists():
        load_dotenv(_env)
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
)
log = logging.getLogger("fetch_kb")

# ── Output path ───────────────────────────────────────────────────────────────

OUT_FILE = pathlib.Path(__file__).parent / "kb_raw_articles.json"
REPO_TMP = pathlib.Path("/tmp/kb_repos")

# ── Sources ───────────────────────────────────────────────────────────────────

REPOS: list[tuple[str, str]] = [
    ("cheat.sh",            "https://github.com/chubin/cheat.sh.git"),
    ("linux-cheat-sheet",   "https://github.com/sudheerj/Linux-cheat-sheet.git"),
    ("perfect-ubuntu",      "https://github.com/mikeroyal/Perfect-Ubuntu-Guide.git"),
    ("awesome-ubuntu",      "https://github.com/awesome-soft/awesome-ubuntu.git"),
]

COMMUNITY_PAGES: list[str] = [
    "https://help.ubuntu.com/community/Webcam",
    "https://help.ubuntu.com/community/WifiDocs/WirelessTroubleShooting",
    "https://help.ubuntu.com/community/BluetoothSetup",
    "https://help.ubuntu.com/community/SoundTroubleshooting",
    "https://help.ubuntu.com/community/BinaryDriverHowto/Nvidia",
    "https://help.ubuntu.com/community/Docker",
    "https://help.ubuntu.com/community/SSH/OpenSSH/Troubleshooting",
    "https://help.ubuntu.com/community/Grub2",
    "https://help.ubuntu.com/community/DiskSpace",
    "https://help.ubuntu.com/community/Python",
    "https://help.ubuntu.com/community/NetworkManager",
    "https://help.ubuntu.com/community/WifiDocs/Driver",
    "https://help.ubuntu.com/community/VideoCapture",
    "https://help.ubuntu.com/community/SoundProblems",
    "https://help.ubuntu.com/community/HardwareSupport",
    "https://help.ubuntu.com/community/Kernel",
    "https://help.ubuntu.com/community/Boot",
    "https://help.ubuntu.com/community/DiskCleanUp",
    "https://help.ubuntu.com/community/Mount",
    "https://help.ubuntu.com/community/VPN",
    "https://help.ubuntu.com/community/Firewall",
]

ASKUBUNTU_TAGS: list[str] = [
    # Hardware
    "webcam", "microphone", "audio", "sound", "bluetooth", "wifi", "ethernet",
    "usb", "hdmi", "display", "monitor", "touchpad", "keyboard", "printer", "scanner",
    # Drivers
    "nvidia", "amd-graphics", "intel-graphics", "drivers", "firmware", "kernel-module",
    # System
    "grub2", "boot", "bios", "uefi", "kernel", "systemd", "services",
    "disk", "disk-usage", "partitioning", "filesystem", "mount", "lvm",
    # Networking
    "networking", "ssh", "vpn", "firewall", "dns", "proxy", "network-manager",
    # Dev tools
    "docker", "virtualbox", "python", "nodejs", "java", "snap", "flatpak",
    # Package management
    "apt", "dpkg", "package-management", "ppa",
    # Recovery
    "freeze", "crash", "black-screen", "login-loop", "permissions", "sudo",
    "pulseaudio", "pipewire", "alsa", "xorg", "wayland", "dmesg",
]

SERVER_DOCS_PDF = "https://ubuntu.com/server/docs/_/downloads/en/latest/pdf/"

# ── Category list (for prompt validation) ─────────────────────────────────────

VALID_CATEGORIES = {
    "camera", "microphone", "audio", "bluetooth", "wifi", "ethernet", "usb",
    "hdmi", "display", "touchpad", "keyboard", "printer", "scanner",
    "nvidia", "amd-graphics", "intel-graphics", "driver", "firmware", "kernel",
    "grub", "boot", "bios", "disk", "filesystem", "mount", "lvm",
    "networking", "ssh", "vpn", "firewall", "dns", "docker", "virtualbox",
    "python", "nodejs", "java", "snap", "flatpak", "apt", "permission",
    "sudo", "freeze", "crash", "black-screen", "login-loop", "system",
    "pulseaudio", "pipewire", "alsa", "xorg", "wayland", "systemd",
}

# ── Token bucket rate limiter ─────────────────────────────────────────────────

class _TokenBucket:
    """Leaky-bucket rate limiter: refills `rate` tokens/sec up to `capacity`."""

    def __init__(self, rate: float, capacity: float):
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        self._last = time.monotonic()

    def consume(self, tokens: float = 1.0):
        now = time.monotonic()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.rate)
        self._last = now
        if self._tokens < tokens:
            wait = (tokens - self._tokens) / self.rate
            log.debug("Rate limit: sleeping %.1fs", wait)
            time.sleep(wait)
            self._tokens = 0
        else:
            self._tokens -= tokens


# Groq free tier: ~14 400 TPM for 8b, ~6 000 TPM for 70b.
# We estimate ~400 tokens per call (prompt ~300 + output ~100).
# 14 400 TPM ÷ 400 ≈ 36 calls/min → ~1.7 s/call → rate = 0.55 calls/s
# Add margin → rate = 0.4 calls/s (one call every 2.5s)
_groq_bucket    = _TokenBucket(rate=0.4, capacity=3)
# OpenRouter free tier is more lenient but we still throttle gently
_openrouter_bucket = _TokenBucket(rate=0.8, capacity=5)


# ── Pre-filter ─────────────────────────────────────────────────────────────────

# Keywords that strongly suggest actionable troubleshooting content
_FILTER_KEYWORDS = {
    "sudo", "apt", "apt-get", "dpkg", "systemctl", "journalctl", "dmesg",
    "modprobe", "rmmod", "lsmod", "nmcli", "iwconfig", "rfkill",
    "ffmpeg", "v4l2", "pactl", "pulseaudio", "pipewire", "wireplumber",
    "xrandr", "nvidia", "lspci", "lsusb", "uname", "chmod", "chown",
    "mount", "umount", "fdisk", "lsblk", "df ", "du ", "fsck",
    "iptables", "ufw", "ssh-keygen", "sshd", "docker", "pip", "pip3",
    "kernel", "driver", "error", "failed", "fix", "install", "reinstall",
    "restart", "reboot", "not working", "doesn't work", "broken", "missing",
    "permission denied", "no such", "cannot", "could not", "/dev/",
}

def _pre_filter_block(text: str) -> bool:
    """Return True if block looks like actionable troubleshooting content."""
    lower = text.lower()
    # Must be long enough to be useful
    if len(text.strip()) < 120:
        return False
    # Must contain at least 2 troubleshooting keywords
    hits = sum(1 for kw in _FILTER_KEYWORDS if kw in lower)
    return hits >= 2


# ── LLM structuring ───────────────────────────────────────────────────────────

_STRUCT_SYSTEM = "You are a Linux KB writer. Output ONLY valid JSON, no markdown."

_STRUCT_PROMPT = """\
Convert this Linux troubleshooting content into a KB article JSON:
{{"title":"str","category":"camera|microphone|audio|bluetooth|wifi|ethernet|usb|hdmi|display|touchpad|keyboard|printer|scanner|nvidia|amd-graphics|intel-graphics|driver|firmware|kernel|grub|boot|bios|disk|filesystem|mount|lvm|networking|ssh|vpn|firewall|dns|docker|virtualbox|python|nodejs|java|snap|flatpak|apt|permission|sudo|freeze|crash|black-screen|login-loop|pulseaudio|pipewire|alsa|xorg|wayland|systemd|system","symptoms":"str","diagnostics":"shell cmds to diagnose","root_causes":"str","fix_steps":"shell cmds to fix","verification":"shell cmd proving fix worked — must print OK/FAIL"}}
Return null if not actionable troubleshooting. fix_steps and verification are required.

Content:
{raw_text}
"""


# Track if we should prefer OpenRouter (after repeated Groq 429s)
_groq_fail_streak = 0
_GROQ_STREAK_THRESHOLD = 3  # after this many consecutive 429s, prefer OpenRouter


def _call_groq(messages: list, groq_client) -> Optional[str]:
    """Try Groq once with rate-bucket throttle; fail fast on 429."""
    global _groq_fail_streak
    _groq_bucket.consume(1)
    try:
        resp = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",  # higher TPM quota than 70b
            messages=messages,
            temperature=0.1,
            max_tokens=600,
        )
        _groq_fail_streak = 0
        return resp.choices[0].message.content.strip()
    except Exception as e:
        msg = str(e).lower()
        if "rate" in msg or "429" in msg or "quota" in msg:
            _groq_fail_streak += 1
            log.debug("Groq 429 (streak=%d) — routing to OpenRouter", _groq_fail_streak)
        else:
            log.debug("Groq error: %s", e)
        return None


def _call_openrouter(messages: list, or_client) -> Optional[str]:
    if or_client is None:
        return None
    _openrouter_bucket.consume(1)
    for attempt in range(3):
        try:
            resp = or_client.chat.completions.create(
                model="mistralai/mistral-7b-instruct:free",
                messages=messages,
                temperature=0.1,
                max_tokens=600,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            msg = str(e).lower()
            if ("rate" in msg or "429" in msg) and attempt < 2:
                wait = 5 * (2 ** attempt)
                log.warning("OpenRouter rate-limit attempt=%d — waiting %ds", attempt + 1, wait)
                time.sleep(wait)
                continue
            log.debug("OpenRouter error: %s", e)
            break
    return None


def _structure_block(raw_text: str, groq_client, or_client) -> Optional[dict]:
    """Send a raw block to LLM, return structured dict or None."""
    global _groq_fail_streak
    raw_text = raw_text[:1500].strip()  # ~375 tokens max — keeps prompt small
    if not _pre_filter_block(raw_text):
        return None

    messages = [
        {"role": "system", "content": _STRUCT_SYSTEM},
        {"role": "user", "content": _STRUCT_PROMPT.format(raw_text=raw_text)},
    ]

    # If Groq has been failing repeatedly, skip straight to OpenRouter
    content = None
    if _groq_fail_streak < _GROQ_STREAK_THRESHOLD:
        content = _call_groq(messages, groq_client)
    else:
        log.debug("Groq streak=%d — using OpenRouter directly", _groq_fail_streak)

    if content is None:
        content = _call_openrouter(messages, or_client)
        # If OpenRouter succeeded, ease Groq back in next time
        if content is not None:
            _groq_fail_streak = max(0, _groq_fail_streak - 1)
    if content is None:
        return None

    # Strip markdown fences
    content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.MULTILINE)
    content = re.sub(r"\s*```$", "", content, flags=re.MULTILINE).strip()

    if content.lower().strip() == "null":
        return None

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
            except json.JSONDecodeError:
                return None
        else:
            return None

    if not isinstance(data, dict):
        return None

    # Validate required fields
    if not data.get("fix_steps") or not data.get("verification"):
        return None
    if not data.get("title") or not data.get("category"):
        return None

    # Normalise category
    cat = data.get("category", "system").lower().strip()
    if cat not in VALID_CATEGORIES:
        cat = "system"
    data["category"] = cat
    data["source"] = data.get("source", "fetch_script")
    return data


# ── Text splitting ─────────────────────────────────────────────────────────────

def _split_markdown(text: str, min_len: int = 150) -> list[str]:
    """Split markdown by H2/H3 headings into blocks."""
    blocks = re.split(r"\n#{2,3} ", text)
    result = []
    for b in blocks:
        b = b.strip()
        if len(b) >= min_len:
            result.append(b[:4000])
    return result


# ── GitHub repos ──────────────────────────────────────────────────────────────

def _clone_repos() -> list[pathlib.Path]:
    REPO_TMP.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, url in REPOS:
        dest = REPO_TMP / name
        if dest.exists():
            log.info("Repo already cloned: %s", name)
        else:
            log.info("Cloning %s ...", url)
            try:
                subprocess.run(
                    ["git", "clone", "--depth=1", url, str(dest)],
                    check=True, capture_output=True, timeout=120
                )
                log.info("Cloned %s", name)
            except subprocess.CalledProcessError as e:
                log.warning("Clone failed for %s: %s", name, e.stderr.decode()[:200])
                continue
        paths.append(dest)
    return paths


def _extract_repo_blocks(repo_paths: list[pathlib.Path]) -> list[str]:
    blocks = []
    for repo in repo_paths:
        for md_path in repo.rglob("*.md"):
            try:
                text = md_path.read_text(errors="replace")
                blocks.extend(_split_markdown(text))
            except Exception:
                pass

        # cheat.sh has plain text sheets under sheets/
        sheets_dir = repo / "sheets"
        if sheets_dir.exists():
            for sheet in sheets_dir.iterdir():
                if sheet.is_file():
                    try:
                        text = sheet.read_text(errors="replace")
                        if len(text) >= 80:
                            blocks.append(f"# {sheet.name}\n{text[:3000]}")
                    except Exception:
                        pass
    log.info("Extracted %d blocks from repos", len(blocks))
    return blocks


# ── Community wiki pages ───────────────────────────────────────────────────────

def _fetch_community_pages() -> list[str]:
    blocks = []
    sess = requests.Session()
    sess.headers["User-Agent"] = "EasyMyTicket-KB-Fetcher/1.0"
    for url in COMMUNITY_PAGES:
        try:
            resp = sess.get(url, timeout=20)
            if resp.status_code != 200:
                log.warning("Community page %s -> %d", url, resp.status_code)
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            # Ubuntu wiki uses div#moin-content or #page-content
            main = (
                soup.find("div", id="moin-content")
                or soup.find("div", id="page-content")
                or soup.find("div", class_="wiki-content")
                or soup.find("article")
                or soup.body
            )
            text = main.get_text(separator="\n", strip=True) if main else ""
            if len(text) > 150:
                blocks.append(f"# Ubuntu Community: {url.split('/')[-1]}\n{text[:4000]}")
                log.info("Fetched community page: %s (%d chars)", url.split("/")[-1], len(text))
            time.sleep(0.5)
        except Exception as e:
            log.warning("Failed to fetch %s: %s", url, e)
    log.info("Extracted %d blocks from community pages", len(blocks))
    return blocks


# ── Ubuntu Server Docs PDF ────────────────────────────────────────────────────

def _fetch_server_docs_pdf() -> list[str]:
    pdf_path = REPO_TMP / "ubuntu_server_docs.pdf"
    if not pdf_path.exists():
        log.info("Downloading Ubuntu Server docs PDF ...")
        try:
            resp = requests.get(SERVER_DOCS_PDF, timeout=120, stream=True)
            if resp.status_code == 200:
                with open(pdf_path, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                log.info("PDF downloaded: %.1f MB", pdf_path.stat().st_size / 1e6)
            else:
                log.warning("PDF download returned %d", resp.status_code)
                return []
        except Exception as e:
            log.warning("PDF download failed: %s", e)
            return []

    try:
        from pypdf import PdfReader
    except ImportError:
        log.warning("pypdf not installed — skipping PDF extraction (pip install pypdf)")
        return []

    blocks = []
    try:
        reader = PdfReader(str(pdf_path))
        full_text = "\n".join(
            page.extract_text() or "" for page in reader.pages
        )
        # Split by likely section headings
        sections = re.split(r"\n([A-Z][^\n]{5,60})\n", full_text)
        for section in sections:
            if len(section.strip()) >= 200:
                blocks.append(section.strip()[:4000])
        log.info("Extracted %d sections from PDF (%d pages)", len(blocks), len(reader.pages))
    except Exception as e:
        log.warning("PDF extraction failed: %s", e)
    return blocks


# ── AskUbuntu API ─────────────────────────────────────────────────────────────

def _fetch_askubuntu(tags: list[str], per_tag: int = 20) -> list[str]:
    blocks = []
    sess = requests.Session()
    for tag in tags:
        try:
            resp = sess.get(
                "https://api.stackexchange.com/2.3/questions",
                params={
                    "tagged": tag,
                    "site": "askubuntu",
                    "sort": "votes",
                    "order": "desc",
                    "pagesize": per_tag,
                    "filter": "withbody",
                },
                timeout=20,
            )
            if resp.status_code != 200:
                log.warning("AskUbuntu API tag=%s -> %d", tag, resp.status_code)
                continue
            data = resp.json()
            items = data.get("items", [])
            for item in items:
                title = item.get("title", "")
                body = BeautifulSoup(item.get("body", ""), "html.parser").get_text()
                text = f"Q: {title}\n\n{body[:2000]}"
                if len(text) >= 150:
                    blocks.append(text)
            log.info("AskUbuntu tag=%s: %d questions", tag, len(items))
            time.sleep(0.3)  # StackExchange rate limit
        except Exception as e:
            log.warning("AskUbuntu tag=%s failed: %s", tag, e)
    log.info("Total AskUbuntu blocks: %d", len(blocks))
    return blocks


# ── LLM clients ───────────────────────────────────────────────────────────────

def _init_clients():
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_key:
        log.error("GROQ_API_KEY not set — cannot structure articles")
        sys.exit(1)

    from groq import Groq
    groq_client = Groq(api_key=groq_key)

    or_client = None
    or_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if or_key:
        try:
            from openai import OpenAI
            or_client = OpenAI(
                api_key=or_key,
                base_url="https://openrouter.ai/api/v1",
                default_headers={"HTTP-Referer": "https://easymyticket.app", "X-Title": "EasyMyTicket"},
            )
            log.info("OpenRouter fallback client ready")
        except ImportError:
            log.warning("openai package not installed — no OpenRouter fallback")
    else:
        log.warning("OPENROUTER_API_KEY not set — Groq rate-limit has no fallback")

    return groq_client, or_client


# ── Dedup ─────────────────────────────────────────────────────────────────────

def _dedup(articles: list[dict]) -> list[dict]:
    seen: set[str] = set()
    result = []
    for a in articles:
        key = a.get("title", "").lower().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(a)
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=== EasyMyTicket KB Data Fetcher ===")

    groq_client, or_client = _init_clients()

    # 1. Collect raw blocks from all sources
    all_blocks: list[str] = []

    log.info("--- Phase 1: GitHub repos ---")
    repo_paths = _clone_repos()
    all_blocks.extend(_extract_repo_blocks(repo_paths))

    log.info("--- Phase 2: Ubuntu community pages ---")
    all_blocks.extend(_fetch_community_pages())

    log.info("--- Phase 3: Ubuntu Server docs PDF ---")
    all_blocks.extend(_fetch_server_docs_pdf())

    log.info("--- Phase 4: AskUbuntu API ---")
    all_blocks.extend(_fetch_askubuntu(ASKUBUNTU_TAGS))

    log.info("Total raw blocks: %d", len(all_blocks))

    # 2. Deduplicate blocks by first 200 chars
    seen_blocks: set[str] = set()
    unique_blocks = []
    for b in all_blocks:
        sig = b[:200].strip().lower()
        if sig not in seen_blocks and len(b.strip()) >= 80:
            seen_blocks.add(sig)
            unique_blocks.append(b)
    log.info("Unique blocks after dedup: %d", len(unique_blocks))

    # 3. Pre-filter before hitting the LLM — skip non-troubleshooting content
    filtered_blocks = [b for b in unique_blocks if _pre_filter_block(b)]
    log.info("Blocks passing pre-filter: %d / %d (%.0f%% skipped without LLM call)",
             len(filtered_blocks), len(unique_blocks),
             100 * (1 - len(filtered_blocks) / max(len(unique_blocks), 1)))

    # 4. Structure via LLM
    articles: list[dict] = []
    errors = 0
    for i, block in enumerate(filtered_blocks):
        if i % 25 == 0:
            log.info("LLM structuring %d/%d (articles: %d, skipped: %d)",
                     i, len(filtered_blocks), len(articles), errors)
        article = _structure_block(block, groq_client, or_client)
        if article:
            articles.append(article)
        else:
            errors += 1
        # No extra sleep — token bucket in _call_groq/_call_openrouter handles pacing

    log.info("Structured: %d valid articles, %d skipped/failed", len(articles), errors)

    # 4. Dedup by title
    articles = _dedup(articles)
    log.info("After title dedup: %d articles", len(articles))

    # 5. Write output
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)

    log.info("Written %d articles to %s", len(articles), OUT_FILE)

    # Print summary by category
    from collections import Counter
    cats = Counter(a.get("category", "unknown") for a in articles)
    log.info("Category breakdown:")
    for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
        log.info("  %-20s %d", cat, count)


if __name__ == "__main__":
    main()
