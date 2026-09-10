"""Provider that reaches gold only through a helper — transitive leak."""

from tests.fixtures.migration_isolation.dirty_helper import LEAK

PROVIDER_ID = "dirty_shadow"
TRANSITIVE_LEAK = LEAK
