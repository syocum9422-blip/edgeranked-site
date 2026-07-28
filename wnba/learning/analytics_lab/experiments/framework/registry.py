"""Plug-in discovery. The runner resolves experiments through here and never
imports one by name.

An experiment module registers itself by exposing a module-level `EXPERIMENT`
instance. `discover()` imports every module in `experiments/catalog/` and
collects them, so adding a research question means adding one file.
"""
from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from analytics_lab.experiments.framework.base import Experiment

CATALOG_PACKAGE = "analytics_lab.experiments.catalog"


def discover() -> dict[str, Experiment]:
    """Import the catalog and return {experiment_id: experiment}."""
    package = importlib.import_module(CATALOG_PACKAGE)
    found: dict[str, Experiment] = {}
    for info in pkgutil.iter_modules(package.__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{CATALOG_PACKAGE}.{info.name}")
        experiment = getattr(module, "EXPERIMENT", None)
        if experiment is None:
            continue
        experiment_id = experiment.manifest.experiment_id
        if experiment_id in found:
            raise ValueError(
                f"duplicate experiment id {experiment_id}: "
                f"{info.name} and {found[experiment_id].__class__.__module__}"
            )
        found[experiment_id] = experiment
    return dict(sorted(found.items()))


def get(experiment_id: str) -> Experiment:
    catalog = discover()
    if experiment_id not in catalog:
        raise KeyError(f"unknown experiment {experiment_id!r}; known: {sorted(catalog)}")
    return catalog[experiment_id]
