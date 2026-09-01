import logging
from typing import List, Dict, Any
from fastembed import TextEmbedding

logger = logging.getLogger(__name__)

class Embedder:
    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        threads: int = 1,
    ) -> None:
        try:
            self.embedder = TextEmbedding(model_name=model_name, threads=threads)
            logger.info(f"Successfully loaded embedding model: {model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize TextEmbedding model '{model_name}': {e}")
            raise

    def generate_embeddings(
        self, 
        content: List[str], 
        batch_size: int = 32, 
        parallel: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Generates embeddings for a list of strings.
        """
        if not content:
            logger.warning("Received empty content list. Returning empty data.")
            return []

        try:
            # embed() returns a generator of numpy arrays
            embeddings_generator = self.embedder.embed(
                content,
                batch_size=batch_size,
                parallel=parallel,
            )

            # Consume the generator directly into the final data structure
            # to avoid exhausting it prematurely or storing it twice in memory.
            data = [
                {"text": text, "embedding": emb.tolist()}
                for text, emb in zip(content, embeddings_generator)
            ]

            return data
            
        except Exception as e:
            logger.error(f"Error generating embeddings: {e}")
            raise