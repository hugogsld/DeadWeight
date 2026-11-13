"""Régénère fixtures/pricing.bedrock.json depuis le catalogue public AWS Price List (sans clé, sans compte).

    mkdir -p /tmp/bedrock-prices && cd /tmp/bedrock-prices
    B=https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws
    for r in us-east-1 eu-west-1 eu-central-1; do
      curl -sSo fm_$r.json $B/AmazonBedrockFoundationModels/current/$r/index.json   # Claude seulement
    done
    python3 fixtures/bedrock/pricing_from_aws.py /tmp/bedrock-prices

Tarifs en USD par million de jetons, à la demande. Deux portées : « regional » (profil géographique eu./us. ou
appel direct dans la région) et « global » (profil global.). Un prix n'est écrit que s'il est lu dans le fichier.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

RETIRED = re.compile(r"Claude (2\.\d|Instant)")  # modèles retirés, prix incohérents entre régions
REGIONS = ("us-east-1", "eu-west-1", "eu-central-1")
OUT = Path(__file__).resolve().parents[1] / "pricing.bedrock.json"


def slug(name: str) -> str:
    """« Claude Sonnet 5.5 » → claude-sonnet-5-5 ; « Claude 3.5 Sonnet v2 » → claude-3-5-sonnet."""
    s = re.sub(r"\s+v\d+$", "", name.lower())
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def classify_claude(usagetype: str) -> tuple[str, str] | None:
    """usagetype Claude → (portée, champ) ; None pour ce qui n'est pas du jeton à la demande."""
    low = re.sub(r"^[A-Za-z0-9-]*?-MP:[A-Za-z0-9]+_", "", usagetype).lower()
    if re.search(r"reserved|provisioned|custom|storage|training|latencyoptimized|long_ctx|millionbatch|mantle", low):
        return None
    scope = "global" if "global" in low else "regional"
    if re.search(r"cachewrite1h|cache_write_tokens_1h", low):
        field = "cache_write_1h_in"
    elif re.search(r"cachewrite|cache_write", low):
        field = "cache_write_in"
    elif re.search(r"cacheread|cache_read", low):
        field = "cached_in"
    elif re.match(r"inputtokencount|input_tokens", low):
        field = "in"
    elif re.match(r"outputtokencount|output_tokens", low):
        field = "out"
    else:
        return None
    if "batch" in low:
        if field not in ("in", "out"):
            return None
        field = "batch_" + field
    return scope, field


def read(directory: Path, region: str, wanted) -> dict:
    """Un fichier d'offre → {modèle: {portée: {champ: USD/Mjetons}}} pour les modèles voulus."""
    data = json.loads((directory / f"fm_{region}.json").read_text(encoding="utf-8"))
    out: dict = {}
    for sku, product in data["products"].items():
        attrs = product["attributes"]
        name = wanted(attrs.get("model", ""))
        if not name:
            continue
        found = classify_claude(attrs.get("usagetype", ""))
        if not found:
            continue
        for term in data["terms"].get("OnDemand", {}).get(sku, {}).values():
            for dim in term["priceDimensions"].values():
                usd = float(dim["pricePerUnit"]["USD"])
                out.setdefault(name, {}).setdefault(found[0], {})[found[1]] = round(usd, 6)
    return {"data": out, "published": data["publicationDate"]}


def build(directory: Path) -> dict:
    """Assemble le fichier : union des trois régions, refuse un même prix qui diffère d'une région à l'autre."""
    per_region, dates = {}, set()
    for region in REGIONS:
        claude = read(directory, region, lambda m: slug(m) if m.startswith("Claude") and not RETIRED.search(m) else None)
        per_region[region] = claude["data"]
        dates.add(claude["published"])
    merged: dict = {}
    for region in REGIONS:
        for model, scopes in per_region[region].items():
            for scope, fields in scopes.items():
                for field, price in fields.items():
                    seen = merged.setdefault(model, {}).setdefault(scope, {}).setdefault(field, price)
                    if seen != price:
                        raise SystemExit(f"prix différents selon la région : {model} {scope} {field} ({region})")
    models = {}
    for model, scopes in merged.items():
        entry = dict(scopes.get("regional") or scopes.get("global") or {})
        if "global" in scopes and "regional" in scopes:
            entry["global"] = scopes["global"]
        models[model] = entry
    return {"_meta": meta(sorted(dates)), "models": dict(sorted(models.items()))}


def meta(dates: list[str]) -> dict:
    return {
        "source": "https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/ (AmazonBedrockFoundationModels, Claude), régions us-east-1, eu-west-1, eu-central-1",
        "retrieved": date.today().isoformat(),
        "published": dates,
        "verified": True,
        "unit": "USD par million de jetons, à la demande",
        "scopes": "clés à la racine = portée régionale (profil eu./us./apac. ou appel direct) ; sous-clé « global » = "
                  "profil global. Modèle sans « global » : pas de profil global au catalogue.",
        "region_pricing": "quand un tarif figure dans plusieurs des trois régions lues il est identique (contrôlé par le script) ; la disponibilité (batch, profil global) varie selon la région ; GovCloud exclu, "
                          "autres régions non lues.",
        "fields": "in, out, cached_in (cache lu), cache_write_in (écriture TTL 5 min), cache_write_1h_in (TTL 1 h), "
                  "batch_in/batch_out (inférence par lots), flex_in/flex_out/flex_cached_in (niveau Flex).",
        "absent": "Claude : aucun tarif Flex ni Priority au catalogue ; batch seulement sur une partie des modèles "
                  "(champ absent = non listé).",
        "not_read": "contexte long (long_ctx), débit provisionné ou réservé, Nova, Llama, Mistral : non repris "
                    "(les tarifs Nova varient selon la région, ce fichier ne porte qu'un tarif par modèle).",
        "hypothesis": "un appel direct dans une région (sans préfixe de profil) est supposé facturé au tarif régional ; "
                      "le journal ne dit pas quel TTL a servi pour les écritures de cache sauf si cacheDetails est présent.",
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    OUT.write_text(json.dumps(build(Path(sys.argv[1])), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"écrit : {OUT}")
