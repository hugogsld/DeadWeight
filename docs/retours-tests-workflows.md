# Retours de tests sur des workflows réels

Journal des tests de Deadweight sur de vrais workflows : ce qu'on a rencontré, et
comment on compte le résoudre. État vérifié sur `main` au commit `11d0ed0`.

Les workflows testés et leurs liens sont listés dans le README, section « Workflows de test ».

**Test réel** veut dire : le workflow a tourné, son trafic est passé par la passerelle,
et le rapport et le rejeu ont été lancés dessus. Les constats marqués « lecture du
code » n'ont pas été mesurés.

## Comment utiliser cette page

1. **Tester** : faire passer un workflow par la passerelle, puis lancer le rapport
   et le rejeu. L'ajouter au tableau « Workflows testés », avec le modèle en bas de page.
2. **Noter** chaque problème dans « Problèmes ouverts », avec un **constat chiffré**
   (commande lancée, chiffre obtenu, chiffre attendu), sa **cause** et une
   **solution envisagée**. Statut : `ouvert`.
3. **Regrouper** avant de corriger : si un problème revient sur plusieurs workflows,
   compléter sa fiche plutôt que d'en créer une nouvelle.
4. **Corriger** une fois la série de tests faite, par ordre de gravité, une PR par
   problème. Statut `en cours` avec le numéro de PR, puis déplacer la fiche dans
   « Problèmes corrigés » une fois fusionnée.

Statuts : `ouvert` → `en cours (#PR)` → `corrigé (#PR)`, ou `abandonné (raison)`.

## Workflows testés

