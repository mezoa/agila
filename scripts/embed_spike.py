"""Temporary research spike: embed one sentence with fastembed and print the vector length."""
from pathlib import Path

from fastembed import TextEmbedding

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "fastembed"

model = TextEmbedding("BAAI/bge-small-en-v1.5", cache_dir=str(CACHE_DIR))
vector = next(iter(model.embed(["Agila saves links and answers from them."])))
print("cache dir:", model.model.cache_dir)
print("vector length:", len(vector))
