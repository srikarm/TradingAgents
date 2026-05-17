def test_can_import_tradingagents_graph():
    """The worker needs to import from the root tradingagents package.

    This test only passes if the server's environment has the root
    tradingagents package installed (via path-dep in pyproject.toml).
    """
    from tradingagents.default_config import DEFAULT_CONFIG  # noqa: F401
