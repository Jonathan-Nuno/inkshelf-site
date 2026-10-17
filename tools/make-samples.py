#!/usr/bin/env python3
"""Build the Inkshelf sample comics (CBZ) from their licensed sources.

Run from the repository root with an interpreter that has Pillow (12.x):

    ~/.local/share/codex-skills/image-tools/venv/bin/python -I tools/make-samples.py 2>&1 | tee make-samples.log

What it does
  1. Downloads (only from the sources listed below) the English hi-res pages of
     Pepper&Carrot episodes 1 and 2 and the JPEG 2000 page images of one Hokusai Manga
     volume from the Smithsonian Libraries, into `cache/` (git-ignored). Each download's
     URL, size and SHA-256 goes to the log and to `samples/MANIFEST.json`.
  2. Re-checks the licence statements on the source pages and records the page hashes.
  3. Builds `samples/*.cbz`: pages stored (not deflated), `ComicInfo.xml` and `LICENSE.txt`
     at the archive root.
  4. Re-opens every archive and checks entries, compression method and ComicInfo fields.

Downloaded files are treated as data: they are never executed or extracted to disk. JPEGs
and JPEG 2000 images are decoded in memory by Pillow only.

Options
  --refresh               ignore `cache/` and download everything again
  --hokusai-volume N      Smithsonian Libraries Hokusai Manga volume (default 5)
  --contact-sheets DIR    also write numbered contact sheets of every Hokusai page (for the
                          page-by-page content check) into DIR
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from html import unescape
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFile, features

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
SAMPLES = ROOT / "samples"
MANIFEST = SAMPLES / "MANIFEST.json"

USER_AGENT = "inkshelf-site-make-samples/1.0 (+https://jonathan-nuno.github.io/inkshelf-site/)"
ARCHIVE_LIMIT = 30 * 1024 * 1024          # each CBZ stays under 30 MB
ZIP_DATE = (2026, 10, 16, 0, 0, 0)         # fixed, so rebuilt archives are byte-identical
MAX_DOWNLOAD = 150 * 1024 * 1024           # refuse anything larger than this

# --------------------------------------------------------------------------------------
# Sources. Network use is limited to these hosts (redirects are checked as well).
# --------------------------------------------------------------------------------------
PC_HOST = "www.peppercarrot.com"
SI_HOST = "library.si.edu"
PC_BASE = f"https://{PC_HOST}/0_sources"
PC_LICENCE_PAGE = f"https://{PC_HOST}/en/about/index.html"
SI_COPYRIGHT_PAGE = f"https://{SI_HOST}/copyright"

CREDIT_LINE = "© David Revoy, www.peppercarrot.com, CC BY 4.0"
CC_BY_URL = "https://creativecommons.org/licenses/by/4.0/"
CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"

# English hi-res files are `en_Pepper-and-Carrot_by-David-Revoy_E<NN><page>.jpg`.
# The story pages only: `P00` is the 2481 x 663 title banner and, in episode 1, `P04` is a
# 2481 x 50 decorative divider; `E<NN>.jpg` is the 1100 x 765 cover thumbnail. None of
# those is a page of the story, so they are not downloaded or packaged (the title is in
# ComicInfo.xml). Episode 2's `P06` is the 2481 x 900 credits panel and is kept.
EPISODES = {
    1: {
        "dir": "ep01_Potion-of-Flight",
        "code": "E01",
        "title": "Episode 1: The Potion of Flight",
        "pages": ["P01", "P02", "P03"],
        "min_height": 3000,
    },
    2: {
        "dir": "ep02_Rainbow-potions",
        "code": "E02",
        "title": "Episode 2: Rainbow Potions",
        "pages": ["P01", "P02", "P03", "P04", "P05", "P06"],
        "min_height": 800,
    },
}
PC_PAGE_WIDTH = 2481

STRIP_WIDTH = 800
STRIP_PAGES_PER_IMAGE = 2     # at most 4 (so no image is taller than 4 x 1130 px)
STRIP_JPEG_QUALITY = 85

HOKUSAI_MAX_SIDE = 1600       # long side of the converted pages
HOKUSAI_JPEG_QUALITY = 85
# Zip members (sorted position, 0-based) left out of the Hokusai archive, with the reason.
# Filled in after the page-by-page content check (see README.md, "Content check").
HOKUSAI_EXCLUDE: dict[int, str] = {}
# What the page-by-page check of volume 5 found (2026-10-16); copied into MANIFEST.json.
HOKUSAI_CONTENT_CHECK = (
    "Volume 5 (hokusaimangav5kats): all 35 scan images (indices 0-34) were viewed one by one on "
    "numbered contact sheets (--contact-sheets); plates 9, 21 and 27, which show figures in "
    "loincloths, were also viewed enlarged. Contents: front and back cover (0, 34), front matter "
    "and title pages (1, 2), deity and court portraits (3, 18-20, 24, 25, 28, 29), shrine gates, "
    "bells, temple roofs and buildings (4-8, 11-17), guardian demons and a priest (9, 10), wrestlers "
    "(21), Mount Fuji and waves (23, 26), a hungry-ghost demon (27) and the publisher's catalogue "
    "(30-33). No nude figures and no bawdy or erotic plates were found, so volume 5 is used with "
    "no pages left out."
)

ALLOWED_HOSTS = {PC_HOST, SI_HOST}

# `retrieved_utc` of downloads made by an earlier run, so a cached rerun keeps the real time.
PRIOR_RETRIEVED: dict[str, str] = {}


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def log(message: str = "") -> None:
    print(message, flush=True)


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def host_allowed(url: str, extra_suffix: str | None = None) -> bool:
    host = urllib.parse.urlsplit(url).hostname or ""
    if host in ALLOWED_HOSTS:
        return True
    return bool(extra_suffix) and (host == extra_suffix or host.endswith("." + extra_suffix))


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, extra_suffix: str | None) -> None:
        self.extra_suffix = extra_suffix

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        if not newurl.startswith("https://") or not host_allowed(newurl, self.extra_suffix):
            raise urllib.error.URLError(f"redirect to a host that is not approved: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url: str, dest: Path, *, refresh: bool, extra_suffix: str | None = None,
          expect_types: tuple[str, ...] = ()) -> dict:
    """Download `url` to `dest` (unless cached) and return its record."""
    if not url.startswith("https://") or not host_allowed(url, extra_suffix):
        raise SystemExit(f"refusing to fetch {url}: host not approved")
    dest.parent.mkdir(parents=True, exist_ok=True)
    cached = dest.exists() and not refresh
    info: dict = {"url": url, "file": str(dest.relative_to(ROOT))}
    if cached:
        info["source"] = "cache"
    else:
        opener = urllib.request.build_opener(_CheckedRedirects(extra_suffix))
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        temp = dest.with_suffix(dest.suffix + ".part")
        try:
            with opener.open(request, timeout=180) as response:
                status = response.status
                content_type = response.headers.get_content_type()
                declared = response.headers.get("Content-Length")
                if status != 200:
                    raise SystemExit(f"{url}: HTTP {status}")
                if expect_types and content_type not in expect_types:
                    raise SystemExit(f"{url}: unexpected content type {content_type}")
                if declared and int(declared) > MAX_DOWNLOAD:
                    raise SystemExit(f"{url}: {declared} bytes is more than the {MAX_DOWNLOAD} limit")
                total = 0
                with temp.open("wb") as out:
                    while True:
                        block = response.read(1 << 20)
                        if not block:
                            break
                        total += len(block)
                        if total > MAX_DOWNLOAD:
                            raise SystemExit(f"{url}: download exceeded {MAX_DOWNLOAD} bytes")
                        out.write(block)
                if declared and total != int(declared):
                    raise SystemExit(f"{url}: got {total} bytes, expected {declared}")
                info["content_type"] = content_type
                info["last_modified"] = response.headers.get("Last-Modified")
                info["final_url"] = response.geturl()
        except (urllib.error.URLError, TimeoutError) as error:
            temp.unlink(missing_ok=True)
            raise SystemExit(f"{url}: download failed ({error}); stopping, no substitute source")
        temp.replace(dest)
        info["source"] = "downloaded"
        info["retrieved_utc"] = utc_now()
    if cached:
        info["retrieved_utc"] = PRIOR_RETRIEVED.get(url, "unknown (cached before this manifest)")
    info["bytes"] = dest.stat().st_size
    info["sha256"] = sha256_of(dest)
    log(f"  {info['source']:10s} {info['bytes']:>10,d} B  sha256 {info['sha256']}  {url}")
    return info


def page_text(path: Path) -> str:
    """Visible text of a downloaded HTML page, whitespace collapsed."""
    raw = path.read_bytes().decode("utf-8", errors="replace")
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    text = unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"\s+", " ", text)


def decode_jpeg(data: bytes, name: str) -> Image.Image:
    if not data.startswith(b"\xff\xd8\xff"):
        raise SystemExit(f"{name}: not a JPEG")
    probe = Image.open(io.BytesIO(data))
    if probe.format != "JPEG":
        raise SystemExit(f"{name}: not a JPEG ({probe.format})")
    probe.verify()
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def write_cbz(path: Path, entries: list[tuple[str, bytes]]) -> None:
    """Pages first, stored (not deflated), then metadata; fixed timestamps."""
    temp = path.with_suffix(".cbz.part")
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in entries:
            member = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            member.compress_type = zipfile.ZIP_STORED
            member.create_system = 3
            member.external_attr = 0o644 << 16
            archive.writestr(member, data)
    if temp.stat().st_size > ARCHIVE_LIMIT:
        size = temp.stat().st_size
        temp.unlink()
        raise SystemExit(f"{path.name}: {size:,} bytes is over the 30 MB limit")
    temp.replace(path)


def comic_info(fields: list[tuple[str, str]]) -> bytes:
    """ComicInfo.xml with elements in the schema's order; values XML-escaped."""
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<ComicInfo>"]
    lines += [f"  <{tag}>{escape(value)}</{tag}>" for tag, value in fields]
    lines += ["</ComicInfo>", ""]
    return "\n".join(lines).encode("utf-8")


