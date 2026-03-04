from __future__ import annotations

import contextlib
import logging
import re
import subprocess
import webbrowser
from datetime import date

from src.constants import MIME_TEXT_PLAIN


def safe_print(text: str) -> None:
    """Print text safely on Windows console by replacing unencodable chars."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


def extract_meeting_links(email_message: object, ics_text: str | None) -> list[dict[str, str]]:
    """Extract meeting URLs from ICS data and email body.

    Returns a list of dicts with 'type' and 'url' keys.
    """
    seen_urls: set[str] = set()
    links: list[dict[str, str]] = []

    _generic_paths = re.compile(
        r'^https://teams\.microsoft\.com/l/meetup-join/?$'
        r'|^https://teams\.microsoft\.com/?$'
        r'|^https://(?:[\w-]+\.)?zoom\.us/j/?$'
        r'|^https://meet\.google\.com/?$'
    )

    def _add(link_type: str, url: str) -> None:
        if url in seen_urls:
            return
        if _generic_paths.match(url):
            return
        seen_urls.add(url)
        links.append({"type": link_type, "url": url})

    # 1. ICS: X-MICROSOFT-SKYPETEAMSMEETINGURL
    if ics_text:
        skype_m = re.search(r'X-MICROSOFT-SKYPETEAMSMEETINGURL[:]([^\r\n]+)', ics_text)
        if skype_m:
            _add("Teams", skype_m.group(1).strip())

    # 2. Email plain-text body
    body = ""
    with contextlib.suppress(Exception):
        body = email_message.get_body(MIME_TEXT_PLAIN) or ""

    url_patterns = [
        ("Teams", r'https://teams\.microsoft\.com/[^\s<>"]+'),
        ("Zoom", r'https://(?:[\w-]+\.)?zoom\.us/j/[^\s<>"]+'),
        ("Google Meet", r'https://meet\.google\.com/[^\s<>"]+'),
    ]
    for link_type, pattern in url_patterns:
        for m in re.finditer(pattern, body):
            _add(link_type, m.group(0))

    # 3. ICS LOCATION (if it looks like a URL)
    if ics_text:
        loc_m = re.search(r'LOCATION[:]([^\r\n]+)', ics_text)
        if loc_m:
            loc_val = loc_m.group(1).strip()
            if loc_val.startswith("http"):
                _add("Location link", loc_val)

    return links


def list_meetings(meetings: list[dict], target: date) -> None:
    """Print a formatted list of meetings for a given date."""
    if not meetings:
        label = "today" if target == date.today() else str(target)
        print(f"\nNo meetings for {label}")
        return

    header = f"Today's meetings ({target})" if target == date.today() else f"Meetings for {target}"

    safe_print(f"\n{header}:\n")
    for m in meetings:
        start_str = m["start"].strftime("%H:%M")
        end_str = m["end"].strftime("%H:%M") if m["end"] else "??:??"
        safe_print(f"  {m['index']:>2}.  {start_str} - {end_str}  {m['subject']}")
    safe_print(f"\nTotal: {len(meetings)} meeting(s)")


def show_meeting_detail(meeting: dict) -> None:
    """Show full details for a single meeting and offer link actions."""
    m = meeting
    start_str = m["start"].strftime("%H:%M")
    end_str = m["end"].strftime("%H:%M") if m["end"] else "??:??"

    organizer = m["parsed"].get("organizer") or "(unknown)"
    location = m["parsed"].get("location") or "(none)"
    links = extract_meeting_links(m["email_message"], m["ics_text"])

    safe_print(f"\nMeeting #{m['index']}: {m['subject']}\n")
    safe_print(f"  Time:       {start_str} - {end_str}")
    safe_print(f"  Organizer:  {organizer}")
    safe_print(f"  Location:   {location}")

    if links:
        safe_print("\n  Links:")
        for i, link in enumerate(links, 1):
            safe_print(f"    {i}. {link['type']}: {link['url']}")

        safe_print("\n  [c] Copy link to clipboard")
        safe_print("  [o] Open link in browser")
        safe_print("  [a] Abort")
        choice = input("\n  > ").strip().lower()

        if choice in ("c", "o"):
            link_idx = _pick_link_index(links)
            if link_idx is None:
                return
            url = links[link_idx]["url"]
            if choice == "c":
                _copy_to_clipboard(url)
            else:
                _open_in_browser(url)
        else:
            safe_print("  Aborted.")
    else:
        safe_print("\n  Links:      (none found)")


def _pick_link_index(links: list[dict[str, str]]) -> int | None:
    """Prompt user to pick a link index (skip if only one)."""
    if len(links) == 1:
        return 0
    idx_input = input(f"  Link number [1-{len(links)}]: ").strip()
    try:
        link_idx = int(idx_input) - 1
        if link_idx < 0 or link_idx >= len(links):
            safe_print("  Invalid link number. Aborted.")
            return None
        return link_idx
    except ValueError:
        safe_print("  Invalid input. Aborted.")
        return None


logger = logging.getLogger(__name__)


def _copy_to_clipboard(url: str) -> None:
    """Copy a URL to the system clipboard."""
    try:
        subprocess.run(["clip"], input=url, text=True, check=False)
        safe_print("  Link copied to clipboard.")
    except Exception:
        logger.debug("Failed to copy to clipboard", exc_info=True)
        safe_print("  Failed to copy to clipboard.")


def _open_in_browser(url: str) -> None:
    """Open a URL in the default browser."""
    try:
        webbrowser.open(url)
        safe_print("  Link opened in browser.")
    except Exception:
        logger.debug("Failed to open browser", exc_info=True)
        safe_print("  Failed to open browser.")
