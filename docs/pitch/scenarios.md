# Scénarios de pitch — deux présentations, deux users

Début de scénario, **2 minutes chacun** (limite de la vidéo X-IA). Contexte complet et règles : `brief-pitch-deck.md`.
Les chiffres viennent du repo, avec leur statut ; ne pas en ajouter.

---

## Pitch 1 — Pour le décideur

**Personnage** : Claire, directrice technique d'une scale-up de 80 personnes. Sa facture d'IA a doublé en six mois.
Elle a des agents partout (support, tri des mails, génération de contenu), et personne ne sait lesquels servent.

| Temps | Ce qu'on voit | Ce qu'on dit |
|---|---|---|
| 0:00–0:15 | Une facture OpenAI qui monte | « Claire paie ses agents IA au prix du raisonnement. La question que personne ne lui pose : est-ce que ça avait besoin d'être un agent ? » |
| 0:15–0:35 | Un mail « Gagnez un iPhone » → gpt-4o → « spam » | « Son tri de mails envoie chaque message au modèle le plus cher… pour répondre spam, facture ou support. Un simple aiguillage, facturé comme de la réflexion. » |
| 0:35–0:55 | Une ligne de configuration qui change | « Avec Deadweight, elle change une seule ligne. Rien ne casse, ses données ne sortent pas de chez elle. Deadweight regarde passer le trafic et lance vingt vérifications. » |
| 0:55–1:20 | L'agent auditeur au travail, puis deux barres « promis ×45 / mesuré ×1,5 » | « Notre agent auditeur enquête, et surtout il **prouve** : il rejoue les vrais appels passés avec la modification. Passer à un modèle plus petit semblait 45 fois moins cher. Mesuré sur ses vraies requêtes : 1,5 fois seulement. Sans preuve, on lui aurait vendu un faux gain. » |
| 1:20–1:40 | Le message Slack, un bouton « accepter » | « Ce qu'elle reçoit : uniquement les gains prouvés. Tri des mails : −72 % de coût, 100 % de précision *(jeu de test)*. Un clic pour accepter la modification. » |
| 1:40–2:00 | Logo, équipe | « Deadweight : on ne vous dit pas quoi couper, on vous le prouve. Construit ce week-end par quatre personnes et leurs agents. » |

**Message à retenir** : moins cher, **prouvé**, sans risque, sans que les données quittent l'entreprise.

---

## Pitch 2 — Pour le développeur

**Personnage** : Karim, développeur qui maintient les workflows IA de son équipe (n8n, un agent en Python, Claude Code
au quotidien). Sa direction lui demande de réduire les coûts. Il n'a pas le temps de tester dix modèles à la main.

| Temps | Ce qu'on voit | Ce qu'on dit |
|---|---|---|
| 0:00–0:15 | Un ticket « réduire la facture IA de 30 % » | « Karim doit réduire les coûts IA. Sans rien casser. Et sans une semaine pour évaluer des modèles. » |
| 0:15–0:35 | Le rapport : « 72 % du coût = relire le contexte » | « Sur les agents de code, on a mesuré que 72 % du coût, c'est relire le contexte, pas le travail lui-même. Ce genre de chose ne se voit pas dans une facture. » |
| 0:35–0:55 | Terminal : `make dev`, puis les connecteurs | « Deadweight se branche sur ce qu'il utilise déjà : une ligne `base_url`, ou l'import de l'historique n8n, des traces OpenTelemetry, des journaux Claude Code et Codex. Tout tourne en local, les clés ne sont jamais stockées. » |
| 0:55–1:20 | Le verdict du rejeu, puis celui du banc | « Pour chaque piste, Deadweight prouve sur l'historique réel. Le rejeu : on rejoue les appels passés avec la modification, 95 % d'accord minimum, sinon c'est refusé, et un refus est un résultat. Le banc : on teste un modèle plus petit, local ou européen, sur les vraies entrées. Chaque chiffre dit s'il est mesuré, estimé ou non testé. » |
| 1:20–1:40 | Une micro-PR sur GitHub | « Ce qu'il reçoit : une petite PR par amélioration, testée, à relire. Et une page développeur qui montre tout, y compris ce qui a échoué et pourquoi. » |
| 1:40–2:00 | Logo, équipe, repo | « Deadweight : la preuve avant la modification, livrée en PR. Construit ce week-end, 20 vérifications, plus de 450 tests. » |

**Message à retenir** : ça se branche en 10 minutes, ça prouve sur **son** historique, ça livre une PR qu'il relit.

---

## Moments de démo communs

1. **La preuve qui dit non** : le banc qui ramène « ×45 » à « ×1,5 ». C'est le moment le plus fort des deux pitchs.
2. **L'honnêteté** : sur l'exemple officiel OpenAI de triage, Deadweight ne trouve rien à optimiser, et c'est juste.
3. **L'agent** : il enquête, choisit quoi prouver, et ne peut pas inventer un chiffre (garde-fou).

## À compléter

- Captures réelles : message Slack, rapport, page développeur, une micro-PR, la sortie du banc (`docs/banc/`).
- Choisir le workflow de la démo en direct (voir `docs/etat-du-projet.md`).
- Faire relire les deux scénarios par quelqu'un hors équipe : compris sans explication ?
