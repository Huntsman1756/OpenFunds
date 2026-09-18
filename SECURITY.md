# Security policy

## Scope

cnmv-iic downloads and parses untrusted content (ZIP + XML) from a public
upstream (cnmv.es). The trust boundary is the acquisition layer; the threat
model covers malicious or corrupted archives, XML entity expansion, oversized
payloads, and provenance tampering.

## Built-in defenses

- HTTPS-only, single-origin URL allowlist (`https://www.cnmv.es/`)
- Bounded redirect chain, redirects off-origin rejected
- Response byte caps enforced while streaming
- ZIP magic check; HTML payloads rejected
- ZIP entry-count, per-entry size, total-size and compression-ratio caps
- Member-name traversal (`..`, absolute paths) rejected
- DOCTYPE/ENTITY declarations rejected outright; lxml parser with entity
  resolution, network access and DTD processing disabled
- SHA-256 of every artifact and member recorded before parsing
- Atomic artifact writes; content-addressed, write-once raw store
- Unknown XSD fingerprints and unknown XML elements fail closed

## Reporting

Report vulnerabilities privately to the maintainers — do not open public
issues for unpatched security problems. If this repository is published on
GitHub, use GitHub private vulnerability reporting; otherwise contact the
maintainer listed in the repository profile.

## Data handling

Raw CNMV artifacts are stored locally under the data directory and are never
committed or redistributed. No credentials, tokens, or personal data are
processed by this project.
