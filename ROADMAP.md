# Deadweight — roadmap weekend 26-27 septembre

4 personnes, 15 h chacune, 60 h au total. Découpé en livrables de 2 à 4 h, chacun prenable indépendamment.
Source : document de Natan du 25/09. Ce fichier est la version vivante : **le tableau ci-dessous se met à jour tout seul**.

## Avancement

Comment apparaître dans le tableau : créer une issue dont le titre commence par l'identifiant
(`D1.1 — Proxy OpenAI`), s'assigner, et ouvrir la PR avec le même début de titre et `Closes #<issue>`.
Fusionner la PR passe le livrable en « Fait » et débloque ceux qui en dépendent.

<!-- STATUT:DEBUT -->
**9 / 17 livrables du plan de base faits** (29 h sur 57 h). Mis à jour automatiquement le 26/09 à 12:23.

| Id | Livrable | Durée | Dépend de | Statut | Qui | Issue / PR |
|---|---|---|---|---|---|---|
| D0.1 | Schéma d'événement et fixtures | 3 h | — | **Fait** | Natanlsr3 | #1 · PR #2 |
| D0.2 | Repo, CI, make dev, enregistrement | 3 h | — | **En relecture** | alexandre-zenou, claude | #22 · PR #21 |
| D0.3 | Jeu de données réaliste | 4 h | D0.1 | **Fait** | Natanlsr3 | #3 · PR #5 |
| D1.1 | Proxy passe-plat OpenAI, streaming | 5 h | D0.2 | **Fait** | claude, thibaudgregori | #23 · PR #24 |
| D1.2 | Capture et persistance | 3 h | D0.1, D1.1 | **En relecture** | claude, thibaudgregori | #25 · PR #27 |
| D1.3 | Anthropic et Gemini | 4 h | D1.1 | **En cours** | alexandre-zenou, claude | #28 |
| D1.4 | Regroupement par trace | 3 h | D1.2 | **En cours** | claude, thibaudgregori | #29 |
| D2.1 | R1 entropie | 2 h | D0.3 | **Fait** | Natanlsr3, claude | #7 · PR #9 |
| D2.2 | R2 modèle surdimensionné | 3 h | D0.3 | **Fait** | Natanlsr3, claude | #17 · PR #18 |
| D2.3 | R3 contexte brut + R4 absence de cache | 3 h | D0.3 | **Fait** | Natanlsr3, codex | #8 · PR #15 |
| D2.4 | R5 boucle + R6 agent inutile | 5 h | D0.3, D1.4 | Bloqué (attend D1.4) | — | — |
| D2.5 | Chiffrage coût et latence | 3 h | D0.1 | **Fait** | Natanlsr3 | #4 · PR #6 |
| D3.1 | Extraction des règles | 3 h | D2.1 | **Fait** | Natanlsr3, codex | #16 · PR #20 |
| D3.2 | Rejeu et seuil 0,95 | 4 h | D3.1 | **En cours** | claude, hugogsld | #26 |
| D3.3 | Court-circuit *(hors plan)* | 4 h | D3.2 | Bloqué (attend D3.2) | — | — |
| D4.1 | Rapport d'audit | 3 h | D2.5 | **Fait** | Natanlsr3, claude | #12 · PR #13 |
| D4.2 | Installation dix minutes | 4 h | D1.1, D4.1 | Prenable | — | — |
| D4.3 | Mode miroir *(hors plan)* | 3 h | D1.2 | Bloqué (attend D1.2) | — | — |
| D4.4 | Test par un tiers | 2 h | D4.2 | Bloqué (attend D4.2) | — | — |
<!-- STATUT:FIN -->

Jalons : **samedi 18 h** — « la passerelle voit et les règles disent ». **Dimanche 15 h** — gel, plus de nouvelle fonctionnalité ; D4.4 et corrections jusqu'à 18 h.

## Où on en est au départ

On a un prototype qui marche, mais qui lit l'API n8n. Le weekend sert à le découpler : la détection passe à la passerelle, le reste suit. Ce n'est pas une réécriture : la logique métier (entropie, chiffrage, extraction de règles, rejeu) se transpose. Ce qui saute, c'est la source de données.

