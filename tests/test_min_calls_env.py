"""DW_MIN_CALLS : un seuil unique, lu par les règles de fréquence (celles listées dans
scripts.tester_seuils.CHECKS) et par le rejeu (proof.replay.MIN_REPLAY), abaissable pour une démo sur un
workflow à peu d'exécutions. Non définie, chaque règle garde son défaut d'aujourd'hui — la CI n'est
jamais affectée."""
import importlib

import pytest

from proof import replay
from rules import excess_reasoning, harness_overhead, low_entropy, oversized_model, paid_errors, verbose_output

# (module, nom de l'attribut, défaut sans la variable)
ENTRIES = ((oversized_model, "MIN_CALLS", 30), (low_entropy, "MIN_CALLS", 30),
           (verbose_output, "MIN_CALLS", 30), (excess_reasoning, "MIN_CALLS", 30),
           (harness_overhead, "MIN_CALLS", 20), (paid_errors, "MIN_CALLS", 20),
           (replay, "MIN_REPLAY", 30))
MODULES = tuple(m for m, _, _ in ENTRIES)


@pytest.fixture
def env_min_calls(monkeypatch):
    def set_and_reload(value):
        if value is None:
            monkeypatch.delenv("DW_MIN_CALLS", raising=False)
        else:
            monkeypatch.setenv("DW_MIN_CALLS", str(value))
        for m in MODULES:
            importlib.reload(m)
    yield set_and_reload
    set_and_reload(None)  # défaut restauré pour le reste de la suite


def test_defaut_inchange_sans_la_variable(env_min_calls):
    env_min_calls(None)
    for m, attr, default in ENTRIES:
        assert getattr(m, attr) == default


def test_dw_min_calls_abaisse_tout_uniformement(env_min_calls):
    env_min_calls(3)
    for m, attr, _ in ENTRIES:
        assert getattr(m, attr) == 3
