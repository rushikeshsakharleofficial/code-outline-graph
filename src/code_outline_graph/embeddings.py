import struct

_model = None


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    return _model


class Embedder:
    def encode(self, text: str) -> list[float]:
        model = _get_model()
        result = list(model.embed([text]))
        return result[0].tolist()

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        model = _get_model()
        result = list(model.embed(texts))
        return [v.tolist() for v in result]


def serialize_float32(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)