def jpeg_bytes(image: Image.Image, quality: int) -> bytes:
    buffer = io.BytesIO()
    # No EXIF/ICC/XMP: the image header (SOF) must sit in the first bytes of the entry.
    image.convert("RGB").save(buffer, "JPEG", quality=quality, optimize=True, progressive=False)
    return buffer.getvalue()


# --------------------------------------------------------------------------------------
# Licence statements
# --------------------------------------------------------------------------------------
def check_licences(refresh: bool, hokusai_page_url: str, volume: int) -> list[dict]:
    log("Licence pages (re-checked before use)")
    records = []

    info = fetch(PC_LICENCE_PAGE, CACHE / "licence" / "peppercarrot-about.html", refresh=True,
                 expect_types=("text/html",))
    text = page_text(ROOT / info["file"])
    needles = [
        "Pepper&Carrot webcomics, translations and artworks are licensed under a Creative Commons Attribution 4.0 International license unless otherwise noted",
        "Copyright © David Revoy",
        "AI derivation prohibited",
    ]
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"licence check failed on {PC_LICENCE_PAGE}: missing {needle!r}")
    info["quoted"] = needles[0]
    info["also_states"] = ["AI derivation prohibited"]
    records.append(info)

    info = fetch(hokusai_page_url, CACHE / "licence" / f"si-hokusai-v{volume}.html", refresh=True,
                 expect_types=("text/html",))
    text = page_text(ROOT / info["file"])
    needles = [
        f"Hokusai manga v. {volume}",
        "CC0 — Creative Commons (CC0 1.0) This content is in the public domain (free of copyright restrictions). You can copy, modify, and distribute this work without contacting the Smithsonian.",
        "No Copyright - United States",
    ]
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"licence check failed on {hokusai_page_url}: missing {needle!r}")
    info["quoted"] = needles[1]
    records.append(info)

    info = fetch(SI_COPYRIGHT_PAGE, CACHE / "licence" / "si-copyright.html", refresh=True,
                 expect_types=("text/html",))
    text = page_text(ROOT / info["file"])
    needle = 'We ask that an attribution statement such as "Courtesy of the Smithsonian Libraries and Archives" is used, along with a link back to the original source on our site.'
    if needle not in text:
        raise SystemExit(f"licence check failed on {SI_COPYRIGHT_PAGE}: attribution request not found")
    info["quoted"] = needle
    records.append(info)
    return records


