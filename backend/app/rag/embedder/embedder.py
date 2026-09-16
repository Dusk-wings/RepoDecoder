import logging
from typing import List, Dict, Any
from fastembed import TextEmbedding
import uuid

logger = logging.getLogger(__name__)


class Embedder:
    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        threads: int = 1,
    ) -> None:
        try:
            self.embedder = TextEmbedding(model_name=model_name, threads=threads)
            logger.info(
                "[EMBEDDER] SUCCESSFULLY LOADED THE EMBEDDING MODEL: %s", model_name
            )
        except Exception as e:
            logger.error(
                "[EMBEDDER] FAILED TO LOAD THE TEXT EMBEDDING MODEL %s, ERROR %s",
                model_name,
                e,
            )
            raise

    def count_tokens(self, text: str) -> int:
        return self.embedder.token_count(text)

    def generate_embeddings(
        self,
        content: List[Dict[str, Any]],
        batch_size: int = 32,
        parallel: int = 1,
        file_id: uuid.UUID | None = None,
        repo_id: uuid.UUID | None = None,
    ) -> List[Dict[str, Any]]:

        if not content:
            logger.warning(
                "[EMBEDDER] RECEIVED EMPTY CONTENT LIST. RETURNING EMPTY DATA."
            )
            return []

        try:
            embedding_texts = []

            for index, item in enumerate(content):
                if not isinstance(item, dict):
                    raise TypeError(
                        f"Content item at index {index} must be a dictionary."
                    )

                if "embedding_text" not in item:
                    raise KeyError(
                        f"Content item at index {index} is missing " "'embedding_text'."
                    )

                embedding_text = item["embedding_text"]

                if not isinstance(embedding_text, str):
                    raise TypeError(
                        f"'embedding_text' at index {index} must be a string."
                    )

                embedding_texts.append(embedding_text)

            # `embed()` returns a generator of NumPy arrays.
            embeddings_generator = self.embedder.embed(
                embedding_texts,
                batch_size=batch_size,
                parallel=parallel,
            )

            embeddings = list(embeddings_generator)

            if len(embeddings) != len(content):
                raise ValueError(
                    "The number of generated embeddings does not match the "
                    "number of content items. "
                    f"Expected {len(content)}, got {len(embeddings)}."
                )

            return [
                {
                    "content": item["chunk"],
                    "embedding_text": item["embedding_text"],
                    "embedding": embedding.tolist(),
                    "file_id": file_id,
                    "repo_id": repo_id,
                }
                for item, embedding in zip(content, embeddings)
            ]

        except Exception:
            logger.exception("[EMBEDDER] ERROR GENERATING EMBEDDINGS")
            raise
