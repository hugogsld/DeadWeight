"""Envoi du message Slack par webhook entrant (``SLACK_WEBHOOK_URL``).

Le texte est celui de ``slack.md`` (optimize) ; chaque micro-PR ouverte devient un bouton lien vers sa page
GitHub. Slack ne fusionne rien et aucun serveur n'est exposé : la décision se prend sur GitHub.
"""
import json
import urllib.request

SECTION_MAX = 3000  # limite Slack d'un bloc section
BUTTONS_MAX = 25    # limite Slack d'un bloc actions


def payload(text, prs=()):
    """Corps du webhook : le message mrkdwn, puis un bouton « Voir la PR » par micro-PR ouverte."""
    body = text if len(text) <= SECTION_MAX else text[:SECTION_MAX - 1] + "…"
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": body}}]
    buttons = [{"type": "button", "url": pr["url"], "action_id": f"pr-{i}",
                "text": {"type": "plain_text", "text": f"Voir la PR : {pr['app_id']}"[:75]}}
               for i, pr in enumerate(prs[:BUTTONS_MAX])]
    if buttons:
        blocks.append({"type": "actions", "elements": buttons})
    return {"text": text, "blocks": blocks}


def send(url, data, opener=urllib.request.urlopen, timeout=10):
    """POST JSON vers le webhook ; lève une erreur lisible si Slack refuse."""
    request = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with opener(request, timeout=timeout) as response:
        answer = response.read().decode("utf-8", "replace").strip()
        if response.status != 200 or answer != "ok":
            raise RuntimeError(f"Slack a refusé le message ({response.status} : {answer or 'réponse vide'})")