# --------------------------------------------------------------------------------------
# Pepper&Carrot
# --------------------------------------------------------------------------------------
def pc_url(episode: dict, page: str) -> str:
    return f"{PC_BASE}/{episode['dir']}/hi-res/en_Pepper-and-Carrot_by-David-Revoy_{episode['code']}{page}.jpg"


def pc_licence_text(episode_title: str, source_dir_url: str, page_urls: list[str], changes: list[str]) -> bytes:
    lines = [
        f"Pepper&Carrot, {episode_title}",
        CREDIT_LINE,
        "",
        "Licence: Creative Commons Attribution 4.0 International (CC BY 4.0)",
        f"Licence text: {CC_BY_URL}legalcode",
        "",
        "Source: " + source_dir_url,
        "Page files (English, hi-res):",
        *[f"  {url}" for url in page_urls],
        "",
        "Licence statement on the source site (https://www.peppercarrot.com/en/about/index.html#license):",
        '  "Pepper&Carrot webcomics, translations and artworks are licensed under a Creative',
        '  Commons Attribution 4.0 International license unless otherwise noted"',
        '  The same page also carries the notice "AI derivation prohibited".',
        "",
        "Changes made:",
        *[f"  {change}" for change in changes],
        "",
        "Packaged for the Inkshelf sample library: https://jonathan-nuno.github.io/inkshelf-site/samples.html",
        "This package is not affiliated with or endorsed by David Revoy; the Pepper&Carrot name",
        "is used only to identify the work.",
        "",
    ]
    return "\n".join(lines).encode("utf-8")


