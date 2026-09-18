"""Domain exceptions for cnmv-iic."""


class CnmvIicError(Exception):
    """Base class for all cnmv-iic errors."""


class AcquisitionError(CnmvIicError):
    """Network/index/download failure."""


class PayloadRejectedError(AcquisitionError):
    """Downloaded payload failed structural validation (fail-closed)."""


class ZipRejectedError(PayloadRejectedError):
    """ZIP failed structural/security validation."""


class SchemaRegistryError(CnmvIicError):
    """Artifact member has an unknown schema fingerprint."""


class UnsupportedSchemaError(CnmvIicError):
    """Instance contains elements/values outside known schema + deviations."""


class ParseError(CnmvIicError):
    """XML instance could not be parsed."""


class ArtifactConflictError(CnmvIicError):
    """Artifact ledger inconsistency."""


class NotFoundError(CnmvIicError):
    """Requested entity/artifact/period not found."""
