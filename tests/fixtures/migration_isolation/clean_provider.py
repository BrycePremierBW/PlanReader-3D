"""Clean production-shaped provider with no gold/eval imports."""

from pb_migration_contracts import QuantityEvidence

PROVIDER_ID = "clean_shadow"
QuantityEvidence  # keep the import live for AST
