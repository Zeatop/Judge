# benchmark.py
import argparse
import json
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # charge .env avant d'instancier les providers

from llm_provider import get_provider
from rag_core import build_rag_prompt

PROVIDERS_TO_TEST = [
    {"name": "claude-opus-4-6",   "provider": "claude",   "model": "claude-opus-4-6"},
    {"name": "claude-sonnet-4",   "provider": "claude",   "model": "claude-sonnet-4-20250514"},
    {"name": "deepseek-reasoner", "provider": "deepseek", "model": "deepseek-reasoner"},
    {"name": "deepseek-chat",     "provider": "deepseek", "model": "deepseek-chat"},
]

PRICING = {
    "claude-opus-4-6":            (5.00, 25.00),
    "claude-sonnet-4-20250514":   (3.00, 15.00),
    "deepseek-reasoner":          (0.55,  2.19),
    "deepseek-chat":              (0.28,  0.42),
}


def rough_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def run_benchmark(questions_file: str, output_file: str):
    questions = json.loads(Path(questions_file).read_text())
    results = []

    for q in questions:
        print(f"\n🔹 {q['question'][:80]}...")
        prompt, chunks, cards = build_rag_prompt(q["question"], q.get("game_id"))
        in_tokens = rough_tokens(prompt)
        print(f"   chunks={chunks}  cards={cards}  prompt~{in_tokens} tokens")

        for cfg in PROVIDERS_TO_TEST:
            try:
                llm = get_provider(cfg["provider"], model=cfg["model"])
                t0 = time.perf_counter()
                answer = llm.invoke(prompt)
                dt = time.perf_counter() - t0

                out_tokens = rough_tokens(answer)
                in_p, out_p = PRICING.get(cfg["model"], (0, 0))
                cost = (in_tokens / 1_000_000) * in_p + (out_tokens / 1_000_000) * out_p

                results.append({
                    "question": q["question"],
                    "game_id": q.get("game_id"),
                    "expected": q.get("expected", ""),
                    "provider": cfg["name"],
                    "chunks_used": chunks,
                    "latency_s": round(dt, 2),
                    "in_tokens_est": in_tokens,
                    "out_tokens_est": out_tokens,
                    "cost_usd": round(cost, 6),
                    "answer": answer,
                })
                print(f"   ✅ {cfg['name']:25s} {dt:6.2f}s  ${cost:.5f}")
            except Exception as e:
                print(f"   ❌ {cfg['name']:25s} ERROR: {e}")
                results.append({"question": q["question"], "provider": cfg["name"], "error": str(e)})

    # Markdown
    lines = ["# Benchmark LLM — Judge AI\n"]
    for q in questions:
        lines.append(f"## {q['question']}\n")
        if q.get("expected"):
            lines.append(f"**Attendu :** {q['expected']}\n")
        lines.append("| Provider | Latence | Tok in/out | Coût | Réponse |")
        lines.append("|---|---|---|---|---|")
        for r in results:
            if r["question"] != q["question"] or "error" in r:
                continue
            ans_short = r["answer"].replace("\n", " ").replace("|", "\\|")[:200] + "..."
            lines.append(
                f"| {r['provider']} | {r['latency_s']}s | "
                f"{r['in_tokens_est']}/{r['out_tokens_est']} | "
                f"${r['cost_usd']:.5f} | {ans_short} |"
            )
        lines.append("\n---\n")

    Path(output_file).write_text("\n".join(lines))
    Path(output_file.replace(".md", ".json")).write_text(
        json.dumps(results, indent=2, ensure_ascii=False)
    )
    print(f"\n📊 Rapport : {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("questions")
    parser.add_argument("--out", default="benchmark_results.md")
    args = parser.parse_args()
    run_benchmark(args.questions, args.out)