# PDF fonts

PDF exports use bundled Noto fonts and do not download fonts at runtime. The
23 font files are stored losslessly in `bitcoin_safe/data/fonts/pdf-fonts.tar.xz`.
On first PDF export, Python decompresses the archive in memory and Qt registers
each font from its original bytes. The archive's XZ integrity check is verified
before registration. The separate copyright notices and SIL Open Font License
remain in the same directory.

Compression reduces the font files from 23,530,692 bytes to 12,540,088 bytes
(46.7%) without changing glyphs, shaping tables or regional variants. The
collection contains the JP, KR, SC, TC and HK proportional CJK faces. It is a
repack of the original Noto Sans CJK Regular TTC with the five unused mono
faces removed; `tools/optimize_pdf_fonts.py` can recreate that TTC from the
original source documented in that script.

The fonts cover the characters in their original cmaps, not arbitrary Unicode.
Uncommon characters outside these cmaps (including emoji and some historical
scripts) may be missing or supplied by system fallback. Check user-entered
wallet names and recovery notes in the resulting PDF. Qt does not currently
report every missing glyph as an error.

To reproduce the archive from its losslessly stored font files:

```sh
mkdir -p build/pdf-font-source
tar -xJf bitcoin_safe/data/fonts/pdf-fonts.tar.xz -C build/pdf-font-source
poetry run python tools/pack_pdf_fonts.py build/pdf-font-source bitcoin_safe/data/fonts/pdf-fonts.tar.xz
```

The generated archive has SHA-256
`ef8c9b8207327418a5da251cf7245afd5ec89d34e3180f763b5948ed35d3d6e4` with the
current Python/liblzma toolchain. The archive generator fixes file ordering,
timestamps, ownership and modes; compression output may vary with liblzma
versions. Python's standard-library `lzma` module is required at runtime.
