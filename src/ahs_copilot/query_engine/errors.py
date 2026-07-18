class QueryEngineError(Exception):
    """Base error for deterministic query-engine failures."""


class ConfigurationError(QueryEngineError):
    pass


class DatasetResolutionError(QueryEngineError):
    pass


class SchemaValidationError(QueryEngineError):
    pass


class QueryValidationError(QueryEngineError):
    pass


class JoinPolicyError(QueryValidationError):
    pass


class ResultLimitError(QueryValidationError):
    pass
