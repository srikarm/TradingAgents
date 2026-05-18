# Register conftest_pg as a pytest plugin so its fixtures (pg_container,
# pg_engine) are discoverable. pytest only auto-loads files named conftest.py;
# this declaration bridges the gap without modifying tests/conftest.py.
pytest_plugins = ["tests.conftest_pg"]