def build_pepper_carrot(refresh: bool) -> tuple[list[dict], list[dict], dict[int, list[tuple[str, bytes]]]]:
    downloads: list[dict] = []
    samples: list[dict] = []
    pages_by_episode: dict[int, list[tuple[str, bytes]]] = {}
    for number, episode in EPISODES.items():
        log(f"Pepper&Carrot episode {number}: {episode['title']}")
        page_urls = [pc_url(episode, page) for page in episode["pages"]]
        pages: list[tuple[str, bytes]] = []
        for page, url in zip(episode["pages"], page_urls):
            dest = CACHE / "pepper-carrot" / f"ep{number:02d}" / url.rsplit("/", 1)[1]
            info = fetch(url, dest, refresh=refresh, expect_types=("image/jpeg",))
            data = dest.read_bytes()
            image = decode_jpeg(data, dest.name)
            width, height = image.size
            if width != PC_PAGE_WIDTH or height < episode["min_height"]:
                raise SystemExit(f"{dest.name}: unexpected size {width}x{height}")
            info.update(sample=f"pepper-carrot-ep{number:02d}", page=page, width=width, height=height,
                        icc_profile=image.info.get("icc_profile") is not None)
            downloads.append(info)
            pages.append((dest.name, data))
        pages_by_episode[number] = pages

        entries = [(f"{index:03d}.jpg", data) for index, (_, data) in enumerate(pages, start=1)]
        source_dir = f"{PC_BASE}/{episode['dir']}/hi-res/"
        entries.append(("ComicInfo.xml", comic_info([
            ("Title", episode["title"]),
            ("Series", "Pepper&Carrot"),
            ("Number", str(number)),
            ("Writer", "David Revoy"),
            ("Penciller", "David Revoy"),
            ("PageCount", str(len(pages))),
            ("LanguageISO", "en"),
            ("Manga", "No"),
        ])))
        entries.append(("LICENSE.txt", pc_licence_text(
            episode["title"], source_dir, page_urls,
            ["The pages are the unmodified English hi-res files, repackaged as a CBZ archive.",
             "The title banner (and, in episode 1, a decorative divider strip) are left out."],
        )))
        target = SAMPLES / f"pepper-carrot-ep{number:02d}.cbz"
        write_cbz(target, entries)
        samples.append(sample_record(target, pages=len(pages), series="Pepper&Carrot", number=str(number)))
        log(f"  wrote {target.name}: {len(pages)} pages, {target.stat().st_size:,} bytes")
    return downloads, samples, pages_by_episode


