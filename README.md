# Inkshelf site

The public site for Inkshelf, an offline reader for CBZ comic and manga files on iPhone. It is
plain HTML served by GitHub Pages from `main` (no build step; `.nojekyll` is present):

| Page | What it is |
| --- | --- |
| `index.html` | Support page: what Inkshelf is, how to bring files in, backups, contact (GitHub Issues), credits |
| `privacy.html` | Privacy policy (Inkshelf collects no data) |
| `samples.html` | Free sample comics with licences, credit lines, source links and downloads |
| `samples/*.cbz` | The sample comics; `samples/MANIFEST.json` records every download and archive hash |

No scripts, no analytics, no cookies and no external resources: pages use `style.css` and the
system font stack, and every link between pages is relative so the site works at
`https://<owner>.github.io/inkshelf-site/`.

## Samples

| File | Contents | Series in Inkshelf |
| --- | --- | --- |
| `pepper-carrot-ep01.cbz` | Pepper&Carrot episode 1, English, 3 pages | Pepper&Carrot |
| `pepper-carrot-ep02.cbz` | Pepper&Carrot episode 2, English, 6 pages | Pepper&Carrot |
| `pepper-carrot-strip.cbz` | Episode 1 scaled to 800 px wide and stacked into 2 tall images (modified) | Pepper&Carrot (vertical) |
| `hokusai-manga-v05.cbz` | Hokusai Manga volume 5, Smithsonian Libraries scan, 35 images, right to left | Hokusai Manga |

Every archive has its pages stored (not deflated) as `001.jpg`, `002.jpg`, … in reading order,
a `ComicInfo.xml` at the root (`Series`, `Number`, `Manga`, …) and a `LICENSE.txt`.
Licences and credit lines: `CREDITS.md`, `LICENSES/`, and the samples page.

### Rebuild

```sh
~/.local/share/codex-skills/image-tools/venv/bin/python -I tools/make-samples.py 2>&1 | tee make-samples.log
```

The interpreter needs Pillow 12.x with JPEG 2000 support. The script downloads (only from
`www.peppercarrot.com`, `library.si.edu` and the archive.org links on the Smithsonian page) into
`cache/` (git-ignored), re-checks the licence statements, builds the four archives (byte-identical
on every run), verifies them and writes `samples/MANIFEST.json`. `--refresh` ignores the cache,
`--hokusai-volume N` packages another volume of the same collection and
`--contact-sheets DIR` writes numbered contact sheets of the Hokusai pages for the content check.
Downloaded files are only decoded in memory; nothing from them is executed or extracted to disk.

`make-samples.first-run.log` is the first run, with every download (`downloaded` lines: URL, size,
SHA-256); `make-samples.log` is the final run from the cache.

### Content check (Hokusai Manga)

Volume 5 was checked page by page before use: all 35 scan images were viewed on numbered contact
sheets and the plates showing figures in loincloths (indices 9, 21 and 27) were viewed enlarged.
The book holds covers, front matter, deity and court portraits, shrine gates, bells, temples,
guardian demons, wrestlers, Mount Fuji and waves, and the publisher's catalogue. No nude figures
and no bawdy or erotic plates were found, so no page is left out and no other volume was needed.
The result is also in `samples/MANIFEST.json` (`hokusai_content_check`).

### Size and conversion notes

Each archive is under 30 MB (largest: 14.4 MB). The Pepper&Carrot pages are the original JPEG
files. The strip's images and the Hokusai pages are re-encoded JPEGs without EXIF or colour
profile; Hokusai pages are scaled to at most 1600 px on the long side (the scans are about
6000 px wide double-page spreads, so each page is a spread).

## Contact

Issues: <https://github.com/Jonathan-Nuno/inkshelf-site/issues>
