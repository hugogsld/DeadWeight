"""DW_MIN_CALLS : un seuil unique, lu par les règles de fréquence (celles listées dans
scripts.tester_seuils.CHECKS), abaissable pour une démo sur un workflow à peu d'exécutions. Non
définie, chaque règle garde son défaut d'aujourd'hui — la CI n'est jamais affectée."""
import importlib

import pytest

from rules import excess_reasoning, harness_overhead, low_entropy, oversized_model, paid_errors, verbose_output

MODULES = (oversized_model, low_entropy, verbose_output, excess_reasoning, harness_overhead, paid_errors)
DEFAULTS = {oversized_model: 30, low_entropy: 30, verbose_output: 30, excess_reasoning: 30,
            harness_overhead: 20, paid_errors: 20}


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
    for m in MODULES:
        assert m.MIN_CALLS == DEFAULTS[m]


def test_dw_min_calls_abaisse_les_six_regles_uniformement(env_min_calls):
    env_min_calls(3)
    for m in MODULES:
        assert m.MIN_CALLS == 3