def build_strip(pages: list[tuple[str, bytes]]) -> dict:
    log("Pepper&Carrot (vertical) strip from episode 1")
    episode = EPISODES[1]
    scaled: list[Image.Image] = []
    for name, data in pages:
        image = decode_jpeg(data, name).convert("RGB")
        height = round(image.height * STRIP_WIDTH / image.width)
        scaled.append(image.resize((STRIP_WIDTH, height), Image.LANCZOS))
    groups = [scaled[i:i + STRIP_PAGES_PER_IMAGE] for i in range(0, len(scaled), STRIP_PAGES_PER_IMAGE)]
    entries: list[tuple[str, bytes]] = []
    for index, group in enumerate(groups, start=1):
        canvas = Image.new("RGB", (STRIP_WIDTH, sum(image.height for image in group)), "white")
        top = 0
        for image in group:
            canvas.paste(image, (0, top))
            top += image.height
        entries.append((f"{index:03d}.jpg", jpeg_bytes(canvas, STRIP_JPEG_QUALITY)))
        log(f"  strip image {index:03d}.jpg: {canvas.width}x{canvas.height} from {len(group)} page(s)")
    if entries and Image.open(io.BytesIO(entries[0][1])).height <= 2 * STRIP_WIDTH:
        raise SystemExit("strip's first image is not more than twice as tall as wide")

    page_urls = [pc_url(episode, page) for page in episode["pages"]]
    entries.append(("ComicInfo.xml", comic_info([
        ("Title", episode["title"] + " (vertical strip)"),
        ("Series", "Pepper&Carrot (vertical)"),
        ("Number", "1"),
        ("Writer", "David Revoy"),
        ("Penciller", "David Revoy"),
        ("PageCount", str(len(groups))),
        ("LanguageISO", "en"),
        ("Manga", "No"),
    ])))
    entries.append(("LICENSE.txt", pc_licence_text(
        episode["title"], f"{PC_BASE}/{episode['dir']}/hi-res/", page_urls,
        [f"modified: pages scaled and stacked vertically (each page scaled to {STRIP_WIDTH} px wide, "
         f"{STRIP_PAGES_PER_IMAGE} pages stacked per image, no gaps, re-encoded as JPEG quality {STRIP_JPEG_QUALITY}).",
         "The title banner and the decorative divider strip are left out."],
    )))
    target = SAMPLES / "pepper-carrot-strip.cbz"
    write_cbz(target, entries)
    log(f"  wrote {target.name}: {len(groups)} images, {target.stat().st_size:,} bytes")
    return sample_record(target, pages=len(groups), series="Pepper&Carrot (vertical)", number="1")


# --------------------------------------------------------------------------------------
# Hokusai Manga (Smithsonian Libraries)
# --------------------------------------------------------------------------------------
def hokusai_identifier(volume: int) -> str:
    return f"hokusaimangav{volume}kats"


def hokusai_page_url(volume: int) -> str:
    return f"https://{SI_HOST}/digital-library/book/{hokusai_identifier(volume)}"


def hokusai_zip_url(volume: int) -> str:
    identifier = hokusai_identifier(volume)
    return f"https://archive.org/download/{identifier}/{identifier}_jp2.zip"


def hokusai_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = [m for m in archive.infolist()
               if not m.is_dir() and m.filename.lower().endswith(".jp2") and ".." not in m.filename
               and not m.filename.startswith("/")]
    return sorted(members, key=lambda m: m.filename)


