# Publishing — PyPI via Trusted Publishing (OIDC)

`cnmv-iic` is published to PyPI **only** through GitHub Actions OIDC
Trusted Publishing. No long-lived PyPI API token is used or stored.

Core invariant:

```text
GitHub release artifact == PyPI artifact   (same bytes, verified by SHA-256)
```

Distributions are built once, validated once, and the exact same bytes
are published to both GitHub Releases and PyPI. Never two independent
builds.

## One-time setup (repository owner)

1. On PyPI, create a **pending Trusted Publisher** for project
   `cnmv-iic` (PyPI → Account → Publishing → "Add a new pending
   publisher"):

   | field | value |
   |---|---|
   | PyPI project name | `cnmv-iic` |
   | Owner | `Huntsman1756` |
   | Repository | `OpenFunds` |
   | Workflow | `publish-pypi.yml` |
   | Environment | `pypi` |

2. In GitHub → Settings → Environments, create environment **`pypi`**
   and enable **required reviewers** (manual approval) so publication
   is a deliberate act.

3. Nothing else: no secrets, no tokens. The workflow uses
   `id-token: write` only.

Until step 1 exists on PyPI, running the workflow will fail at the
OIDC exchange — nothing is published.

## Publishing an existing release (v0.1.0)

The workflow `.github/workflows/publish-pypi.yml` is manual
(`workflow_dispatch`). It does **not** rebuild:

```text
tag input (e.g. v0.1.0)
  → download .whl + .tar.gz + SHA256SUMS.txt from that GitHub release
  → fail closed: exactly 1 wheel + 1 sdist + SHA256SUMS, nothing else
  → sha256sum -c against the published checksums
  → package metadata Version: must equal the tag version
  → pypa/gh-action-pypi-publish@release/v1 (OIDC)
```

```bash
gh workflow run publish-pypi.yml -f tag=v0.1.0
# then approve the `pypi` environment deployment
```

For `v0.1.0` this publishes exactly the bytes already released on
GitHub — no rebuild, no repackaging, no normalization.

## Future releases

Recommended pipeline (single build, dual publish):

```text
tag
 ↓
build once (wheel + sdist)
 ↓
validate: tests, audit, SHA256SUMS, SBOM
 ↓
GitHub Release with validated assets
 ↓
publish-pypi.yml → downloads those same assets → PyPI
```

Enabling **GitHub immutable releases** is recommended once available
for the repository: it freezes release assets and tags and adds a
release attestation. This applies only to future releases — the
already-published `v0.1.0` release is left as-is (its bytes are pinned
by `SHA256SUMS.txt` regardless).

## Fail-closed guarantees

The workflow refuses to publish when:

- expected release assets are missing;
- more/fewer than exactly one wheel and one sdist are present;
- any unexpected file is present in `dist/`;
- SHA-256 verification against `SHA256SUMS.txt` fails;
- package `Version:` metadata does not match the tag.
