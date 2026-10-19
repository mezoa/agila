"""TEMPORARY spike (block c, C3): time 10 cited-answer calls against a local Ollama model.

Usage: python scripts/ollama_spike.py qwen3.5:4b

Exception to the "only llm.py talks to Ollama" rule; delete this file once llm.py exists.
"""

import json
import statistics
import sys
import time
import urllib.request

BASE_URL = "http://127.0.0.1:11434"

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answerable": {"type": "boolean"},
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "integer"},
                    "sentence": {"type": "integer"},
                },
                "required": ["chunk_id", "sentence"],
            },
        },
    },
    "required": ["answerable", "answer", "citations"],
}

INSTRUCTIONS = (
    "Answer the question using only the numbered passages below. "
    "If they do not contain the answer, set answerable to false, answer to an empty string "
    "and citations to an empty list. Otherwise cite the chunk_id and the sentence number "
    "(starting at 1) that support the answer. Reply as JSON."
)

# (question, three passages as lists of sentences, expected answerable)
QUESTIONS = [
    (
        "Is pgvector search exact or approximate without an index?",
        [
            "pgvector does exact nearest neighbor search by default. It checks every row.",
            "An index such as HNSW makes search approximate and faster.",
            "The extension is enabled once per database with CREATE EXTENSION vector.",
        ],
        True,
    ),
    (
        "Which operator gives cosine distance in pgvector?",
        [
            "The <=> operator returns cosine distance. Similarity is 1 minus the distance.",
            "The <-> operator returns Euclidean distance.",
            "The <#> operator returns the negative inner product.",
        ],
        True,
    ),
    (
        "How does a container reach a service running on the Windows host?",
        [
            "Docker Desktop provides the DNS name host.docker.internal. Containers use it to "
            "reach the host.",
            "Published ports are opened with the -p flag.",
            "Binding a port to 127.0.0.1 keeps it off the local network.",
        ],
        True,
    ),
    (
        "Where does Postgres 18 keep its data inside the image?",
        [
            "Postgres 18 images keep data under /var/lib/postgresql.",
            "Images for version 17 and older use /var/lib/postgresql/data.",
            "Mount the volume at the path that matches the image tag.",
        ],
        True,
    ),
    (
        "How long does Ollama keep a model loaded by default?",
        [
            "Ollama keeps a model in memory for 5 minutes after the last request.",
            "The keep_alive field changes this per request. A value of -1 keeps it forever.",
            "Setting keep_alive to 0 unloads the model right away.",
        ],
        True,
    ),
    (
        "Which command adds a dependency to a uv project?",
        [
            "uv add installs a package and records it in pyproject.toml.",
            "uv run executes a command inside the project environment.",
            "uv sync makes the environment match the lock file.",
        ],
        True,
    ),
    (
        "What is the default HNSW ef_search value in pgvector?",
        [
            "pgvector does exact nearest neighbor search by default.",
            "The <=> operator returns cosine distance.",
            "CREATE EXTENSION vector enables the extension.",
        ],
        False,
    ),
    (
        "Which Postgres version added the MERGE command?",
        [
            "Postgres 18 images keep data under /var/lib/postgresql.",
            "The db service uses the pgvector/pgvector image.",
            "Host port 5433 maps to container port 5432.",
        ],
        False,
    ),
    (
        "How many GPU layers does Ollama offload by default?",
        [
            "Ollama keeps a model in memory for 5 minutes.",
            "The default context length is 4096 tokens.",
            "The API listens on 127.0.0.1:11434.",
        ],
        False,
    ),
    (
        "Which Python version does Docker Compose require?",
        [
            "uv add installs a package.",
            "uv init creates pyproject.toml and a src folder.",
            "uv run executes a command in the project environment.",
        ],
        False,
    ),
]


def build_prompt(question, passages):
    lines = [INSTRUCTIONS, ""]
    for chunk_id, sentences in enumerate(passages, start=1):
        numbered = " ".join(f"[{n}] {s}" for n, s in enumerate(_split(sentences), start=1))
        lines.append(f"Passage {chunk_id}: {numbered}")
    lines += ["", f"Question: {question}"]
    return "\n".join(lines)


def _split(text):
    parts = [p.strip() for p in text.replace("? ", "?|").replace(". ", ".|").split("|")]
    return [p for p in parts if p]


def generate(base_url, model, prompt):
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "format": ANSWER_SCHEMA,
        }
    ).encode()
    request = urllib.request.Request(
        f"{base_url}/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.load(response)["response"]


def run(model, base_url=BASE_URL):
    """Warm up once, then time each question. Returns a list of result dicts."""
    generate(base_url, model, "Reply with the JSON for an unanswerable question.")
    results = []
    for question, passages, _expected in QUESTIONS:
        prompt = build_prompt(question, passages)
        start = time.perf_counter()
        reply = generate(base_url, model, prompt)
        seconds = time.perf_counter() - start
        try:
            answerable = json.loads(reply).get("answerable")
            valid = True
        except (json.JSONDecodeError, AttributeError):
            answerable, valid = None, False
        results.append(
            {"question": question, "seconds": seconds, "valid": valid, "answerable": answerable}
        )
    return results


def main(argv, base_url=BASE_URL):
    if len(argv) != 2:
        print("usage: python scripts/ollama_spike.py <model>")
        return 2
    results = run(argv[1], base_url)
    for i, r in enumerate(results, start=1):
        print(f"Q{i}: {r['seconds']:.1f} s  json_ok={r['valid']}  answerable={r['answerable']}")
    times = [r["seconds"] for r in results]
    print(
        f"median {statistics.median(times):.1f} s, min {min(times):.1f} s, "
        f"max {max(times):.1f} s, valid JSON {sum(r['valid'] for r in results)}/{len(results)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
