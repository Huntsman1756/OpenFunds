# NOTICE — third-party attribution

## EidoAut/Aletheia (MIT License)

Repository: https://github.com/EidoAut/Aletheia

The acquisition layer of this project (`cnmv_iic.acquisition`) was informed
by defensive patterns observed in Aletheia's `CnmvIicProvider` /
`CnmvIicParser` (C#): bounded redirects, response byte caps, ZIP magic
validation, entry-count / decompressed-size / compression-ratio limits,
member-name traversal rejection, DTD/entity processing disabled, and
provenance-aware artifact records.

These are *patterns*, not ported code — this implementation is original
Python. Aletheia's license is reproduced below as required.

Aletheia is MIT-licensed:

```
MIT License

Copyright (c) 2025 EidoAut

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Other repositories consulted (reference only, nothing reused)

- `jcmoro/ticker-lab` — working CNMV ingestion in Go; **no license**, used as
  architectural reference only. No code, no text copied.
- `afernandez119/cnmv_data`, `delaosash/cnmv-funds` — PDF extraction projects;
  no license established, nothing reused.
- `qumundo/funds` — proprietary, all rights reserved; nothing reused.
- `fundsxml/schema`, `fundsxml/examples` — industry schema; not a dependency.
- `antikas/open-investment-model` (MIT) — conceptual prior art only.
- `openfunds.org` — existing industry standard/initiative; this project is
  named `cnmv-iic` specifically to avoid collision (ADR-006).
