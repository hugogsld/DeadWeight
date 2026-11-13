"""Le message Slack : les gains prouvés, activables en acceptant des micro-PR.

Les chiffres d'en-tête ne viennent que des propositions validées (verdict « pass ») et de mesures au
statut « mesuré » ; une estimation apparaît avec « ~ » et n'entre jamais dans un total. Le coût total est
calculé en dollars sur la période observée, jamais en additionnant des pourcentages de périmètres différents.
Sur abonnement (Claude Code Max, ChatGPT Plus…), le forfait ne baisse pas : le dollar gagné est une valeur
équivalente API et une marge sur les limites d'usage, jamais présenté comme une économie sur la facture.
"""


from report.conseils import conseil_logs, conseil_proposition

LEVELS = {"precision"}  # un niveau, pas une variation : jamais de signe
TOTAL = {False: "de la dépense totale", True: "de la valeur consommée (équiv. API)"}


def _fmt(v, unit="", level=False):
    if v is None:
        return "—"
    sign = "+" if isinstance(v, (int, float)) and v > 0 and unit == "%" and not level else ""
    return f"{sign}{v:g}{' ' + unit if unit and unit != '%' else unit}"


def _mesure_text(p, key, v):
    """Comme le tableau du testeur (scripts.tester_ui.latency_cell) : la latence médiane à -100 %
    (plus aucun appel au modèle) s'affiche en ms réelles, pas en pourcentage qui ressemble à un bug."""
    if key == "latence_mediane" and v["valeur"] == -100.0:
        ms = p.get("latence_ms") or {}
        if ms.get("avant") is not None and ms.get("apres") is not None:
            return f"{ms['avant']:.0f} ms → {ms['apres']:.0f} ms"
    prefix = "~" if v["statut"] != "mesuré" else ""
    return f"{prefix}{_fmt(v['valeur'], v['unite'], key in LEVELS)}"


LEGEND = "_Légende : ✅ gain prouvé par rejeu · ◻️ piste non testée · ⛔ piste rejetée (précision insuffisante)_"


def quoi_changer(p):
    """Une ligne concrète (paramètre, valeur, où) pour les gains qui ne produisent pas de diff, sinon None."""
    kind, model = p.get("type"), str(p.get("model") or "")
    if kind == "plafond" and p.get("plafond"):
        return (f"Quoi changer : dans l'appel au modèle, `max_tokens={p['plafond']}` "
                f"(`max_completion_tokens={p['plafond']}` pour un modèle de raisonnement OpenAI).")
    if kind == "raisonnement":
        effort = (p.get("preuve") or {}).get("effort") or "low"
        return (f"Quoi changer : dans l'appel au modèle, `reasoning_effort=\"{effort}\"` "
                f"(API Responses : `reasoning={{\"effort\": \"{effort}\"}}`).")
    if kind == "cache_prompt":
        if model.startswith("claude"):
            return ("Quoi changer : mettre instructions et outils en tête du prompt, et ajouter "
                    "`cache_control={\"type\": \"ephemeral\"}` sur le dernier bloc fixe du `system`.")
        return ("Quoi changer : mettre la partie fixe (instructions, outils) en tête du prompt, la partie variable "
                "à la fin ; le préfixe identique de 1024 jetons ou plus est mis en cache automatiquement.")
    return None


def _line(p, link, total_spent=None, equivalent_api=False, kind=None):
    m = p["mesures"]
    icon = {"pass": "✅", "reject": "⛔", "non_teste": "◻️"}.get(p["verdict"], "•")
    parts = []
    # ordre imposé : contexte envoyé, coût, latence médiane, précision (D2.6, Problème 2) ; les deux
    # figures restantes (latence p95, jetons de sortie) suivent, en détail secondaire.
    for key, label in (("jetons_envoyes", "contexte envoyé"), ("cout", "coût"),
                       ("latence_mediane", "latence médiane"), ("precision", "précision"),
                       ("latence_p95", "latence p95"), ("jetons_sortie", "jetons de sortie")):
        v = m.get(key)
        if v and v["valeur"] is not None:
            parts.append(f"{label} {_mesure_text(p, key, v)}")
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
    how = (conseil_proposition(p, kind) or quoi_changer(p)) if p["verdict"] == "pass" else None
    if how and kind == "logs" and not conseil_proposition(p, kind) and p["type"] in ("plafond", "cache_prompt"):
        how = None  # réglage SDK sans équivalent dans Claude Code : mieux vaut ne rien dire que mal conseiller
    return f"{icon} *{p['app_id']}* — {p['changement']}\n      {detail}{share}{why}{pr}" + (f"\n      {how}" if how else "")


def _sans_piste(rows, kind):
    """Constats statistiques sans piste testable : lesquels, pourquoi, et ce qui les rendrait testables."""
    out = [f"• {sum(r['nb'] for r in rows)} constat(s) statistique(s), mais aucune piste testable par rejeu :"]
    for r in rows:
        out.append(f"   - {r['titre']} ({r['nb']}) : {r['pourquoi']}. Pour le tester : {r['pour_tester']}.")
        how = conseil_logs(r["regle"]) if kind == "logs" else None
        if how:
            out.append(f"     {how}")
    return out


def message(proposals, links=None, total_spent=None, show_all=False, equivalent_api=False, with_diffs=False,
            sans_piste=None, kind=None):
    """Texte Slack (mrkdwn). ``links`` : {finding_id+type: url de PR} ; ``total_spent`` : dépense observée.
    ``equivalent_api`` : facturation par abonnement, les dollars sont une valeur équivalente API.
    Par défaut, seules les propositions prouvées apparaissent (un décideur n'a rien à faire des autres) ;
    ``show_all`` (démo) les montre seulement s'il n'y a aucun gain prouvé : sinon une ligne les compte.
    ``with_diffs`` : les diffs de micro-PR ont été produits (``--repo``). Le détail est dans la page développeur."""
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
        if links:
            head.append("• Chaque gain s'active en acceptant sa micro-PR, et s'annule en la retirant.")
        elif with_diffs:
            head.append("• Le diff et le texte de chaque micro-PR sont dans le dossier de sortie (fichiers .diff et .pr.md).")
        else:
            head.append("• Aucun diff produit : relancez avec `--repo <dossier>` pour l'obtenir "
                        "(le dépôt n'est pas modifié).")
    if sans_piste:
        head.extend(_sans_piste(sans_piste, kind))
    elif not proposals:
        head.append("• Aucun constat sur ces données, donc rien à tester : la page audit.html explique pourquoi "
                    "(section « Pourquoi aucun constat »).")
    shown = ok if ok or not show_all else proposals
    body = [_line(p, links.get(p["finding_id"] + p["type"]), total_spent, equivalent_api, kind) for p in shown]
    hidden = len(proposals) - len(shown)
    if hidden:
        untested = sum(p["verdict"] == "non_teste" for p in proposals if p not in shown)
        body.append(f"_{hidden} autre{'s' if hidden > 1 else ''} piste{'s' if hidden > 1 else ''} : "
                    f"{untested} non testée{'s' if untested > 1 else ''}, {hidden - untested} rejetée"
                    f"{'s' if hidden - untested > 1 else ''} ; détail dans la page développeur._")
    foot = "_Mesuré = rejeu des mêmes entrées sur votre historique. ~ = estimation, jamais additionnée._"
    return "\n".join(head[:1] + [LEGEND] + head[1:] + [""] + body + ["", foot])
