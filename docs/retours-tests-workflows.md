# Retours de tests sur des workflows réels

Ce document liste ce qu'on a rencontré en faisant passer de vrais workflows par
Deadweight le 26/09, et comment le résoudre. État vérifié sur `main` au commit
`11d0ed0`. À compléter à chaque nouveau test.

## Ce qui a été testé

| Test | Trafic | Ce qu'il vérifie |
| --- | --- | --- |
| SDK OpenAI officiel → passerelle → vraie API OpenAI | appel simple + streaming, `gpt-4o-mini` | relais identique, streaming, clé jamais capturée (D1.1) |
| **Récap Gmail** ([repo workflows](https://github.com/thibaudgregori/Workflow-test-hackathon-agentique-25-09-2026), `workflow 2 - Recap Gmail`) | **51 appels réels** `gpt-4o-mini` : 47 tris de mails (un mot parmi 5) + 4 appels d'un agent de récap avec outil `read_email` | capture (D1.2), traces sans en-tête (D1.4), règles, rapport (D4.1), rejeu (D3.2) |
| Jeu de données D0.3 | 1 332 événements générés | les six règles, cas positifs et négatifs |

Résultat global sur le récap Gmail : la chaîne complète tourne sur du vrai trafic.
R1 « une IA qui répond toujours la même chose » est détectée sur le tri (47 appels,
5 réponses : info 16, newsletter 14, urgent 9, a_traiter 6, spam 2). L'agent de
récap n'est pas signalé, à raison. Ses appels sont regroupés en 2 traces sans aucun
en-tête. Coût réel des 51 appels : 0,0049 $.

## Problèmes ouverts

| # | Problème | Gravité | Où |
| --- | --- | --- | --- |
| 1 | Le rejeu affiche encore une projection mensuelle absurde | haute | `proof/replay.py` |
| 2 | R1 conseille des « règles fixes » que le rejeu refuse ensuite | haute | `report/audit.py`, `proof/` |
| 3 | Le rejeu ne peut presque jamais conclure sous ~90 appels | moyenne | `proof/replay.py`, `rules/low_entropy.py` |
| 4 | Le conseil « laissez tourner une heure » est faux pour un workflow par lots | moyenne | `report/audit.py` |
| 5 | Choix de R5 à valider en équipe | basse | `rules/unbounded_loop.py` |
| 6 | Heuristique de traces jamais confrontée à un historique réécrit | basse | `gateway/traces.py` |

### 1. Le rejeu affiche une projection mensuelle absurde

**Constat.** `python -m proof.replay` sur le récap Gmail affiche :

    coût      98.5014 → 16.4169 USD/mois  (/6.0)

Or les 47 tris ont coûté environ 0,005 $, et le workflow tourne une fois par jour :
le vrai coût mensuel est d'environ 0,14 $. Le chiffre affiché est 700 fois trop haut.

**Cause.** La correction #52 (pas de projection sur moins d'une heure de trafic)
n'existe que dans `report/audit.py` (`_figures`). `proof/replay.py` appelle
`chiffrer()` directement (ligne ~183), qui projette toujours
`coût × 30 jours / fenêtre`. Ici la fenêtre fait 1,1 minute, soit un facteur 39 000.

**Correction.** Déplacer le garde-fou dans `report/cost.py`, pour que `chiffrer()`
ne renvoie jamais de projection sur moins d'une heure, mais un `cout_observe_usd`.
Tous les appelants (rapport, rejeu, mode miroir) en profitent, et on supprime la
copie dans `audit.py`. À tester avec une fenêtre de 1 minute : aucune projection,
coût observé présent.

### 2. R1 conseille des règles fixes que le rejeu refuse

**Constat.** Le rapport dit, pour le tri de mails : « Remplacer par quelques règles
fixes, avec l'IA en secours ». Le rejeu du même constat répond :

    accord    20.0% sur les 5 entrées remplacées (5 par règles, 0 par secours)
    VERDICT   REJECT : on ne propose pas ce remplacement (seuil 95%)

Le refus est légitime : trier des mails par *urgence* demande de comprendre le
texte, et des mots-clés n'y suffisent pas. **Une entropie basse prouve qu'on classe,
pas que des mots-clés suffisent à classer.**

**Cause.** Le rapport ne lit pas les preuves du rejeu. Chaque constat R1 porte la
même action, qu'il soit remplaçable ou non. La mention « pas encore vérifié par
rejeu » est présente mais discrète face à une recommandation affirmative.

**Correction.**
- Brancher les preuves dans le rapport : `report.audit --proofs out/proofs/` lit
  les `proof-*.json` et affiche PASS (accord, économie mesurée) ou REJECT (raison).
- Sans preuve, formuler R1 comme une piste : « Candidat au remplacement par des
  règles, à vérifier par rejeu ».
- Sur REJECT, proposer l'alternative mesurable : un modèle plus petit sur ces
  appels (R2), ou réduire le texte envoyé (le tri envoie jusqu'à 1 500 caractères
  par mail pour renvoyer un mot).

### 3. Le rejeu ne peut presque jamais conclure sous ~90 appels

**Constat.** Sur 47 tris, 41 servent d'exemples d'extraction et sont exclus du
rejeu. Il en reste 6, pour un minimum de 30 (`MIN_REPLAY`). Le rejeu refuse donc
de conclure, quelle que soit la qualité des règles.

**Cause.** R1 garde jusqu'à 12 exemples par sortie (`MAX_SAMPLES_PER_OUTPUT`),
soit jusqu'à 60 exemples pour 5 catégories. Il faut donc environ 60 + 30 = 90
appels d'un même gabarit avant qu'une preuve soit possible. Exclure les exemples
est juste (données indépendantes), mais le coût en volume n'est dit nulle part.

**Correction.**
- Le dire : dans le rapport, pour un constat R1 sous le volume nécessaire,
  « il faut environ N appels de plus pour pouvoir le prouver ».
- Ou validation croisée : extraire sur une moitié, rejouer sur l'autre, puis
  inverser. Tout l'échantillon sert au rejeu, sans réutiliser un exemple pour se
  juger lui-même.

### 4. « Laissez tourner la passerelle au moins une heure » est faux pour un workflow par lots

**Constat.** Le récap Gmail tourne une fois par jour et fait ses 51 appels en
1 minute. Le rapport dit « laissez tourner la passerelle au moins une heure ».
Laisser tourner la passerelle ne change rien : la fenêtre est mesurée entre le
premier et le dernier **appel**, pas pendant que la passerelle est allumée. Une
seule exécution donnera toujours 1 minute.

Vérifié : avec deux exécutions du même tri espacées de 24 h, la projection
devient réaliste, 0,139 $/mois.

**Correction.**
- Message : « moins d'une heure entre le premier et le dernier appel observé :
  laissez passer au moins deux exécutions de votre workflow, ou une heure de
  trafic continu ».
- Mieux : enregistrer dans la base les heures de démarrage et d'arrêt de la
  passerelle, et projeter sur la période d'observation réelle. 51 appels observés
  pendant 24 h de fonctionnement, c'est 51 appels par jour.

### 5. Choix de R5 à valider en équipe

Deux comportements assumés dans `rules/unbounded_loop.py`, à confirmer :
- un agent qui interroge 8 fois l'état d'un même job est **signalé** comme boucle.
  Il paie un appel de modèle par interrogation pour une attente qu'un minuteur
  ferait. Discutable : on peut préférer un constat à part « attente active » ;
- un identifiant **métier** qui ressemble à un jeton aléatoire (hexadécimal de 16
  caractères ou plus) est ignoré dans la comparaison. Un lot de commandes à
  identifiants hexadécimaux serait pris pour une boucle.

### 6. Heuristique de traces jamais confrontée à un historique réécrit

Sur le récap Gmail, D1.4 regroupe correctement l'agent (2 traces, 0 faux positif).
Mais aucun workflow testé ne **résume ou tronque** son historique d'une façon qui
modifie les anciens messages (LangChain `ConversationSummaryMemory`, par exemple).
Dans ce cas, la réponse précédente n'apparaît plus telle quelle et la trace est
coupée, ce qui fait rater R3, R5 et R6. Prochain workflow de test à écrire : un
chat avec mémoire résumée.

## Problèmes corrigés

Gardés pour la traçabilité : chacun a été vu en testant.

| Problème | Correction |
| --- | --- |
| OpenAI recopie la clé dans son erreur 401 (`Incorrect API key provided: sk-…`), qui partait dans l'événement | clé masquée avant capture, D1.1 (#24) |
| Un événement malformé tuait le thread d'écriture SQLite sans bruit : plus rien n'était capturé | chaque événement protégé seul (#42) |
| Rapport de démo à 315 220 $/mois (projection d'une fenêtre de 0,3 s) | pas de projection sous une heure dans le rapport (#52) ; reste le rejeu (problème 1) |
| Aucun coût pour les modèles Claude (`claude-sonnet-4-5` contre `claude-sonnet-4.5` au catalogue) et pour les appels avec cache | noms des API reconnus, prix du cache (#56) |
| Streaming sans `include_usage` : tokens inconnus, coût vide | la passerelle demande l'usage et le retire du flux rendu (#57) |
| R5 : pagination avec URL longue prise pour une boucle ; vraie boucle cachée par un `request_id` unique | comparaison argument par argument, ids techniques ignorés (#36) |
| Robot roadmap bloqué par la protection de `main` | écrit dans une issue au lieu de pousser sur `main` (#45) |

## Pièges pour qui teste

- **La passerelle doit tourner.** Sinon l'application échoue avec `Connection
  refused` : c'est le prix du mode proxy. Port par défaut **8080** (les premiers
  essais utilisaient 8787).
- **Clé collée deux fois.** Rien ne s'affiche quand on colle un secret : on colle
  deux fois et OpenAI renvoie un 401 avec une clé masquée de plus de 700
  caractères. Une clé `sk-proj-…` fait 164 caractères : afficher sa longueur
  avant de l'utiliser.
- **Ctrl+C ne coupe pas une passerelle lancée en arrière-plan dans un script**
  (bash ignore SIGINT pour les tâches de fond). Utiliser `kill -TERM` : la
  passerelle vide sa file et s'arrête proprement.
- **Une seule exécution ne suffit pas pour le coût** (problème 4) : prévoir deux
  passages du workflow.
- **Le trafic capturé contient les données du client.** Avec le récap Gmail :
  expéditeurs, objets et textes des mails sont dans `out/events.db`, et dans
  l'export JSONL. Ne jamais les commiter ni les partager.
- **Gmail** : l'accès IMAP passe par un mot de passe d'application (validation en
  deux étapes obligatoire). Google envoie alors des « Security alert » : c'est
  attendu, à vérifier quand même.