| Brique du prototype | Ce qu'elle fait | Décision |
|---|---|---|
| `detector/scan.py` | lit workflows + historique n8n, calcule l'entropie | on garde le calcul, on jette la lecture n8n |
| `collector/pricing.py` | catalogue OpenRouter → coût réel par modèle | on garde tel quel |
| `patcher/patch.py` | reconstruit le graphe n8n | mis de côté — devient l'option « patch plateforme » |
| prompt d'extraction des règles | sort les règles de classification d'un échantillon | on garde, on le porte |
| `prover/prove.py` | rejeu sur historique, latences réelles, seuil d'accord | on garde la logique, nouvelle source de données |
| `run.sh`, `daemon.sh` | enchaînement et boucle de réveil | on jette — remplacé par un service |

## L'objectif du weekend

**Une passerelle qu'un tiers installe seul en dix minutes et qui rend un rapport d'audit sur les six règles.** C'est le prérequis de la validation auprès de cinq entreprises.

Critère de réussite, vérifiable dimanche 18 h. Quelqu'un qui n'a pas écrit une ligne du code :

1. change une variable `base_url` dans son application ;
2. laisse tourner son trafic normal ;
3. lance une commande et obtient un rapport d'une page — constats chiffrés, coût mensuel, latence, volume ;
4. n'a jamais eu à nous appeler.

Si les quatre points passent, le weekend est réussi, même si des règles sont incomplètes. Si le point 1 ou le point 4 casse, tout le reste ne sert à rien.

**Hors objectif** : le court-circuit automatique depuis la passerelle. Livrer l'audit prime.

## Règles du repo

- `main` est protégé : tout passe par une PR.
- Un livrable = une branche = une PR. Nommage `feat/D1.2-capture-persistance`.
- `git pull --rebase origin main` au début de chaque session et avant chaque PR.
- Relecture par n'importe qui, en moins de trente minutes. Les PR restent petites.
- Aucun secret dans le repo. Les clés vivent dans `.env.local`. Une clé qui fuit est révoquée immédiatement.
- Chaque PR qui ajoute une commande met à jour le README.
- Agents de code (Claude Code, Codex) : voir `AGENTS.md`.

**Dans le produit, on ne stocke jamais la clé du client.** La passerelle relaie l'en-tête d'autorisation tel quel, sans le persister ni le journaliser. La capture contient les prompts du client : la base reste chez lui.

**Limites de débit** : le rejeu est la seule chose capable de marteler une API. Plafond dur et étalement dans le temps, posés dans D3.2 avant le premier lancement.

## Les livrables

Chaque livrable a un critère de fin binaire. Difficulté : ★ mécanique · ★★ code standard · ★★★ il faut réfléchir · ★★★★ piège technique connu · ★★★★★ on ne sait pas encore comment faire.

### Lot 0 — Socle (samedi matin)

- **D0.1 — Schéma d'événement et fixtures** · 3 h · ★★★. Fin : schéma fusionné et 50 événements d'exemple couvrant les six règles.
- **D0.2 — Repo, structure, CI et `make dev`** · 3 h · ★★. Fin : sur une machine vierge, `git clone` puis `make dev`, ça tourne. CI verte.
- **D0.3 — Jeu de données réaliste** · 4 h · ★★★. Fin : chaque règle a au moins un cas positif et un cas négatif ; le jeu est versionné.

### Lot 1 — Passerelle

- **D1.1 — Proxy passe-plat OpenAI, streaming compris** · 5 h · ★★★★. Fin : une application existante fonctionne à l'identique, streaming inclus ; latence ajoutée < 30 ms au p95 ; l'en-tête d'autorisation est relayé et jamais persisté. Remplir `upstream` avec l'hôte amont.
- **D1.2 — Capture et persistance** (SQLite, écriture asynchrone) · 3 h · ★★. Fin : 1 000 appels relayés donnent 1 000 événements relisibles, latence inchangée.
- **D1.3 — Anthropic et Gemini** · 4 h · ★★★. Fin : trois fournisseurs relayés, même schéma, fixtures enregistrées.
- **D1.4 — Regroupement par trace** · 3 h · ★★★. Fin : une boucle de huit appels ressort comme une trace de huit, avec et sans en-tête. **Conditionne les règles 5 et 6 : à ne pas repousser à dimanche.**