def contact_sheets(images: list[tuple[int, Image.Image]], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    columns, rows, tile_w, tile_h = 2, 3, 780, 640
    per_sheet = columns * rows
    for sheet_index in range(0, len(images), per_sheet):
        chunk = images[sheet_index:sheet_index + per_sheet]
        sheet = Image.new("RGB", (columns * tile_w, rows * (tile_h + 24)), "white")
        draw = ImageDraw.Draw(sheet)
        for slot, (index, image) in enumerate(chunk):
            thumb = image.copy()
            thumb.thumbnail((tile_w - 8, tile_h - 8), Image.LANCZOS)
            x = (slot % columns) * tile_w + 4
            y = (slot // columns) * (tile_h + 24) + 24
            draw.text((x, y - 18), f"page index {index}  ({image.width}x{image.height} original)", fill="black")
            sheet.paste(thumb.convert("RGB"), (x, y))
        sheet.save(directory / f"sheet-{sheet_index // per_sheet + 1:03d}.png")
    log(f"  wrote {-(-len(images) // per_sheet)} contact sheets to {directory}")


def build_hokusai(refresh: bool, volume: int, sheets_dir: Path | None) -> tuple[dict, dict]:
    identifier = hokusai_identifier(volume)
    log(f"Hokusai Manga volume {volume} ({identifier})")
    url = hokusai_zip_url(volume)
    dest = CACHE / "hokusai" / f"{identifier}_jp2.zip"
    # The Smithsonian page's own download links point at archive.org's /download/ paths.
    info = fetch(url, dest, refresh=refresh, extra_suffix="archive.org", expect_types=("application/zip",))
    info.update(sample=f"hokusai-manga-v{volume:02d}", linked_from=hokusai_page_url(volume))

    with zipfile.ZipFile(dest) as archive:
        members = hokusai_members(archive)
        if not members:
            raise SystemExit("no .jp2 page images in the Hokusai archive")
        log(f"  {len(members)} page images in the scan archive "
            f"({members[0].filename} .. {members[-1].filename})")
        decoded: list[tuple[int, Image.Image]] = []
        for index, member in enumerate(members):
            if member.file_size > 120 * 1024 * 1024:
                raise SystemExit(f"{member.filename}: unexpectedly large")
            image = Image.open(io.BytesIO(archive.read(member)))
            image.load()
            decoded.append((index, image.convert("RGB")))
    info["page_images_in_scan"] = len(members)
    info["first_member"] = members[0].filename
    info["last_member"] = members[-1].filename

    if sheets_dir is not None:
        contact_sheets(decoded, sheets_dir)

    kept = [(index, image) for index, image in decoded if index not in HOKUSAI_EXCLUDE]
    entries: list[tuple[str, bytes]] = []
    width = max(3, len(str(len(kept))))
    for position, (index, image) in enumerate(kept, start=1):
        scaled = image.copy()
        scaled.thumbnail((HOKUSAI_MAX_SIDE, HOKUSAI_MAX_SIDE), Image.LANCZOS)
        entries.append((f"{position:0{width}d}.jpg", jpeg_bytes(scaled, HOKUSAI_JPEG_QUALITY)))
    log(f"  {len(entries)} pages kept, {len(HOKUSAI_EXCLUDE)} excluded {sorted(HOKUSAI_EXCLUDE)}")

    page_url = hokusai_page_url(volume)
    entries.append(("ComicInfo.xml", comic_info([
        ("Title", f"Hokusai Manga, volume {volume}"),
        ("Series", "Hokusai Manga"),
        ("Number", str(volume)),
        ("Writer", "Katsushika Hokusai"),
        ("PageCount", str(len(kept))),
        ("LanguageISO", "ja"),
        ("Manga", "YesAndRightToLeft"),
    ])))
    licence = "\n".join([
        f"Hokusai Manga (北斎漫画), volume {volume}",
        "Katsushika Hokusai (葛飾北斎), Edo period",
        "Courtesy of the Smithsonian Libraries and Archives",
        "",
        "Licence: CC0 1.0 / No Copyright - United States, Smithsonian Libraries",
        f"Source: {page_url}",
        f"Licence text: {CC0_URL}legalcode",
        "",
        'Statement on the source page: "CC0 — Creative Commons (CC0 1.0) This content is in the public',
        'domain (free of copyright restrictions). You can copy, modify, and distribute this work without',
        'contacting the Smithsonian."',
        "",
        "Changes made:",
        f"  Page images converted from the scan's JPEG 2000 files to JPEG (long side at most {HOKUSAI_MAX_SIDE} px,",
        f"  quality {HOKUSAI_JPEG_QUALITY}) and packaged as a CBZ archive in the scan's page order."
        + (f" {len(HOKUSAI_EXCLUDE)} scan page(s) left out (see CREDITS.md)." if HOKUSAI_EXCLUDE else ""),
        "",
        "Packaged for the Inkshelf sample library: https://jonathan-nuno.github.io/inkshelf-site/samples.html",
        "",
    ]).encode("utf-8")
    entries.append(("LICENSE.txt", licence))

    target = SAMPLES / f"hokusai-manga-v{volume:02d}.cbz"
    write_cbz(target, entries)
    log(f"  wrote {target.name}: {len(kept)} pages, {target.stat().st_size:,} bytes")
    return info, sample_record(target, pages=len(kept), series="Hokusai Manga", number=str(volume))


# --------------------------------------------------------------------------------------
# Records and verification
# --------------------------------------------------------------------------------------
def sample_record(path: Path, *, pages: int, series: str, number: str) -> dict:
    return {
        "file": str(path.relative_to(ROOT)),
        "bytes": path.stat().st_size,
        "sha256": sha256_of(path),
        "pages": pages,
        "series": series,
        "number": number,
    }


def verify_archives(samples: list[dict]) -> None:
    log("Verification")
    for record in samples:
        path = ROOT / record["file"]
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None:
                raise SystemExit(f"{path.name}: corrupt entry")
            infos = archive.infolist()
            deflated = [i.filename for i in infos if i.compress_type != zipfile.ZIP_STORED]
            if deflated:
                raise SystemExit(f"{path.name}: deflated entries {deflated}")
            names = [i.filename for i in infos]
            if any("/" in n for n in names):
                raise SystemExit(f"{path.name}: entries are not all at the archive root")
            pages = sorted(n for n in names if n.lower().endswith(".jpg"))
            if len(pages) != record["pages"] or pages != [f"{i:0{len(pages[0][:-4])}d}.jpg" for i in range(1, len(pages) + 1)]:
                raise SystemExit(f"{path.name}: page names are not 001.jpg ... in order")
            root = ET.fromstring(archive.read("ComicInfo.xml"))
            fields = {child.tag: (child.text or "").strip() for child in root}
            if root.tag != "ComicInfo" or fields.get("Series") != record["series"] or fields.get("Number") != record["number"]:
                raise SystemExit(f"{path.name}: ComicInfo mismatch {fields}")
            if "Web" in fields:
                raise SystemExit(f"{path.name}: ComicInfo must not carry Web")
            first = Image.open(io.BytesIO(archive.read(pages[0])))
            record["first_page_size"] = f"{first.width}x{first.height}"
            record["manga"] = fields.get("Manga")
            record["vertical_default"] = first.height > 2 * first.width
        log(f"  OK {path.name}: {len(pages)} pages, stored, Series={fields['Series']!r} Number={fields['Number']} "
            f"Manga={fields['Manga']} first page {record['first_page_size']} "
            f"(vertical default: {record['vertical_default']}), {record['bytes']:,} bytes")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--refresh", action="store_true", help="download everything again")
    parser.add_argument("--hokusai-volume", type=int, default=5)
    parser.add_argument("--contact-sheets", type=Path, default=None)
    args = parser.parse_args()

    if not features.check("jpg_2000"):
        raise SystemExit("this Pillow has no JPEG 2000 support")
    ImageFile.LOAD_TRUNCATED_IMAGES = False
    SAMPLES.mkdir(exist_ok=True)
    CACHE.mkdir(exist_ok=True)
    if MANIFEST.exists():
        try:
            for item in json.loads(MANIFEST.read_text(encoding="utf-8")).get("downloads", []):
                if item.get("retrieved_utc"):
                    PRIOR_RETRIEVED[item["url"]] = item["retrieved_utc"]
        except (OSError, ValueError):
            pass

    import PIL
    log(f"make-samples.py, {utc_now()}, Python {sys.version.split()[0]}, Pillow {PIL.__version__}")
    log()
    licences = check_licences(args.refresh, hokusai_page_url(args.hokusai_volume), args.hokusai_volume)
    log()
    downloads, samples, pages_by_episode = build_pepper_carrot(args.refresh)
    log()
    samples.append(build_strip(pages_by_episode[1]))
    log()
    hokusai_download, hokusai_sample = build_hokusai(args.refresh, args.hokusai_volume, args.contact_sheets)
    downloads.append(hokusai_download)
    samples.append(hokusai_sample)
    log()
    verify_archives(samples)

    manifest = {
        "generated_utc": utc_now(),
        "tool": "tools/make-samples.py",
        "pillow": PIL.__version__,
        "licence_pages": licences,
        "downloads": downloads,
        "samples": samples,
        "hokusai_volume": args.hokusai_volume,
        "hokusai_content_check": HOKUSAI_CONTENT_CHECK,
        "hokusai_excluded_scan_pages": {str(k): v for k, v in sorted(HOKUSAI_EXCLUDE.items())},
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log()
    log(f"wrote {MANIFEST.relative_to(ROOT)}")
    log("Samples")
    for record in samples:
        log(f"  {record['file']:36s} {record['bytes']:>11,d} B  {record['pages']:>3d} pages  sha256 {record['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
