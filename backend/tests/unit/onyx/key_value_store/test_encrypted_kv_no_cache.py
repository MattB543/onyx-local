"""Structural regression test: the encrypted KV store must never gain a cache.

``onyx/db/encrypted_kv_store.py`` is the home for instance-level secrets. Its
safety property is structural rather than behavioral: there is no cache code
path at all, so a secret cannot leak into Redis (which is not encrypted at
rest). Behavioral tests can only prove that today's code paths don't cache;
this test proves no cache path exists, so a future "let's speed this up with a
Redis mirror" change trips a red test instead of silently leaking plaintext.
"""

import ast
import inspect

import pytest

import onyx.db.encrypted_kv_store as encrypted_kv_store

# Anything that would indicate a cache/Redis mirror creeping into the module.
_FORBIDDEN_TOKENS = (
    "REDIS_KEY_PREFIX",
    "_get_cache",
    "onyx.cache",
    "redis",
)


def _executable_source() -> str:
    """Round-trip the module through the AST so prose (docstrings, comments)
    can discuss Redis while the check still applies to real code only."""
    tree = ast.parse(inspect.getsource(encrypted_kv_store))
    # Drop the module docstring; ast.unparse already discards comments.
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        tree.body = tree.body[1:]
    return ast.unparse(tree)


@pytest.mark.parametrize("token", _FORBIDDEN_TOKENS)
def test_encrypted_kv_store_module_has_no_cache_references(token: str) -> None:
    source = _executable_source()
    assert token not in source.lower() and token not in source, (
        f"onyx/db/encrypted_kv_store.py references {token!r}. Instance secrets "
        "must never be mirrored into the (unencrypted) cache backend. If a cache "
        "is genuinely required, it must store ciphertext only -- and this test "
        "must be updated deliberately, with that reasoning recorded."
    )
