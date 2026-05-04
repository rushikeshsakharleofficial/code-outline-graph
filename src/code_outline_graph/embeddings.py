import os
import struct

_model = None

# Max threads for ONNX/OpenMP — default 2, override with CODE_OUTLINE_THREADS env var
_THREAD_CAP = str(max(1, int(os.environ.get("CODE_OUTLINE_THREADS", "2"))))


def _limit_threads():
    """Cap OpenMP/MKL/ONNX thread pools before model loads. Must run before any import of fastembed/onnxruntime."""
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "ONNXRUNTIME_INTRA_OP_NUM_THREADS",
    ):
        if var not in os.environ:
            os.environ[var] = _THREAD_CAP


def _get_model():
    global _model
    if _model is None:
        _limit_threads()
        try:
            from fastembed import TextEmbedding
            _model = TextEmbedding(
                model_name="BAAI/bge-small-en-v1.5",
                threads=int(_THREAD_CAP),
            )
        except TypeError:
            # older fastembed doesn't accept threads= kwarg
            from fastembed import TextEmbedding
            _model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    return _model


class Embedder:
    def encode(self, text: str) -> list[float]:
        model = _get_model()
        result = list(model.embed([text]))
        return result[0].tolist()

    def encode_batch(self, texts: list[str], batch_size: int = 64) -> list[list[float]]:
        """Encode in chunks with brief yields to keep CPU breathable."""
        import time
        model = _get_model()
        out = []
        for i in range(0, len(texts), batch_size):
            chunk = texts[i: i + batch_size]
            out.extend(v.tolist() for v in model.embed(chunk))
            if i + batch_size < len(texts):
                time.sleep(0.01)  # 10ms yield between chunks
        return out


def serialize_float32(vector: list[float]) -> bytes:
    return struct.pack(f"{len(vector)}f", *vector)