### Lot 2 — Les six règles

- **D2.1 — R1 low_entropy_output** · 2 h · ★★. Fin : mêmes verdicts que le prototype.
- **D2.2 — R2 oversized_model** · 3 h · ★★★. Fin : candidats avec économie estimée, marqués « non prouvé ».
- **D2.3 — R3 raw_context + R4 no_cache** · 3 h · ★★. Fin : détecte les cas du jeu, zéro faux positif.
- **D2.4 — R5 unbounded_loop + R6 agent_where_chain** · 5 h · ★★★★★. Fin : détecte les cas du jeu, seuil écrit avec son raisonnement. Prévoir de jeter la première tentative.
- **D2.5 — Chiffrage coût et latence** · 3 h · ★★. Fin : quatre chiffres mesurés par constat, jamais de valeur par défaut présentée comme une mesure.

### Lot 3 — Preuve et application

- **D3.1 — Extraction des règles de classification** · 3 h · ★★★. Le modèle extrait les règles, le code construit l'aiguillage. Fin : sur un constat du jeu, sort des règles qui tournent.
- **D3.2 — Rejeu et seuil d'accord à 0,95** · 4 h · ★★★★. Fin : rend un taux d'accord, refuse sous le seuil, et le refus s'affiche comme un résultat légitime.
- **D3.3 — Court-circuit depuis la passerelle** · 4 h · ★★★★ · *hors plan de base*. Ne s'attaque que si le lot 4 est bouclé.

### Lot 4 — Livraison

- **D4.1 — Rapport d'audit d'une page** · 3 h · ★★. Fin : relu par quelqu'un hors équipe, compris sans explication orale.
- **D4.2 — Installation en dix minutes et README** · 4 h · ★★★. Fin : chronométré sur une machine vierge, sous dix minutes, sans question.
- **D4.3 — Mode miroir** · 3 h · ★★★ · *hors plan de base*.
- **D4.4 — Test de bout en bout par un tiers** · 2 h · ★. Interdiction d'aider oralement. **Dimanche après-midi, pas dimanche 18 h.**

## Répartition proposée

| | Samedi (≈ 8 h) | Dimanche (≈ 7 h) |
|---|---|---|
| P1 | D0.1, D1.1 | D1.3, renfort intégration |
| P2 | D0.2, D1.2 | D1.4, D3.1 |
| P3 | D0.3, D2.1 | D2.4, relectures |
| P4 | D2.2, D2.3 | D2.5, D4.1 |

D4.2 et D4.4 ne sont assignés à personne mais ne se coupent jamais : pris dimanche par celui qui finit en avance, sinon D2.4 saute pour les libérer. Rien n'oblige à respecter ces colonnes : un livrable dont les dépendances sont satisfaites se prend, sans demander.

## Ordre de coupe si on déborde

1. D4.3 et D3.3 (déjà hors plan).
2. D3.1 et D3.2 — le prototype les fait en version n8n.
3. D2.4 — un rapport sur quatre règles reste un rapport.
4. D1.3 — un audit OpenAI seul reste vendable.

**On ne coupe jamais D4.1, D4.2 et D4.4.**

## Risques

| Risque | Signal d'alerte | Parade |
|---|---|---|
| Le streaming casse la capture | D1.1 marche en simple, plus rien en streaming | à traiter dans D1.1, pas après |
| Les règles marchent sur fixtures, pas sur vrai trafic | écart découvert au jalon 1 | c'est à ça que sert le jalon 1 |
| Le rapport est illisible pour un extérieur | on le trouve clair entre nous | D4.4 par quelqu'un hors équipe |

**Règle des trente minutes** : coincé plus de trente minutes sur la même erreur, on le dit à voix haute.

**Question ouverte** : quels fournisseurs les futurs clients utilisent réellement (Bedrock, Vertex ?). À vérifier dès les premiers contacts.
