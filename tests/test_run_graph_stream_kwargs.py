"""Pin the stream_mode dedup contract in _run_graph.

Regression guard for a production bug discovered during a Playwright
demo on 2026-05-18: PR #13 (shipped earlier the same day) added the
progress_callback branch to `TradingAgentsGraph._run_graph` and called
`self.graph.stream(init, **args, stream_mode=["values", "updates"])`.

The kwargs dict `args` is built by `propagator.get_graph_args()`, which
already includes `"stream_mode": "values"` (intended for the debug
branch's `graph.stream(init, **args)` call). When the new branch
spreads `args` AND passes `stream_mode` explicitly, Python raises:

    TypeError: stream() got multiple values for keyword argument
    'stream_mode'

The bug was caught by PR #13's reviewer-prompt verification list as a
TODO but never empirically exercised — the unit tests for #9 use a
StubGraph that short-circuits the real `graph.stream()` call, so the
duplicate-kwarg error never fires in CI.

This test pins the dedup logic by reading the source file directly
(NOT importing `tradingagents.graph.trading_graph`, which pulls in
yfinance and other heavy deps not present in every test environment).
A pure behavioral test would require constructing a real
`TradingAgentsGraph` — heavyweight for a one-line contract.
"""

from pathlib import Path


def _trading_graph_source() -> str:
    """Read trading_graph.py without importing it.

    The module's top-level `import yfinance` would fail in test environments
    that don't have the runtime deps installed (this is the same env where
    11 unrelated library tests already fail at collection time). Source-text
    inspection sidesteps the dep graph entirely.
    """
    src_path = (
        Path(__file__).resolve().parent.parent
        / "tradingagents"
        / "graph"
        / "trading_graph.py"
    )
    return src_path.read_text(encoding="utf-8")


def test_run_graph_progress_callback_branch_dedupes_stream_mode():
    src = _trading_graph_source()

    # The progress_callback branch must strip stream_mode from args before
    # spreading. Accept either a dict comprehension or an args.pop() form —
    # both achieve the same effect.
    dict_comp_dedupe = (
        'for k, v in args.items() if k != "stream_mode"' in src
        or "for k, v in args.items() if k != 'stream_mode'" in src
    )
    args_pop_dedupe = (
        'args.pop("stream_mode"' in src or "args.pop('stream_mode'" in src
    )

    assert dict_comp_dedupe or args_pop_dedupe, (
        "_run_graph's progress_callback branch must remove 'stream_mode' from "
        "args before passing stream_mode=['values','updates'] to graph.stream(), "
        "or Python raises 'got multiple values for keyword argument'. "
        "Use either a {k:v for k,v in args.items() if k!='stream_mode'} dict "
        "comprehension or args.pop('stream_mode', None) before the stream call."
    )


def test_run_graph_progress_callback_branch_uses_list_stream_mode():
    """The whole point of the new branch is to get (mode, chunk) tuples by
    requesting both "values" (for final-state accumulation) and "updates"
    (for per-node progress callbacks). LangGraph yields tuples ONLY when
    stream_mode is a list — a string mode yields chunks directly."""
    src = _trading_graph_source()

    list_form = (
        'stream_mode=["values", "updates"]' in src
        or "stream_mode=['values', 'updates']" in src
    )
    assert list_form, (
        "_run_graph's progress_callback branch must call graph.stream with "
        "stream_mode=['values', 'updates'] (list form) so LangGraph yields "
        "(mode, chunk) tuples. A scalar stream_mode would yield chunks "
        "directly and break the `for mode, chunk in ...` unpacking."
    )
