"""Journaux d'invocation Amazon Bedrock → événements Deadweight (lecture seule, sans toucher au code du client)."""
from __future__ import annotations

from pathlib import Path

from connectors.agent_logs.common import Comprehension, number_steps

from .convert import convert, profile_kind
from .source import SourceError, load

__all__ = ["lire", "SourceError"]


def lire(source: str | Path) -> tuple[list[dict], dict]:
    """Source (fichier, dossier, .zip) → (événements triés, rapport de compréhension).

    Lève SourceError si la source est introuvable ou corrompue. Un résultat vide n'est pas une erreur ici :
    c'est à l'appelant (CLI) de refuser « 0 appel » avec le rapport sous les yeux.
    """
    records, bodies, stats = load(source)
    report = Comprehension(str(source))
    report.files = stats["fichiers"]
    if stats["lignes_illisibles"]:
        report.ignore("ligne illisible ou qui n'est pas un enregistrement d'invocation", stats["lignes_illisibles"])
    for name in stats["fichiers_non_reconnus"]:
        report.ignore(f"fichier sans enregistrement d'invocation Bedrock : {Path(name.split('!')[-1]).name}")
    events = [e for e in (convert(r, bodies, report) for r in records) if e is not None]
    events.sort(key=lambda e: e["ts_start"])
    number_steps(events, report)
    report.extra["enregistrements_lus"] = len(records)
    report.extra["corps_externes_fournis"] = stats["corps_externes"]
    geo = sum(profile_kind(e["model"]) == "geo" for e in events)
    if geo:
        report.extra["appels_profil_geographique"] = geo
    _notes(report)
    return events, report.as_dict()


def _notes(report: Comprehension) -> None:
    extra = report.extra
    if extra.get("corps_externes_absents"):
        report.note(f"{int(extra['corps_externes_absents'])} corps de plus de 100 Ko stockés dans S3 "
                    "non fournis : contenu manquant pour ces appels (les jetons sont comptés)")
    if extra.get("appels_sans_contenu"):
        report.note("corps non journalisés (modalité texte non cochée, ou gros corps sans bucket) : "
                    "jetons seulement pour ces appels")
    if extra.get("appels_format_non_reconnu"):
        report.note("corps d'un format de modèle non Anthropic/Converse (Titan, Llama...) : jetons seulement")
    if extra.get("jetons_ecrits_en_cache"):
        report.note("jetons écrits en cache comptés à part (usage.cache_write_input_tokens)")
    report.note("horodatage du journal pris comme début d'appel ; durée = metrics.latencyMs (Converse), "
                "0 pour InvokeModel (non journalisée)")
    report.note("flux (ConverseStream, InvokeModelWithResponseStream) reconstitués selon la forme documentée "
                "des évènements ; à valider sur un vrai journal")
    report.note("l'identité (ARN) et les étiquettes requestMetadata servent à nommer application et workflow, "
                "elles ne sont pas stockées")
