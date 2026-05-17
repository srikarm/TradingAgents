from __future__ import annotations

from pathlib import Path

from app.schemas.run import ReportSections

# section name → relative path under <results_path>/reports/
_SECTION_FILES: dict[str, tuple[str, ...]] = {
    "market": ("1_analysts", "market.md"),
    "sentiment": ("1_analysts", "sentiment.md"),
    "news": ("1_analysts", "news.md"),
    "fundamentals": ("1_analysts", "fundamentals.md"),
    "investment_plan": ("2_research", "manager.md"),
    "trader_plan": ("3_trading", "trader.md"),
    "final": ("final_trade_decision.md",),
}


def load_report_sections(results_path: str) -> ReportSections:
    """Read all known markdown sections from a run's results_path.

    Missing files are returned as None. Paths are joined under the supplied
    results_path; the caller is responsible for ensuring results_path was
    produced by `user_root` (this function does not re-validate).
    """
    base = Path(results_path) / "reports"
    out: dict[str, str | None] = {}
    for section, parts in _SECTION_FILES.items():
        path = base.joinpath(*parts)
        if path.is_file():
            try:
                out[section] = path.read_text(encoding="utf-8")
            except OSError:
                out[section] = None
        else:
            out[section] = None
    return ReportSections(**out)
