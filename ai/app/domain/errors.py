class IngestionError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.status, self.code, self.retryable = status, code, retryable


class ResourceError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class StorageError(Exception):
    """Sanitized storage failure; provider exceptions stay in the adapter."""


class SourceError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code, self.retryable = code, retryable


class EmbeddingError(Exception):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class IndexingError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class RagError(Exception):
    def __init__(self, status: int, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.status, self.code, self.retryable = status, code, retryable
