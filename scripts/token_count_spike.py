"""Temporary research spike: count bge-small-en-v1.5 tokens with fastembed's own tokenizer."""
from fastembed import TextEmbedding

MODEL = "BAAI/bge-small-en-v1.5"
SAMPLES = [
    "Hello world",
    "Agila saves links and answers from them.",
    "word " * 600,  # longer than the 512-token model limit
]

model = TextEmbedding(MODEL)  # downloads on first run, then reads the cache
inner = model.model  # OnnxTextEmbedding; its tokenizer is a tokenizers.Tokenizer
inner._ensure_tokenizer()
tok = inner.tokenizer

print("model dir:", inner._model_dir)
print("truncation:", tok.truncation)
for text in SAMPLES:
    with_special = tok.encode(text)  # what fastembed counts (add_special_tokens=True)
    without = tok.encode(text, add_special_tokens=False)
    print(
        f"{text[:30]!r:34} token_count={model.token_count(text):4d} "
        f"with_special={len(with_special.ids):4d} without_special={len(without.ids):4d} "
        f"first/last={with_special.tokens[0]},{with_special.tokens[-1]}"
    )
