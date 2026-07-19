class AHSEngineError(Exception):
    """Base exception for deterministic engine failures."""


class ConfigurationError(AHSEngineError):
    pass


class CatalogError(AHSEngineError):
    pass


class SchemaValidationError(AHSEngineError):
    pass


class QueryValidationError(AHSEngineError):
    pass


class ExecutionError(AHSEngineError):
    pass
