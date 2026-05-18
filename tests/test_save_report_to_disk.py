"""Regression test for v3+ followup #8.

`save_report_to_disk` is a library-level utility (it consumes graph output
and writes markdown reports to disk). Previously it lived in `cli/main.py`,
which forced anyone who wanted to persist a final_state — server worker,
notebook user, future API consumer — to either re-implement it (see
`server/app/workers/tasks.py:_persist_reports`) or import from the CLI
entry point. Moving it into the library proper makes it the canonical
report writer.

This test pins both the public location and the on-disk layout contract.
"""

import datetime
from pathlib import Path


def _minimal_final_state() -> dict:
    """A final_state shape carrying one item from each report section, so
    the test exercises every directory the function creates."""
    return {
        "market_report": "# Market\nBullish on momentum.",
        "sentiment_report": "# Sentiment\nNeutral.",
        "news_report": "# News\nNothing material.",
        "fundamentals_report": "# Fundamentals\nP/E in range.",
        "investment_debate_state": {
            "bull_history": "bull case",
            "bear_history": "bear case",
            "judge_decision": "manager favors bull",
        },
        "trader_investment_plan": "buy 100 shares",
        "risk_debate_state": {
            "aggressive_history": "load up",
            "conservative_history": "stay light",
            "neutral_history": "rebalance modestly",
            "judge_decision": "BUY — moderate size",
        },
    }


def test_save_report_to_disk_is_importable_from_tradingagents(tmp_path: Path):
    """v3+ #8: function moved out of cli/main.py into tradingagents library."""
    from tradingagents.reports import save_report_to_disk

    report_file = save_report_to_disk(
        _minimal_final_state(), "NVDA", tmp_path / "NVDA"
    )

    assert report_file == tmp_path / "NVDA" / "complete_report.md"
    assert report_file.is_file()


def test_save_report_to_disk_writes_per_section_files(tmp_path: Path):
    """Each section the function knows about must be written to its own
    subdirectory with the expected filename. Pins the on-disk contract that
    `server/app/workers/tasks.py:_persist_reports` mirrors."""
    from tradingagents.reports import save_report_to_disk

    save_path = tmp_path / "NVDA"
    save_report_to_disk(_minimal_final_state(), "NVDA", save_path)

    # 1. Analysts
    assert (save_path / "1_analysts" / "market.md").read_text() == "# Market\nBullish on momentum."
    assert (save_path / "1_analysts" / "sentiment.md").is_file()
    assert (save_path / "1_analysts" / "news.md").is_file()
    assert (save_path / "1_analysts" / "fundamentals.md").is_file()
    # 2. Research
    assert (save_path / "2_research" / "bull.md").is_file()
    assert (save_path / "2_research" / "bear.md").is_file()
    assert (save_path / "2_research" / "manager.md").is_file()
    # 3. Trading
    assert (save_path / "3_trading" / "trader.md").is_file()
    # 4. Risk
    assert (save_path / "4_risk" / "aggressive.md").is_file()
    assert (save_path / "4_risk" / "conservative.md").is_file()
    assert (save_path / "4_risk" / "neutral.md").is_file()
    # 5. Portfolio Manager decision
    assert (save_path / "5_portfolio" / "decision.md").is_file()
    # Consolidated header carries the ticker.
    consolidated = (save_path / "complete_report.md").read_text()
    assert "NVDA" in consolidated


def test_save_report_to_disk_skips_missing_sections(tmp_path: Path):
    """If a section is absent from final_state, its directory must NOT be
    created — only sections with content are written."""
    from tradingagents.reports import save_report_to_disk

    sparse = {"market_report": "only one section"}
    save_path = tmp_path / "MIN"
    save_report_to_disk(sparse, "MIN", save_path)

    assert (save_path / "1_analysts" / "market.md").is_file()
    assert not (save_path / "2_research").exists()
    assert not (save_path / "3_trading").exists()
    assert not (save_path / "4_risk").exists()
    assert not (save_path / "5_portfolio").exists()
    assert (save_path / "complete_report.md").is_file()
