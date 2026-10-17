# Credits and licences

The sample comics on this site are packaged from works released under open licences. Each
archive in `samples/` also carries a `LICENSE.txt` with the same information. The source
statements below were re-checked on 2026-10-16 by `tools/make-samples.py`; the page hashes
and retrieval times are in `samples/MANIFEST.json` (`licence_pages`).

## Pepper&Carrot, by David Revoy

- Credit line: **© David Revoy, www.peppercarrot.com, CC BY 4.0**
- Licence: Creative Commons Attribution 4.0 International, <https://creativecommons.org/licenses/by/4.0/>
  (legal code: <https://creativecommons.org/licenses/by/4.0/legalcode>), see `LICENSES/CC-BY-4.0.txt`.
- Licence statement on the source site (<https://www.peppercarrot.com/en/about/index.html#license>,
  checked 2026-10-16): "Pepper&Carrot webcomics, translations and artworks are licensed under a
  Creative Commons Attribution 4.0 International license unless otherwise noted (eg. fan-arts)".
  The same page carries the notice "AI derivation prohibited".
- Files: `pepper-carrot-ep01.cbz` (Episode 1: The Potion of Flight, source
  <https://www.peppercarrot.com/en/webcomic/ep01_Potion-of-Flight.html>), `pepper-carrot-ep02.cbz`
  (Episode 2: Rainbow Potions, source <https://www.peppercarrot.com/en/webcomic/ep02_Rainbow-potions.html>),
  `pepper-carrot-strip.cbz` (episode 1 as a vertical strip).
- Pages come from the English hi-res files under `https://www.peppercarrot.com/0_sources/`; every
  URL and SHA-256 is in `samples/MANIFEST.json` and `make-samples.first-run.log`.
- Changes made (CC BY 4.0, section 3(a)(1)(B)):
  - Episodes 1 and 2: the story pages are unmodified, repackaged as CBZ archives. The title
    banner (`P00`, all episodes) and episode 1's 50 px decorative divider (`P04`) are not
    included; the title is in `ComicInfo.xml`. Episode 2 keeps its credits panel (`P06`).
  - Strip: modified. Episode 1's pages are scaled to 800 px wide and stacked vertically, two
    pages per image with no gaps, and saved as JPEG (quality 85).
- Not covered by the licence and not claimed here: the Pepper&Carrot name and logo. This site and
  Inkshelf are not affiliated with or endorsed by David Revoy.

## Hokusai Manga, volume 5 (Smithsonian Libraries and Archives)

- Credit line: **Courtesy of the Smithsonian Libraries and Archives**, with a link back to
  <https://library.si.edu/digital-library/book/hokusaimangav5kats> (DOI
  <https://doi.org/10.5479/sil.1073933.39088019217496>).
- Licence: **CC0 1.0 / No Copyright – United States**, <https://creativecommons.org/publicdomain/zero/1.0/>
  (legal code: <https://creativecommons.org/publicdomain/zero/1.0/legalcode>), see `LICENSES/CC0-1.0.txt`.
- Licence statement on the source page (checked 2026-10-16): "CC0 — Creative Commons (CC0 1.0) This
  content is in the public domain (free of copyright restrictions). You can copy, modify, and
  distribute this work without contacting the Smithsonian."
- Attribution request on <https://library.si.edu/copyright> (checked 2026-10-16): "We ask that an
  attribution statement such as "Courtesy of the Smithsonian Libraries and Archives" is used, along
  with a link back to the original source on our site."
- File: `hokusai-manga-v05.cbz`. The page images are the scan's JPEG 2000 files
  (`hokusaimangav5kats_jp2.zip`, linked from the Smithsonian page, hosted at archive.org; URL and SHA-256
  in `samples/MANIFEST.json`), converted to JPEG with the long side at most 1600 px (quality 85) and
  packaged in the scan's order, all 35 scan images (front and back cover, spreads and catalogue
  pages).
- Content check: every one of the 35 scan images was viewed before packaging, looking for nude or
  bawdy plates; none were found, so no page is left out (details in `README.md`).
