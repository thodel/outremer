# Scanned recognition fixture

`magna-carta-1215-image-only.pdf` contains only a raster image—there is no PDF
text layer. It is derived from the public-domain Wikimedia Commons image:

- *Magna Carta (British Library Cotton MS Augustus II.106)*
- One of the four surviving 1215 exemplars
- Source: https://commons.wikimedia.org/wiki/File:Magna_Carta_(British_Library_Cotton_MS_Augustus_II.106).jpg
- Licence: public domain
- Fixture transformation: Wikimedia's 1280 px derivative embedded as a
  single-page image-only PDF

The fixture exists to exercise the actual low-text-yield recognition route.
The offline test mocks only the remote recognition response; PDF detection,
routing, and run-report provenance remain real. Set `OUTREMER_LIVE_OCR=1` to
run the opt-in live GPUStack recognition test.
