import math

from app.domain.errors import EmbeddingError


def validate_vectors(vectors, count: int, dimensions: int) -> list[list[float]]:
    if not isinstance(vectors, list) or len(vectors) != count:
        raise EmbeddingError("Embedding response count does not match input")
    output = []
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != dimensions:
            raise EmbeddingError("Embedding dimensions do not match configuration")
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for value in vector):
            raise EmbeddingError("Embedding response contains invalid values")
        if not any(value != 0 for value in vector):
            raise EmbeddingError("Embedding response contains a zero vector")
        output.append([float(value) for value in vector])
    return output
