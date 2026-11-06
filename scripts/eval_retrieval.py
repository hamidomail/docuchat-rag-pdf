"""Measure retrieval quality on a small labelled question set.

    python scripts/eval_retrieval.py            # uses sample_docs/ and eval/questions.json

Reports hit@1, hit@3 and MRR (mean reciprocal rank) of the page that holds the answer.
Re-run it after changing CHUNK_SIZE, TOP_K or EMBEDDINGS_PROVIDER to compare settings.
"""
import json
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.store import DocumentStore, make_embedder  # noqa: E402


def main() -> None:
    cases = json.loads((ROOT / "eval" / "questions.json").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as tmp:
        settings = replace(Settings.from_env(), data_dir=Path(tmp))
        store = DocumentStore(settings, make_embedder(settings))
        for pdf in sorted((ROOT / "sample_docs").glob("*.pdf")):
            store.add_pdf(pdf.name, pdf.read_bytes())

        hit1 = hit3 = rr = 0.0
        for case in cases:
            hits = store.search(case["question"], k=5)
            ranks = [i for i, h in enumerate(hits, 1)
                     if case["doc"] in h.chunk.doc_name and h.chunk.page == case["page"]]
            rank = ranks[0] if ranks else None
            hit1 += rank == 1
            hit3 += bool(rank and rank <= 3)
            rr += 1 / rank if rank else 0
            mark = "ok " if rank == 1 else ("~  " if rank else "MISS")
            print(f"{mark} rank={rank or '-'}  {case['question']}")

    n = len(cases)
    print(f"\n{n} questions | retrieval: {'hybrid' if store.embedder else 'BM25'} | "
          f"hit@1 {hit1 / n:.0%} | hit@3 {hit3 / n:.0%} | MRR {rr / n:.2f}")


if __name__ == "__main__":
    main()
