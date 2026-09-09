"""Literal importlib.import_module of a forbidden module."""

import importlib

importlib.import_module("pb_public_tender_benchmark")

PROVIDER_ID = "importlib_dirty"
