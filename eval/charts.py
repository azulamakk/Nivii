#!/usr/bin/env python3
"""
Generate benchmark visualisation charts from eval/results.json.
Usage:
    pip install -r eval/requirements.txt
    python3 eval/charts.py
Output: eval/charts/*.png
"""
from pathlib import Path
import json
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
import numpy as np

RESULTS_PATH = Path(__file__).parent / "results.json"
OUT_DIR = Path(__file__).parent / "charts"
OUT_DIR.mkdir(exist_ok=True)

# Memory tier per model — matches decisions.md §7
TIER_5GB = {"gemma3:4b", "qwen3.5:2b", "llama3.2:3b", "gemma2:2b"}
TIER_8GB = {"qwen2.5-coder:7b", "qwen3.5:4b", "gemma4:e2b"}
COLOR_4GB = "#27ae60"
COLOR_5GB = "#e67e22"
COLOR_8GB = "#8e44ad"

sns.set_theme(style="whitegrid", font_scale=1.1)


def load_results():
    data = json.loads(RESULTS_PATH.read_text())
    return [r for r in data if r["status"] == "ok"]


def tier_color(model: str) -> str:
    if model in TIER_8GB:
        return COLOR_8GB
    if model in TIER_5GB:
        return COLOR_5GB
    return COLOR_4GB


def short_name(model: str) -> str:
    return (
        model
        .replace("qwen2.5-coder", "qwen2.5c")
        .replace("deepseek-coder", "deepseek-c")
        .replace("gemma4:e2b", "gemma4-e2b")
    )


# ── Chart 1: Correctness vs Latency trade-off ─────────────────────────────────

def chart_correctness_vs_latency(data):
    fig, ax = plt.subplots(figsize=(10, 6))

    # Shade ideal quadrant (low latency, high correctness)
    ax.axhspan(60, 100, xmin=0, xmax=0.35, alpha=0.06, color=COLOR_4GB, zorder=0)
    ax.text(0.72, 73, "ideal zone", color=COLOR_4GB, fontsize=9, alpha=0.6)

    # 60% threshold line
    ax.axhline(60, color="grey", linestyle="--", linewidth=1, alpha=0.7, label="60% threshold")

    for r in data:
        x = r["avg_latency_s"]
        y = r["correctness_rate"]
        size = (r["sql_validity_rate"] / 100) * 300 + 50
        color = tier_color(r["model"])
        ax.scatter(x, y, s=size, color=color, alpha=0.85, edgecolors="white", linewidth=0.8, zorder=3)
        ax.annotate(
            short_name(r["model"]),
            (x, y),
            textcoords="offset points",
            xytext=(8, 4),
            fontsize=8.5,
            color="#333333",
        )

    ax.set_xscale("log")
    ax.set_xlabel("Average latency (s, log scale)")
    ax.set_ylabel("Correctness (%)")
    ax.set_title("Correctness vs Latency — trade-off across all models")
    ax.set_ylim(0, 85)

    legend_handles = [
        mpatches.Patch(color=COLOR_4GB, label="≤ 4 GB Docker (standard)"),
        mpatches.Patch(color=COLOR_5GB, label="5 GB Docker (ampliado)"),
        mpatches.Patch(color=COLOR_8GB, label="8 GB Docker (avanzado)"),
        plt.Line2D([0], [0], color="grey", linestyle="--", label="60% threshold"),
    ]
    ax.legend(handles=legend_handles, fontsize=9, loc="upper left")

    plt.tight_layout()
    out = OUT_DIR / "correctness_vs_latency.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {out}")


# ── Chart 2: ES vs EN correctness ─────────────────────────────────────────────

def chart_language_split(data):
    rows = [
        r for r in data
        if r.get("es_correctness_rate") is not None and r.get("en_correctness_rate") is not None
    ]
    rows.sort(key=lambda r: r["correctness_rate"], reverse=True)

    models = [short_name(r["model"]) for r in rows]
    es_vals = [r["es_correctness_rate"] for r in rows]
    en_vals = [r["en_correctness_rate"] for r in rows]

    x = np.arange(len(models))
    width = 0.35

    fig, ax = plt.subplots(figsize=(11, 5))
    bars_es = ax.bar(x - width / 2, es_vals, width, label="ES (Spanish)", color="#3498db", alpha=0.85)
    bars_en = ax.bar(x + width / 2, en_vals, width, label="EN (English)", color="#e74c3c", alpha=0.85,
                     hatch="//", edgecolor="white")

    ax.axhline(60, color="grey", linestyle="--", linewidth=1, alpha=0.7, label="60% threshold")

    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=20, ha="right", fontsize=9)
    ax.set_ylabel("Correctness (%)")
    ax.set_ylim(0, 95)
    ax.set_title("Correctness by language — Spanish vs English")
    ax.legend(fontsize=9)

    for bar in list(bars_es) + list(bars_en):
        h = bar.get_height()
        ax.text(bar.get_x() + bar.get_width() / 2, h + 1, f"{h:.0f}%",
                ha="center", va="bottom", fontsize=7.5, color="#333333")

    plt.tight_layout()
    out = OUT_DIR / "language_split.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {out}")


# ── Chart 3: Correctness by difficulty tier ───────────────────────────────────

def chart_difficulty_breakdown(data):
    rows = sorted(data, key=lambda r: r["correctness_rate"], reverse=True)

    tiers = ["simple", "medium", "hard"]
    tier_colors = {"simple": "#2ecc71", "medium": "#f39c12", "hard": "#e74c3c"}

    models_labels = []
    tier_rates: dict[str, list[float]] = {t: [] for t in tiers}

    for r in rows:
        queries = r.get("results", [])
        models_labels.append(short_name(r["model"]))
        for tier in tiers:
            tier_qs = [q for q in queries if q["difficulty"] == tier]
            rate = (sum(1 for q in tier_qs if q["correct"]) / len(tier_qs) * 100) if tier_qs else 0
            tier_rates[tier].append(rate)

    x = np.arange(len(models_labels))
    width = 0.22
    offsets = [-width, 0, width]

    fig, ax = plt.subplots(figsize=(11, 5))
    for i, tier in enumerate(tiers):
        bars = ax.bar(x + offsets[i], tier_rates[tier], width,
                      label=tier.capitalize(), color=tier_colors[tier], alpha=0.85)
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                ax.text(bar.get_x() + bar.get_width() / 2, h + 1, f"{h:.0f}%",
                        ha="center", va="bottom", fontsize=7, color="#333333")

    ax.axhline(60, color="grey", linestyle="--", linewidth=1, alpha=0.6, label="60% threshold")
    ax.set_xticks(x)
    ax.set_xticklabels(models_labels, rotation=20, ha="right", fontsize=9)
    ax.set_ylabel("Correctness (%)")
    ax.set_ylim(0, 115)
    ax.set_title("Correctness by difficulty tier")
    ax.legend(fontsize=9)

    plt.tight_layout()
    out = OUT_DIR / "difficulty_breakdown.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {out}")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    data = load_results()
    if not data:
        print("No results with status=ok found in results.json. Run the benchmark first.")
        raise SystemExit(1)

    print(f"Generating charts for {len(data)} model(s)...")
    chart_correctness_vs_latency(data)
    chart_language_split(data)
    chart_difficulty_breakdown(data)
    print(f"\nDone — charts saved to {OUT_DIR}/")
