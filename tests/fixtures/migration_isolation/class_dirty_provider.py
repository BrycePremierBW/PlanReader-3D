"""Forbidden import nested inside a class method."""


class DirtyEngine:
    def extract(self):
        import pb_holdout_suite_registry as _holdout

        return _holdout


PROVIDER_ID = "class_dirty"
