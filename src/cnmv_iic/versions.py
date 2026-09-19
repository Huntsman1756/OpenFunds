"""Compatibility contract — version identifiers for every layer whose
change can alter reproducible output.

Since v0.1, any breaking change to a layer MUST bump its version here
(or introduce a new engine version), never silently alter semantics
under an existing version string.

Consumers can pin/verify against these values; `dataset-info` reports
them alongside fingerprints.
"""
from __future__ import annotations

from cnmv_iic import __version__

# Parquet schema layout (columns/order of the canonical tables).
# Bump when any schema field is added/removed/renamed in a
# backwards-incompatible way.
DATASET_SCHEMA_VERSION = "1"

# Canonical domain semantics (keys, identity rules, Decimal fields).
CANONICAL_MODEL_VERSION = __version__

# G9 lifecycle adjudication engine — preregistered rules.
# Frozen: a rule change is a NEW engine version, not an edit.
LIFECYCLE_ENGINE_VERSION = "g9e-v1"

# Source ledger parsing/classification rules (weekly bulletin, HR,
# FONDREGISTRO markers). Bump when extraction semantics change.
LIFECYCLE_PARSER_VERSION = "1"
LIFECYCLE_RULE_VERSION = "1"

# CNMV family adapters pin __version__ at export time; external
# provider parsers have their own constants in adapters/*.
PARSER_VERSION = __version__


def contract() -> dict[str, str]:
    """The full compatibility contract as a reportable dict."""
    return {
        "package_version": __version__,
        "dataset_schema_version": DATASET_SCHEMA_VERSION,
        "canonical_model_version": CANONICAL_MODEL_VERSION,
        "lifecycle_engine_version": LIFECYCLE_ENGINE_VERSION,
        "lifecycle_parser_version": LIFECYCLE_PARSER_VERSION,
        "lifecycle_rule_version": LIFECYCLE_RULE_VERSION,
        "parser_version": PARSER_VERSION,
    }
