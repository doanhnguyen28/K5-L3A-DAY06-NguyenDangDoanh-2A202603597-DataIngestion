"""Real local embedding model (Sentence Transformers). No mock/random fallback: errors propagate."""
from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class MyEmbedder:
    """Sentence Transformers adapter.

    Query and document are encoded the same way (this model has no query/passage prefixes),
    L2-normalized so cosine distance in pgvector is well defined. Texts longer than the
    model's max_seq_length are truncated by the model; `count_tokens` lets us report that.
    """

    def __init__(self, model_name: str, batch_size: int = 32) -> None:
        import sentence_transformers
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self.batch_size = batch_size
        self.model = SentenceTransformer(model_name, device="cpu")
        self.dimensions = int(self.model.get_embedding_dimension())
        self.max_seq_length = int(self.model.max_seq_length)
        self.library_version = sentence_transformers.__version__

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self.model.encode(texts, batch_size=self.batch_size,
                                    normalize_embeddings=True, show_progress_bar=False)
        return vectors.tolist()

    def embed_query(self, question: str) -> list[float]:
        return self.model.encode(question, normalize_embeddings=True).tolist()

    def count_tokens(self, text: str) -> int:
        return len(self.model.tokenizer(text, add_special_tokens=True)["input_ids"])