| Test | Trafic | Ce qu'il vérifie |
| --- | --- | --- |
| SDK OpenAI officiel → passerelle → vraie API OpenAI | appel simple + streaming, `gpt-4o-mini` | relais identique, streaming, clé jamais capturée (D1.1) |
| **Récap Gmail** ([`workflow 2 - Recap Gmail`](https://github.com/thibaudgregori/Workflow-test-hackathon-agentique-25-09-2026/tree/main/workflow%202%20-%20Recap%20Gmail)), test réel | **51 appels réels** `gpt-4o-mini` : 47 tris de mails (un mot parmi 5) + 4 appels d'un agent de récap avec outil `read_email` | capture (D1.2), traces sans en-tête (D1.4), règles, rapport (D4.1), rejeu (D3.2) |
| Jeu de données D0.3 | 1 332 événements générés | les six règles, cas positifs et négatifs |
| **Miguel shorts-factory** ([`workflow 1 - Miguel short`](https://github.com/thibaudgregori/Workflow-test-hackathon-agentique-25-09-2026/tree/main/workflow%201%20-%20Miguel%20short)), lecture du code | **aucun appel capturé** : lecture du code d'orchestration et du relevé de coûts réel (316 lignes, 7 lots de production) | ce que Deadweight verrait, et ce qu'il ne peut pas voir, sur un pipeline d'agents en production |
| **OpenAI story flow** ([`workflow 3 - OpenAI story flow`](https://github.com/thibaudgregori/Workflow-test-hackathon-agentique-25-09-2026/tree/main/workflow%203%20-%20OpenAI%20story%20flow)), test réel | **77 appels réels** `gpt-4o-mini` : 30 exécutions de l'exemple officiel `deterministic.py` du SDK Agents (plan → vérification → histoire) | capture, traces (D1.4), R1, rejeu, API Responses |

Résultat global sur le récap Gmail : la chaîne complète tourne sur du vrai trafic.
R1 « une IA qui répond toujours la même chose » est détectée sur le tri (47 appels,
5 réponses : info 16, newsletter 14, urgent 9, a_traiter 6, spam 2). L'agent de
récap n'est pas signalé, à raison. Ses appels sont regroupés en 2 traces sans aucun
en-tête. Coût réel des 51 appels : 0,0049 $.

### Fiche : Miguel shorts-factory (26/09)

- **Source** : snapshot de `migueltorrezd/shorts-factory` @ `34edd0a`, dossier
  `workflow 1 - Miguel short` du repo workflows.
- **Ce qu'il fait** : transforme une vidéo filmée en trois shorts (YouTube,
  Instagram, TikTok), puis les emballe, les archive et les programme.
  Orchestration : `workflow/daily-shorts.js`, un Workflow Claude Code qui lance
  un agent Claude Opus 5.5 par tâche.
- **Trafic capturé** : aucun. Le faire tourner demande une vraie vidéo, les
  comptes Modal, ElevenLabs, Notion, Google Drive et Zernio de Miguel, et il
  **publie sur ses réseaux** : pas lancé. Test fait sur le code et sur
  `factory/runs/*/costs.jsonl`.
- **Appels de modèles** : agents Claude Opus 5.5 via Claude Code (le cœur du
  pipeline), `claude -p` (lecteurs indépendants), GPT-6 Astra via `codex exec`
  (détourage), Gemini en direct via le SDK `google-genai` (contrôle qualité,
  **en pause** depuis le 22/09). Aucun appel OpenAI direct.
- **Ce que Deadweight signalerait** (lecture du code, non mesuré) : une
  famille d'agents Opus dont le prompt dit lui-même qu'ils ne décident rien.

| Agent | Ce que dit son prompt | Remplaçable par |
| --- | --- | --- |
| `wait:` (sleeper) | « exécute `sleep 600`, puis réponds le seul mot *slept* ». Existe parce que le script n'a pas d'horloge | un minuteur dans l'orchestrateur |
| `marker:` | « tu es aussi petit qu'un agent peut l'être » : une commande, ne juge rien | l'appel direct du script |
| `watch:` | lance la même commande jusqu'à 4 fois, « ne juge rien » | une boucle dans le script |
| `probe:` | lit au plus deux fichiers et revient | une lecture de fichier |
| `costs:report` | « lance UNE commande », ne peut pas échouer | l'appel direct du script |
| `prep:launch`, `render:` | lancent un script et renvoient son résultat | l'appel direct du script |

Restent de vrais agents : `design:`, `author:` (création), `metadata:` (rédaction), la revue du détourage par Astra.

- **Coût** : le relevé de Miguel annonce **1,48 $ pour tout le lot 24**
  (« every number below was measured »), 6,25 $ sur 7 lots. **Aucune ligne
  pour les agents Claude Opus ni pour GPT-6 Astra** : seuls Modal, Gemini et
  ElevenLabs sont comptés. Le poste le plus lourd du pipeline est invisible
  dans son propre bilan.
- **Problèmes** : 7, 8, 9.

### Fiche : OpenAI story flow (26/09)

- **Source** : exemple officiel `examples/agent_patterns/deterministic.py` de
  [openai-agents-python](https://github.com/openai/openai-agents-python) @ `588826c`,
  dossier `workflow 3 - OpenAI story flow` du repo workflows.
- **Ce qu'il fait** : trois agents à la suite. Un plan d'histoire, puis un
  vérificateur qui rend `{good_quality, is_scifi}`, puis, si les deux sont vrais,
  l'histoire.
- **Trafic capturé** : 2 lots de 15 demandes (9 de science-fiction, 6 d'autres
  genres), soit **77 appels réels** `gpt-4o-mini` : 30 plans, 30 vérifications,
  17 histoires. Sans streaming, 0 erreur, 2 min de trafic par lot. Coût réel :
  environ 0,01 $ par lot.
- **Règles obtenues** :
  - après 1 lot (38 appels) : **aucun constat**. Le vérificateur ne rend que 2
    réponses sur 15 appels, mais R1 demande au moins 30 appels d'un même gabarit ;
  - après 2 lots (77 appels) : **R1 sur le vérificateur**, « 30 appels ne
    produisent que 2 réponses différentes ». Mesuré à côté : `good_quality` vaut
    `true` 30 fois sur 30, le contrôle de qualité n'a jamais rien arrêté ;
  - **aucune trace** reconstituée (0 sur 77), donc R6 « toujours le même chemin »
    ne peut pas voir cette chaîne fixe.
- **Ce que montrent les données** (les 77 appels relus un par un) :
  - `good_quality` vaut `true` **30 fois sur 30** : la moitié du contrôle ne
    décide jamais rien ;
  - le vérificateur s'est **contredit** sur la même demande (« last lighthouse
    keeper on a flooded Earth » : pas SF au lot 1, SF au lot 2), ce qui a bloqué
    l'histoire la première fois ;
  - la règle « la **demande** de l'utilisateur contient *sci-fi* » reproduit
    `is_scifi` **29 fois sur 30**. Appliquée au **plan**, qui est ce que le
    vérificateur reçoit, la même règle tombe juste **14 fois sur 30**.
- **Rejeu** : `REJECT`. 24 des 30 vérifications servent d'exemples, il en reste 6
  à rejouer pour un minimum de 30. Règles extraites :
  `elysium|alex|mira|human` → science-fiction, `clara|bakery|whisker|hotel` →
  pas de science-fiction. Ce sont des noms de personnages de ce lot, pas des
  critères. Coût affiché : `20.0539 → 10.0269 USD/mois` pour un coût réel de
  0,0023 $.
- **API Responses** : une exécution avec le réglage par défaut du SDK
  (`set_default_openai_api("responses")`) a répondu normalement à l'utilisateur.
  La passerelle a relayé, et **0 événement capturé** (77 avant, 77 après).
- **Problèmes** : 1 et 3 (confirmés), 10, 11, 12, 13, 14.

### Fiche : Récap Gmail, retest sur `main` (26/09, 17 h 20)

- **Version testée** : `main` @ `7fd9045` (14 vérifications, agent auditeur, banc de
  modèles), passerelle neuve sur le port 8096, même base que le premier passage.
- **Trafic** : 2e exécution réelle du récap sur la vraie boîte (35 mails) :
  37 appels. Avec le passage de 16 h 04, **88 appels** sur **1 h 16**.
  Coût réel : 0,0084 $.
- **Rapport** : 1 constat, R1 sur le tri (82 appels, 5 réponses). Coût mensuel
  affiché : **2,53 $**. Coût réel du tri : 0,0022 $ par récap, soit **0,07 $/mois**
  à un récap par jour (problème 4).
- **Rejeu hors ligne** (`proof.replay`, sans clé) : `REJECT`, 33 entrées rejouées,
  **55 % d'accord** sur 20 remplacées. Règles surtout fondées sur l'expéditeur :
  `medium|changelog|campaign|read` → newsletter, `google|account|security|alert`
  → urgent.
- **Agent auditeur** (`scripts.audit`, `gpt-5-mini`, 6 appels, 0,0157 $) : plan
  d'action en 5 points. Son propre rejeu donne **87 % d'accord** sur 23 entrées
  remplacées, `REJECT`. Plan : observer en miroir, rejouer davantage, puis
  remplacer si le seuil est atteint (problème 16 pour ses erreurs).
- **Banc de modèles** (`bench run --candidates small`, 30 cas) :
  `openai-gpt-5-nano` score **0,0** sur 29 appels réussis, p95 16,9 s ;
  `mistral-ministral-8b` et `openrouter-mistral-small` : 30/30 en erreur (pas de
  clé), affichés `reject`. Problèmes 15 et 17.
- **Problèmes** : 4 (confirmé après plus d'une heure), 15, 16, 17.

### Fiche : Sources de workflows (27/09)

Objectif : vérifier que Deadweight se branche sur les principales sources de workflows d'entreprise.
Chaque test : une vraie application lancée en local, son trafic passé par Deadweight, puis le rapport.
Synthèse dans `docs/analyser-un-workflow.md`, « Ce qui a été vérifié pour de vrai ».

- **n8n 2.40.7** (installé en local, `npx n8n`) : workflow webhook → Basic LLM Chain → OpenAI Chat
  Model, 42 exécutions. **Passerelle** : l'identifiant OpenAI de n8n a un champ *Base URL* et un
  en-tête personnalisé → 42/42 appels captés, `app_id` = `n8n-mail-triage`. **Import de
  l'historique** (`importers.n8n check/fetch/convert`) : 42/42 exécutions, 100 % des appels LLM
  compris, jetons réels, une trace par exécution. Même rapport par les deux voies. Pour ne pas
  saisir de vraie clé dans n8n, l'amont était le faux OpenAI du projet.
- **LangChain** (`langchain-openai` 1.6.6) : `ChatOpenAI(base_url=…, default_headers=…)`, appels
  simples et streaming : 4/4 captés.
- **Claude Code** : journaux de session d'un vrai projet (5,5 Mo) → `connectors.agent_logs` :
  300 appels lus, 0 ignoré, niveaux 1 à 3. Rapport : 2 constats R12 (problème 19), 730 $/mois
  affichés pour une session sous abonnement (problème 9).
- **OpenTelemetry en direct** : application Python, exportateur officiel
  `opentelemetry-exporter-otlp-proto-http` 1.45 → `/v1/traces` : **415, 0 événement** (problème 18).
- **SDK Agents d'OpenAI** : l'API Responses n'est toujours pas capturée sur `main` (problème 11).
- Non vérifié : Claude Code et Codex en direct par la passerelle, Codex en journaux, Ollama, Make,
  Zapier, Azure OpenAI, Bedrock, Vertex (outil ou compte absent).

## Problèmes ouverts

| # | Problème | Gravité | Où | Vu sur | Statut |
| --- | --- | --- | --- | --- | --- |
| 1 | Le rejeu affiche encore une projection mensuelle absurde | haute | `proof/replay.py` | Récap Gmail, OpenAI story flow | ouvert |
| 2 | R1 conseille des « règles fixes » que le rejeu refuse ensuite | haute | `report/audit.py`, `proof/` | Récap Gmail | ouvert |
| 3 | Le rejeu ne peut presque jamais conclure sous ~90 appels | moyenne | `proof/replay.py`, `rules/low_entropy.py` | Récap Gmail, OpenAI story flow | ouvert |
| 4 | La projection mensuelle surestime les workflows par lots, même après une heure | haute | `report/audit.py`, `report/cost.py` | Récap Gmail (2 passages) | corrigé (#98) |
| 5 | Choix de R5 à valider en équipe | basse | `rules/unbounded_loop.py` | tests D2.4 | ouvert |
| 6 | Heuristique de traces jamais confrontée à un historique réécrit | basse | `gateway/traces.py` | aucun (à tester) | ouvert |
| 7 | Deadweight ne voit pas les agents lancés par Claude Code, `claude -p` ou `codex exec` | haute | installation (D4.2), `gateway/` | Miguel shorts-factory (lecture du code) | ouvert |
| 8 | Les agents qui n'exécutent qu'une seule commande échappent à toutes les règles | haute | `rules/agent_where_chain.py` | Miguel shorts-factory (lecture du code) | ouvert |
| 9 | Agents facturés à l'abonnement : le coût en dollars par token ne reflète pas ce qu'ils coûtent | moyenne | `report/cost.py`, `report/audit.py` | Miguel shorts-factory (lecture du code) | ouvert |
| 10 | Les agents qui se passent le relais (la sortie de l'un devient l'entrée de l'autre) ne sont pas regroupés en trace | haute | `gateway/traces.py` | OpenAI story flow | ouvert |
| 11 | L'API Responses d'OpenAI, celle du SDK Agents par défaut, n'est pas capturée | haute | `gateway/proxy.py`, `gateway/capture.py` | OpenAI story flow | ouvert |
| 12 | L'extraction de règles hors ligne apprend des noms propres | moyenne | `proof/extract.py` | OpenAI story flow | ouvert |
| 13 | La bonne règle se trouve en amont : l'extraction ne regarde que l'entrée de l'appel signalé | moyenne | `proof/extract.py`, `gateway/traces.py` | OpenAI story flow | ouvert |
| 14 | Sortie structurée : un champ qui ne change jamais n'est pas signalé | moyenne | `rules/low_entropy.py` | OpenAI story flow | ouvert |
| 15 | Le banc de modèles envoie les cas sans le prompt système : les candidats ne reçoivent pas la consigne | haute | `bench/testset.py` | Récap Gmail (retest) | corrigé (#82) |
| 16 | Le plan de l'agent auditeur contient des chiffres mal attribués et une recommandation incohérente | moyenne | `agent/`, `report/audit.py` | Récap Gmail (retest) | corrigé (#99) |
| 17 | Banc : un candidat sans clé est affiché « reject, score 0 » au lieu de « non testé » | basse | `bench/runner.py`, `bench/report.py` | Récap Gmail (retest) | corrigé (#99) |
| 18 | OpenTelemetry en direct : la passerelle refuse le protobuf, seul format de l'exportateur Python | haute | `gateway/proxy.py` (`receive_traces`), `connectors/otel.py` | Sources (27/09) | en cours (#118) |
| 19 | R12 conseille de plafonner la longueur des réponses d'un agent de code | moyenne | `rules/verbose_output.py` | Sources (27/09), Claude Code | ouvert |

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

**Complément (retest).** Deux passages du récap espacés de 1 h 16 : le garde-fou
d'une heure est franchi, le rapport projette **2,53 $/mois** pour le tri. Coût
réel : 0,0022 $ par récap, soit **0,07 $/mois** à un récap par jour, **38 fois
moins**. La projection suppose que le rythme des deux passages, 82 appels en
76 minutes, dure 30 jours d'affilée. Le garde-fou d'une heure ne suffit donc pas :
seule la durée réelle d'observation (heures de démarrage et d'arrêt de la
passerelle), ou le rythme des exécutions, donne une projection juste.

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

### 7. Deadweight ne voit pas les agents lancés par des outils en ligne de commande

**Constat.** Dans shorts-factory, les appels de modèles partent de Claude Code
(le Workflow et ses agents), de `claude -p` et de `codex exec`, pas d'un SDK
dans le code de Miguel. Il n'y a aucun `base_url` à changer dans son code : le
point 1 du critère de réussite du weekend (« changer une variable `base_url` »)
ne s'applique pas tel quel.

**Cause.** Ces outils lisent leur adresse dans l'environnement :
`ANTHROPIC_BASE_URL` pour Claude Code et `claude -p`, `OPENAI_BASE_URL` pour
Codex. La passerelle sait déjà relayer Anthropic sous `/anthropic` (D1.3), mais
rien ne l'explique et ce n'est pas testé.

**Correction.**
- Tester Claude Code à travers la passerelle :
  `ANTHROPIC_BASE_URL=http://127.0.0.1:8080/anthropic claude -p "..."`. Vérifier
  le streaming, les appels d'outils, et que l'authentification par abonnement
  (jeton OAuth, pas une clé `sk-ant-`) est relayée sans être capturée.
- Ajouter au README d'installation une section « agents en ligne de commande »
  avec ces deux variables.
- Pour un test réel, demander à Miguel de lancer **un** lot avec ces variables :
  c'est le seul moyen de mesurer ses agents sans toucher à son code.

### 8. Les agents qui n'exécutent qu'une seule commande échappent à toutes les règles

**Constat.** Les gaspillages les plus nets de shorts-factory (`wait:`,
`marker:`, `costs:report`, `probe:` : fiche ci-dessus) sont des agents Opus
qui font **un seul** appel d'outil, toujours le même, puis rendent un résultat
fixe. Aucune règle ne les attrape :
- R6 `agent_where_chain` exige au moins 2 appels d'outils par trace
  (`MIN_TOOL_CALLS = 2`), un seuil choisi pour ne pas viser la recherche
  documentaire « un appel puis une réponse » ;
- R5 ne voit une boucle qu'à l'intérieur d'une trace ; le sleeper relancé toutes
  les 10 minutes, ce sont des traces séparées ;
- R1 pourrait voir le sleeper (il répond toujours *slept*), mais seulement si
  ses appels partagent un gabarit, alors que son prompt contient la raison de
  l'attente, qui change.

**Correction.** Nouvelle règle, ou extension de R6 : « agent à commande fixe ».
Sur au moins 10 traces d'une même application, si chaque trace fait **un** appel
d'outil dont le nom **et les arguments normalisés** sont identiques (au chemin de
lot près), puis rend une réponse courte, alors un appel direct du script suffit.
Les arguments distinguent ce cas de la recherche documentaire, dont la requête
change à chaque fois. Cas de test : les prompts de `daily-shorts.js`.

### 9. Agents facturés à l'abonnement : le coût en dollars ne dit pas ce qu'ils coûtent

**Constat.** Les agents de Miguel tournent sous Claude Code : son code gère un
« usage cap » (plafond d'usage) et endort le lot jusqu'à sa remise à zéro. Ce
qui coûte, c'est le **quota** et le **temps perdu**, pas une facture au token.
Ni son relevé (qui les ignore) ni Deadweight (qui ne compte que des dollars par
token) ne le montrent.

**Correction.** Pour les appels Anthropic sans prix facturé : afficher les
tokens consommés et leur équivalent au prix public, avec la mention « équivalent,
non facturé ». Ajouter au rapport la **part des appels** d'une application
qu'un constat permettrait d'éviter : sur un plafond d'usage, c'est la mesure
qui parle.

### 10. Les agents qui se passent le relais ne sont pas regroupés en trace

**Constat.** Dans l'OpenAI story flow, **0 appel sur 77** est regroupé en trace,
alors que chaque histoire enchaîne 2 ou 3 agents. Vérifié dans les données :
chaque appel contient **un seul message**, et ce message est **mot pour mot la
réponse de l'agent précédent** (15 vérifications sur 15, 8 histoires sur 8, sur
le premier lot).

**Cause.** L'heuristique de D1.4 ne relie B à A que si B **prolonge la
conversation** de A (le dernier message reçu par A, puis sa réponse, dans
l'historique de B), avec le **même prompt système**. Ici chaque agent démarre une
conversation neuve, avec son propre prompt système : c'est le schéma « chaîne
d'agents » du SDK OpenAI (`Runner.run(agent_suivant, resultat.final_output)`).
Conséquence directe : R6 ne peut pas voir la chaîne la plus fixe qui soit.

**Correction.** Deuxième voie de regroupement, dans `gateway/traces.py` : B
continue A si un message utilisateur de B est **identique** à la réponse de A (au
moins 200 caractères, pour ne pas relier deux « ok »), même application, B
démarre moins de WINDOW_S secondes après la fin de A. Le prompt système peut
changer, puisque c'est un autre agent. Cas de test : `out/workflow3.jsonl`, qui
doit donner 30 traces de 2 ou 3 appels.

### 11. L'API Responses d'OpenAI n'est pas capturée

**Constat.** Le SDK Agents d'OpenAI utilise par défaut l'API **Responses**
(`/v1/responses`), pas `chat/completions`. Une exécution du story flow avec ce
réglage par défaut : réponse normale pour l'utilisateur, relais par la passerelle,
**0 événement capturé**. Pour tester, il a fallu forcer
`set_default_openai_api("chat_completions")`.

**Cause.** `gateway/proxy.py` ne capture que `POST /v1/chat/completions` côté
OpenAI. Tout le reste est relayé sans être vu.

**Impact.** Un client qui construit ses agents avec le SDK officiel d'OpenAI,
la façon recommandée aujourd'hui, **n'est pas audité du tout**, sans aucun
message d'erreur. Le rapport dirait « rien à signaler ».

**Correction.**
- Capturer `POST /v1/responses` : normaliser `input` (chaîne ou liste d'items),
  `instructions` (→ `request.system`), les `output` de type `message` et
  `function_call`, et `usage` (`input_tokens`, `output_tokens`,
  `input_tokens_details.cached_tokens`). Le streaming Responses a ses propres
  événements (`response.output_text.delta`, `response.completed`).
- En attendant, compter les appels relayés **non capturés** par route, et
  l'écrire dans le rapport : « 3 appels vers /v1/responses n'ont pas été
  analysés ». Un trou visible vaut mieux qu'un « rien à signaler » faux.

### 12. L'extraction de règles hors ligne apprend des noms propres

**Constat.** Sur le vérificateur du story flow, l'extraction hors ligne a produit
`elysium|alex|mira|human` pour « science-fiction » et
`clara|bakery|whisker|hotel` pour « pas de science-fiction ». Ce sont les noms des
personnages et des lieux des exemples de ce lot. Ces règles ne valent rien sur
une nouvelle histoire. Le rejeu les refuse, mais pour une autre raison (trop peu
d'entrées), et affiche 100 % d'accord sur les 3 entrées qu'elles couvrent.

**Cause.** L'extraction retient les mots les plus propres à chaque catégorie
dans les exemples. Avec 12 exemples par catégorie, les mots les plus
discriminants sont des noms propres, présents dans un seul exemple.

**Correction.**
- Ne garder un mot que s'il apparaît dans **au moins 3 exemples différents**
  de la catégorie. Un nom de personnage n'apparaît qu'une fois.
- Écarter les mots en majuscule en milieu de phrase (noms propres).
- Dans la preuve, afficher les règles en clair à côté du verdict : un humain voit
  tout de suite que `clara|bakery` ne décrit pas « pas de science-fiction ».

### 13. La bonne règle se trouve en amont : l'extraction ne regarde que l'entrée de l'appel signalé

**Constat.** Sur les 30 vérifications réelles du story flow, la règle « la demande
de l'utilisateur contient *sci-fi* » reproduit la réponse `is_scifi` du
vérificateur **29 fois sur 30**. Mais cette demande est reçue par l'agent 1, pas
par le vérificateur. Ce que reçoit le vérificateur, le plan, ne contient
« sci-fi » ou « science fiction » que dans des cas qui donnent **14 sur 30**.
L'extraction (D3.1) ne lit que l'entrée de l'appel signalé : elle ne peut pas
trouver la règle à 29 sur 30, et se rabat sur des noms propres (problème 12).

**Cause.** Dans une chaîne d'agents, l'information qui décide est souvent dans
l'entrée **d'origine** de la chaîne, avant qu'un premier agent la reformule.

**Correction.** Une fois le problème 10 corrigé (traces reliant les agents qui
se passent le relais), donner à l'extraction et au rejeu, pour chaque appel
signalé, **l'entrée de la première étape de sa trace** en plus de sa propre
entrée. Critère de fin : sur `workflow 3`, une règle d'au moins 95 % d'accord,
construite sur la demande d'origine.

### 14. Sortie structurée : un champ qui ne change jamais n'est pas signalé

**Constat.** Le vérificateur du story flow rend un JSON à deux champs.
`good_quality` vaut `true` **30 fois sur 30**. R1 ne voit qu'une sortie globale
à 2 valeurs et dit « aiguillage », sans dire que la moitié du contrôle ne décide
jamais rien. Le contrôle qualité paie des tokens pour un champ constant.

**Cause.** R1 compte les sorties entières, normalisées comme du texte. Il ne
regarde pas à l'intérieur d'une réponse structurée.

**Correction.** Si les sorties d'un groupe sont du JSON avec les mêmes clés,
calculer aussi la distribution **par champ**. Un champ constant sur au moins
MIN_CALLS appels devient une ligne du constat : « le champ `good_quality` vaut
`true` dans 30 appels sur 30 : il ne décide jamais rien ». Critère de fin : cette
phrase apparaît dans le rapport sur `workflow 3`.

### 15. Le banc de modèles envoie les cas sans le prompt système

**Constat.** Retest du récap Gmail : `openai-gpt-5-nano` obtient **0 % d'accord
sur 29 appels réussis** pour trier des mails dans 5 catégories.

**Cause.** Dans `bench/testset.py`, `_usable_messages` ne garde que les messages
`user`, `assistant` et `tool` de `request.messages`. Or le schéma d'événement range
le prompt système à part, dans `request.system`. Il n'est jamais envoyé au
candidat. Pour le tri de mails, toute la consigne est dans le prompt système
(« Classe le mail dans UNE catégorie parmi : urgent, a_traiter, info, newsletter,
spam »). Le candidat reçoit un mail brut, répond en texte libre, et n'égale jamais
la référence. Le verdict ne dit rien du modèle.

**Correction.** Préfixer les messages du cas par `{"role": "system", "content":
request.system}` quand il existe. Test : un cas dont la consigne n'est que dans
`request.system` doit l'envoyer. Relancer ensuite le banc sur `recap-gmail` pour
avoir un vrai score de gpt-5-nano.

### 16. Le plan de l'agent auditeur contient des chiffres mal attribués

**Constat.** Plan produit sur le retest du récap Gmail :
- « La couverture actuelle des règles est de 69,7 % » : 69,7 % est l'**économie**
  annoncée deux lignes plus haut (« économie 69,7 %, facteur 3,3 »), pas la
  couverture ;
- « Garder en mémoire les réponses pour les cas récurrents (les 5 réponses
  distinctes) » : un cache se fait sur des **entrées** identiques. Ici les 82
  entrées sont 82 mails différents, un cache ne servirait à rien ;
- « L'agent a lancé les six vérifications » : il y en a 14 ;
- le constat affiche « pas encore vérifié par rejeu » alors que le plan, sur la
  même page, cite le rejeu de l'agent (87 %, `REJECT`).

Le rapport affirme « Tous les chiffres viennent des vérifications et du rejeu,
pas du modèle ». Les chiffres existent bien, mais le modèle les rattache à la
mauvaise grandeur.

**Correction.**
- Vérifier chaque chiffre du plan **avec son libellé** : couverture, économie et
  accord sont des champs distincts du rejeu, et un chiffre cité doit l'être avec
  le nom de son champ.
- Refuser une recommandation « cache » si la règle `no_cache` n'a rien trouvé.
- Textes générés à partir du nombre réel de vérifications, et constat marqué
  « rejeu : REJECT, 87 % » quand l'agent l'a rejoué.
- Dire dans le rapport quelle extraction a servi : hors ligne (55 %) ou par IA
  (87 %), sur les mêmes données.

### 17. Banc : un candidat sans clé est affiché « reject, score 0 »

**Constat.** `mistral-ministral-8b` et `openrouter-mistral-small` : 30 appels sur
30 en erreur faute de clé, affichés `reject score=0.0`. On lit « ce modèle ne
convient pas » alors qu'il n'a pas été testé. Par ailleurs `--candidates` ne
filtre que par taille (`small`, `medium`, `local`) : impossible de ne lancer que
les candidats pour lesquels on a une clé.

**Correction.** Verdict `non testé (clé absente)` quand tous les appels
échouent en authentification ou sans clé configurée, et ignorer ces candidats par
défaut. Accepter aussi des identifiants dans `--candidates`
(`--candidates openai-gpt-5-nano,openai-gpt-5-mini`).

### 18. OpenTelemetry en direct : la passerelle refuse le protobuf

**Constat.** Application Python, span GenAI autour d'un vrai appel `gpt-4o-mini`, exportateur
officiel `OTLPSpanExporter` (`opentelemetry-exporter-otlp-proto-http` 1.45), destination
`http://127.0.0.1:8097/v1/traces`. Avec `OTEL_EXPORTER_OTLP_PROTOCOL=http/json` comme le demande le
README, et sans : `Failed to export spans batch code: 415, reason: Unsupported Media Type`. **0
événement capturé.**

**Cause.** `receive_traces` n'accepte qu'un `content-type` JSON. L'exportateur OTLP/HTTP officiel de
Python envoie du protobuf (`application/x-protobuf`), **constaté même avec `http/json`** : le réglage
du README n'a donc aucun effet pour une application Python, qui est le cas le plus courant en IA.

**Correction.** Accepter `application/x-protobuf` dans `receive_traces` : décoder avec
`opentelemetry.proto.collector.trace.v1.trace_service_pb2.ExportTraceServiceRequest`, convertir par
`google.protobuf.json_format.MessageToDict` (identifiants en base64, déjà gérés par
`connectors/otel.py`), puis le même chemin que le JSON. Retirer `http/json` du README. Test : le script
`manual.py` de la fiche, qui doit donner 3 événements.

**À savoir aussi.** L'instrumentation automatique officielle `opentelemetry-instrumentation-openai-v2`
n'a pas pu tourner : 2.4b0 importe un module absent de `opentelemetry-util-genai` 1.2b0, 2.3b0
échoue avec `wrapt` 2.5, et le SDK `openai` 3.x a remplacé `httpx` par `httpx2`. Un client Python qui
suit la documentation OpenTelemetry tombera sur ces erreurs avant même d'arriver chez nous.

### 19. R12 conseille de plafonner les réponses d'un agent de code

**Constat.** Journaux Claude Code d'un vrai projet : R12 « des réponses bien plus longues que
nécessaire », 263 appels, réponse typique 766 jetons, 90e centile 1 799, « plafonner autour de 920
jetons ». Pour un agent de code, une longue réponse est souvent un appel d'outil qui écrit un
fichier : un plafond à 920 jetons couperait l'écriture au milieu.

**Correction.** Ne pas compter dans R12 les réponses dont la longueur vient d'appels d'outils
(arguments de `Write`, `Edit`, `Bash`…), ou exclure les appels qui finissent en `tool_calls`. Ne
proposer un plafond que sur le texte libre rendu à l'utilisateur.

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

- **n8n créé par l'API** : un workflow créé puis activé par l'API publique de n8n 2.40 répond « actif »,
  mais son webhook renvoie 404 (« not registered ») tant qu'on ne l'a pas désactivé puis réactivé.
- **Brancher n8n sur la passerelle** : dans l'identifiant OpenAI de n8n, champ *Base URL* =
  `http://127.0.0.1:8080/v1`, et l'en-tête personnalisé `x-deadweight-app` pour nommer l'application.

- **La passerelle doit tourner.** Sinon l'application échoue avec `Connection
  refused` : c'est le prix du mode proxy. Port par défaut **8080** (les premiers
  essais utilisaient 8787).
- **Clé collée deux fois.** Rien ne s'affiche quand on colle un secret : on colle
  deux fois et OpenAI renvoie un 401 avec une clé masquée de plus de 700
  caractères. Une clé `sk-proj-…` fait 164 caractères : afficher sa longueur
  avant de l'utiliser.
- **Arrêter la bonne passerelle.** Sur macOS, le processus s'appelle `Python` (majuscule) : `pkill -f "python -m gateway"` ne le trouve pas, et une ancienne passerelle continue d'occuper le port. Vérifier avec `lsof -iTCP:8080 -sTCP:LISTEN`.
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

## Modèle pour un nouveau workflow testé

Recopier ce bloc, le remplir, puis ajouter une ligne au tableau « Workflows testés ».

```markdown
### Workflow : <nom> (<date>, <testeur>)

- **Source** : <lien du repo ou dossier>
- **Ce qu'il fait** : <une phrase>
- **Trafic capturé** : <nb d'appels>, <modèles>, <streaming oui/non>, <outils oui/non>, <sur quelle durée>
- **Règles attendues** : <celles qui doivent se déclencher, et celles qui ne doivent PAS>
- **Règles obtenues** : <sortie de report.audit>
- **Rejeu** : <verdict et accord de proof.replay, s'il y a un constat R1>
- **Coût** : <coût réel dépensé> contre <coût affiché par le rapport>
- **Problèmes** : <numéros des fiches ouvertes ou complétées>
```

