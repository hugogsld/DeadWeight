"""Le message Slack : les gains prouvés, activables en acceptant des micro-PR.

Les chiffres d'en-tête ne viennent que des propositions validées (verdict « pass ») et de mesures au
statut « mesuré » ; une estimation apparaît avec « ~ » et n'entre jamais dans un total. Le coût total est
calculé en dollars sur la période observée, jamais en additionnant des pourcentages de périmètres différents.
Sur abonnement (Claude Code Max, ChatGPT Plus…), le forfait ne baisse pas : le dollar gagné est une valeur
équivalente API et une marge sur les limites d'usage, jamais présenté comme une économie sur la facture.
"""


LEVELS = {"precision"}  # un niveau, pas une variation : jamais de signe
TOTAL = {False: "de la dépense totale", True: "de la valeur consommée (équiv. API)"}


def _fmt(v, unit="", level=False):
    if v is None:
        return "—"
    sign = "+" if isinstance(v, (int, float)) and v > 0 and unit == "%" and not level else ""
    return f"{sign}{v:g}{' ' + unit if unit and unit != '%' else unit}"


def _line(p, link, total_spent=None, equivalent_api=False):
    m = p["mesures"]
    icon = {"pass": "✅", "reject": "⛔", "non_teste": "◻️"}.get(p["verdict"], "•")
    parts = []
    # ordre imposé : contexte envoyé, coût, latence médiane, précision (D2.6, Problème 2) ; les deux
    # figures restantes (latence p95, jetons de sortie) suivent, en détail secondaire.
    for key, label in (("jetons_envoyes", "contexte envoyé"), ("cout", "coût"),
                       ("latence_mediane", "latence médiane"), ("precision", "précision"),
                       ("latence_p95", "latence p95"), ("jetons_sortie", "jetons de sortie")):
        v = m.get(key)
        ms = p.get("latence_ms") or {}
        if key == "latence_mediane" and v and v["valeur"] == -100.0 and None not in (ms.get("avant"), ms.get("apres")):
            # -100 % seul ressemble à un bug : les millisecondes mesurées, comme dans le tableau du testeur
            parts.append(f"{label} {ms['avant']:.0f} ms → {ms['apres']:.0f} ms")
        elif v and v["valeur"] is not None:
            parts.append(f"{label} {'~' if v['statut'] != 'mesuré' else ''}{_fmt(v['valeur'], v['unite'], key in LEVELS)}")
    detail = ("Pour cette tâche : " + ", ".join(parts)) if parts else "; ".join(p.get("raisons") or ["non testé"])
    # part de la dépense totale : seulement si le coût de cette tâche est mesuré (jamais estimé), et
    # seulement des dollars sur la même période — jamais un pourcentage d'un autre périmètre.
    cout = p.get("cout_usd")
    share = ""
    if (p["verdict"] == "pass" and cout and cout.get("statut") == "mesuré" and total_spent
            and cout.get("avant") is not None and cout.get("apres") is not None):
        share = f", soit {(cout['avant'] - cout['apres']) / total_spent * 100:.0f} % {TOTAL[equivalent_api]}"
    pr = f" → <{link}|accepter la PR>" if link and p["verdict"] == "pass" else ""
    why = f" ({'; '.join(p['raisons'])})" if p["verdict"] == "reject" and p.get("raisons") else ""
    return f"{icon} *{p['app_id']}* — {p['changement']}\n      {detail}{share}{why}{pr}"


def message(proposals, links=None, total_spent=None, show_all=False, equivalent_api=False):
    """Texte Slack (mrkdwn). ``links`` : {finding_id+type: url de PR} ; ``total_spent`` : dépense observée.
    ``equivalent_api`` : facturation par abonnement, les dollars sont une valeur équivalente API.
    Par défaut, seules les propositions prouvées apparaissent (un décideur n'a rien à faire des autres) ;
    ``show_all`` (démo) les montre toutes. Le détail complet est dans la page développeur."""
    links = links or {}
    ok = [p for p in proposals if p["verdict"] == "pass"]
    saved = [p["cout_usd"] for p in ok if p.get("cout_usd") and p["cout_usd"].get("apres") is not None]
    before = sum(c["avant"] for c in saved)
    after = sum(c["apres"] for c in saved)
    precisions = [p["mesures"]["precision"]["valeur"] for p in ok
                  if p["mesures"].get("precision", {}).get("statut") == "mesuré"
                  and p["mesures"]["precision"]["valeur"] is not None]
    head = [f"*Deadweight : {len(ok)} optimisation{'s' if len(ok) > 1 else ''} prouvée{'s' if len(ok) > 1 else ''} "
            f"sur {len(proposals)} testée{'s' if len(proposals) > 1 else ''}*"]
    if ok:
        if precisions:
            head.append(f"• Précision par rapport aux anciennes réponses : *{min(precisions):g} % minimum* (mesuré)")
        if saved and before:
            scope = f" sur les étapes concernées ; {(before - after) / total_spent * 100:.0f} % {TOTAL[equivalent_api]}" \
                if total_spent else ""
            label = "Valeur consommée (équiv. API)" if equivalent_api else "Coût"
            head.append(f"• {label} : *{(after - before) / before * 100:+.0f} %*{scope} (mesuré, "
                        f"{before:.4g} $ → {after:.4g} $ sur la période observée)")
            if equivalent_api:
                head.append("• Abonnement : la facture reste le prix du forfait ; le gain, tâche par tâche, "
                            "est une marge sur les limites d'usage, pas une économie en argent.")
        head.append("• Chaque gain s'active en acceptant sa micro-PR, et s'annule en la retirant.")
    shown = proposals if show_all else ok
    body = [_line(p, links.get(p["finding_id"] + p["type"]), total_spent, equivalent_api) for p in shown]
    hidden = len(proposals) - len(shown)
    if hidden:
        body.append(f"_{hidden} autre{'s' if hidden > 1 else ''} piste{'s' if hidden > 1 else ''} testée"
                    f"{'s' if hidden > 1 else ''} sans preuve suffisante : détail dans la page développeur._")
    foot = "_Mesuré = rejeu des mêmes entrées sur votre historique. ~ = estimation, jamais additionnée._"
    return "\n".join(head + [""] + body + ["", foot])
