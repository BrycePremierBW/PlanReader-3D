"""Forbidden import nested inside a function."""


def extract():
    import pb_benchmark_accuracy_engine as _gold

    return _gold


PROVIDER_ID = "fn_dirty"
