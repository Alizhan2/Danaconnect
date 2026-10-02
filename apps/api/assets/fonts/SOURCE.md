# Bundled certificate font

This directory contains the unchanged **DejaVu Sans 2.37** TrueType font.
The API uses it for certificate text in Russian, Kazakh and English, independently
of installed operating-system fonts. It is a PDF text font, not a brand logo.

## Provenance

- Maintainer repository: https://github.com/dejavu-fonts/dejavu-fonts
- Pinned release: https://github.com/dejavu-fonts/dejavu-fonts/releases/tag/version_2_37
- Release asset: https://github.com/dejavu-fonts/dejavu-fonts/releases/download/version_2_37/dejavu-sans-ttf-2.37.zip
- Independently published archive checksum: https://dejavu-fonts.github.io/Download.html
- License explanation: https://dejavu-fonts.github.io/License.html
- Retrieved: 2026-10-02 (Asia/Oral).

The downloaded archive matched the SHA-256 checksum published on the official
download page **before** extraction. Only the named TTF and original license
were copied from the ZIP; no package scripts or executables were run.

| Item | Archive member / bundled name | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Original release ZIP | `dejavu-sans-ttf-2.37.zip` | 417746 | `5c6e497a2f36552cb5ffb112c413a6af39c0f3c47653662b90b4fa6499822fd7` |
| Unchanged font | `dejavu-sans-ttf-2.37/ttf/DejaVuSans.ttf` → `DejaVuSans.ttf` | 757076 | `7da195a74c55bef988d0d48f9508bd5d849425c1770dba5d7bfc6ce9ed848954` |
| Original license | `dejavu-sans-ttf-2.37/LICENSE` → `LICENSE-DejaVu.txt` | 8816 | `7a083b136e64d064794c3419751e5c7dd10d2f64c108fe5ba161eae5e5958a93` |

Individual-file digests were calculated from the checksum-verified official
archive. The font digest is also pinned in `app/services/growth.py`.
Static character-map inspection of this exact file found 5,918 entries and
glyphs for all 66 Russian letters, all 18 additional uppercase/lowercase Kazakh
Cyrillic letters, and all 52 English letters. No certificate PDF was generated
as part of this asset inspection.

## Redistribution

`LICENSE-DejaVu.txt` is copied verbatim from that release archive and must travel
with this font in source distributions and deployment bundles. It includes the
original Bitstream/Arev copyright and permission notices. DejaVu additions are
described as public-domain contributions. Redistribution as part of an
application is permitted by the included license; the typeface must not be sold
on its own. This copy has not been modified or renamed. No maintainer endorsement
is implied.

## Deployment

Include `assets/fonts/DejaVuSans.ttf`, `LICENSE-DejaVu.txt` and this notice alongside
the API's `app` directory. The API resolves this path from the service module,
checks the pinned bundled-file digest, and prefers it before optional
`CERTIFICATE_FONT_PATH` or system fonts. A missing bundle may use those fallback
paths; a corrupted bundled font fails with an availability error.

The existing certificate code checks every requested character against the
selected font's character map and reports unsupported characters explicitly.
Font bundling does not change award permissions, certificate content or layout.
