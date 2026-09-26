# Deadweight — roadmap v2 : samedi après-midi → dimanche après-midi

La v1 (`ROADMAP.md`) prévoyait 60 h ; on l'a quasiment bouclée en une matinée à quatre, agents compris.
Cette v2 est **recalibrée sur ce rythme** : les durées sont des heures réelles d'une personne avec son agent,
pas des estimations « à la main ». Même règles de repo que la v1 (une tâche = une issue = une branche = une PR).

Suivi en continu : issue épinglée « Avancement du weekend (automatique) », v2 et v1. Pour y apparaître,
même règle qu'en v1 : issue dont le titre commence par l'identifiant (`A1 — Agent auditeur`), assignée,
et PR au même début de titre avec `Closes #<issue>`.

## Ce qui change

On a une passerelle qui marche et un rapport sur six règles. Il reste trois choses qui décident du hackathon :

1. **Être éligible.** Le règlement X-IA exige un « véritable projet agentique » (LLM + raisonnement, décision,
   orchestration) et ne note **que ce qui a été fait pendant le hackathon**. Aujourd'hui, notre audit est
   surtout du code déterministe : il faut un agent auditeur visible, et déclarer le prototype du 12/09.
2. **Prouver l'impact sur de vrais workflows** (30 % de la note). Des chiffres sur nos jeux de test ne
   suffisent pas : il faut deux ou trois workflows réels, audités, avec « voici ce que vous économisez ».
3. **Une démo de 2 minutes limpide** (15 % pitch + 15 % UX). Tout ce qui ne se voit pas dans la vidéo
   compte peu.

## Règlement X-IA — ce qui nous concerne

| Point | Ce que dit le règlement | Conséquence pour nous |
|---|---|---|
| Dépôt | **dimanche 27/09 à 23:59**, hors délai refusé | on vise **dimanche 20 h**, marge de 4 h |
| Livrables | vidéo **≤ 2 min**, description courte, lien du repo **avec instructions de test dans le README**, noms des membres | V1 à V4 ci-dessous |
| Agentique | LLM + « raisonnement, prise de décision, orchestration d'actions » ; pas un script sans LLM | lot A (agent auditeur) |
| Existant | autorisé, **à mentionner** ; seule la partie faite pendant le hackathon est évaluée ; sinon disqualification possible | A2 : section « construit ce weekend » |
| Participation | membres X-IA à jour de cotisation, équipe déclarée sur Luma | A3 : vérifier les quatre |
| Notation | 30 % impact et utilité · 20 % innovation · 20 % qualité · 15 % UX · 15 % clarté démo/pitch | l'ordre des lots suit ces poids |
| Finale | 5 finalistes, pitch live (octobre/novembre) | hors weekend |

Partenaires avec crédits : OpenAI, Pipelex (workflows agentiques déterministes), Dust (plateforme d'agents),
Gradium (voix), Jinko (voyage). Le règlement ne mentionne **pas de prix réservé** à l'usage d'un partenaire ;
les intégrer sert la note (innovation, qualité) et la visibilité, pas une éligibilité.

## Encore ouvert de la v1

Tout est fusionné (D0.1 à D4.3), sauf **D4.4, le test par un tiers**, dimanche vers 15 h 30. Depuis :
prix OpenRouter avec cache et noms des API (`make prices`), jetons capturés en streaming, coût partiel au
lieu de « non disponible », pas de projection mensuelle sur moins d'une heure de trafic.

## Décisions du 26/09 après-midi

- **Gardé** : A1 (agent auditeur), B1 (import de l'historique n8n, option « lire l'historique »), B3 (analyse
  des vrais workflows, **grosse priorité**, B4 inclus), bloc M (catalogue et recommandations), Q1, D4.4, vidéo.
- **Au bloc rendu, à la fin** : A2 (section « construit pendant le hackathon »), A3 (inscriptions).
- **Coupé ou mis de côté** : B2 (convertisseur de logs), C1 et C2 (outils hors LLM), E1 (Pipelex),
  E2 (voix), E3 (Dust), Q2. B5 (confidentialité) est réduit à un petit dossier `private/`, fait dans B1.
- Premier gros workflow reçu : plan d'analyse et de test plus bas.

Difficulté : ★ mécanique → ★★★★★ on ne sait pas encore faire. Durées en heures réelles, agent compris.

## Récapitulatif

| Id | Tâche | Difficulté | Temps | Stack technique | Qui |
|---|---|---|---|---|---|
| A1 | Agent auditeur | ★★★★ | 7 h | Python, SDK OpenAI (appel d'outils), JSON Schema, modules existants | Hugo (+ Claude pour les tests) |
| B1 | Import de l'historique n8n | ★★★★ | 6 h | Python, API publique n8n v1, JSON de workflow n8n, schéma d'événement | Thibaud |
| B3 | Analyse du premier workflow | ★★★ | 3 h | B1 + règles + rapport, revue humaine | toute l'équipe |
| M1 | Catalogue : origine, hébergement, qualité, vitesse | ★★★ | 4 h | Python, API OpenRouter, API Artificial Analysis, tables JSON versionnées | Alexandre |
| M2 | Recommandations de modèles | ★★★★ | 5 h | Python, M1, rejeu D3.2 | Alexandre |
| Q1 | Boucle de bout en bout en CI | ★★ | 1 h | bash, GitHub Actions, faux fournisseurs | Codex |
| — | Vrai trafic OpenAI par la passerelle | ★ | 15 min | `make dev`, clé réelle | Natan |
| D4.4 | Test par un tiers | ★ | 2 h | aucun | Natan (observateur) |
| A2, A3 | Section « construit pendant le hackathon », inscriptions | ★ | 45 min | README, Luma | Claude, Natan |
| V1–V4 | Script, tournage, description, dépôt | ★★ | 4 h | enregistrement d'écran, montage | Natan + un volontaire |

## A1 — Agent auditeur · ★★★★ · 7 h

**Pourquoi** : le règlement exige un projet agentique (raisonnement, décision, orchestration). Aujourd'hui,
l'audit est un enchaînement fixe : les six règles, le chiffrage, le rapport ; le rejeu se lance à la main ; le
seul appel à un LLM est l'extraction des règles. A1 remplace l'enchaînement fixe par un agent qui enquête et
arbitre, avec nos modules comme outils.

**Ce qu'il fait** : il regarde le trafic, choisit quoi prouver en premier (le plus cher), lance le rejeu, lit
le verdict. En cas de refus, il comprend pourquoi et tente autre chose (autres règles, modèle de secours, ou mode
miroir pour observer plus longtemps). Il termine par un plan d'action priorisé (quoi faire d'abord, gain,
risque), éventuellement posté sur Slack.

**Stack** : Python ; SDK OpenAI avec appel d'outils (crédits partenaire) ; un modèle rapide et peu cher pour
l'agent ; JSON Schema pour décrire les outils ; modules existants (`rules/`, `report.cost`, `proof.extract`,
`proof.replay`, `gateway.mirror`, bloc M) ; pytest avec un faux LLM scripté.

| Sous-tâche | Contenu | ★ | Temps |
|---|---|---|---|
| A1.1 Outils | Emballer l'existant en outils à réponses courtes : `lister_apps`, `lancer_regles`, `detail_constat` (extraits tronqués), `extraire_regles`, `rejouer`, `stats_miroir`, `alternatives_modele` (bloc M), `publier_plan` | ★★ | 1 h 30 |
| A1.2 Boucle | Appel d'outils en boucle, budget (25 appels d'outil maximum), condition d'arrêt, deux tentatives maximum par constat refusé | ★★★ | 2 h |
| A1.3 Garde-fous | Aucun chiffre inventé : chaque nombre du texte doit sortir d'un résultat d'outil (vérification automatique, sinon on régénère). Coût de l'audit affiché. Décider **avec quelle clé tourne l'agent** : celle du client (ses données restent chez son fournisseur) ou la nôtre | ★★★★ | 1 h |
| A1.4 Journal | Section « Comment l'agent a mené l'audit » dans le rapport : étapes, outils appelés, décisions, avec un journal JSON | ★★ | 1 h |
| A1.5 Intégration et tests | `make audit` passe par l'agent quand une clé est disponible, sinon rapport déterministe comme aujourd'hui ; tests hors ligne avec un faux LLM ; évaluation sur le jeu D0.3 (l'agent doit prioriser mail-triage) | ★★★ | 1 h 30 |

**Risques** : chiffres inventés (A1.3), non-déterminisme (tests avec un faux LLM), données client envoyées au
modèle de l'agent (A1.3), coût et durée de l'audit.

## B1 — Import de l'historique n8n · ★★★★ · 6 h

**Pourquoi** : un fichier de workflow ne contient aucun trafic. L'historique des exécutions, lui, contient les
vrais appels, en vrai volume. La détection reste indépendante de n8n (la passerelle ne change pas) : B1 est un
**importeur**, une deuxième source d'événements.

**Stack** : Python ; API publique n8n v1 (`GET /api/v1/executions?workflowId=…&includeData=true`, pagination par
curseur, en-tête `X-N8N-API-KEY`) ; JSON de workflow n8n (nœuds, connexions `ai_languageModel` et `ai_tool`) ;
schéma d'événement ; reprise de `detector/scan.py` (prototype), qui savait déjà trouver le modèle d'un nœud.

| Sous-tâche | Contenu | ★ | Temps |
|---|---|---|---|
| B1.1 Récupération | Une commande que **le client lance chez lui** (`python -m importers.n8n fetch --url … --workflow …`, clé en variable d'environnement) : elle écrit un fichier d'exécutions, qu'il peut auditer lui-même ou nous envoyer. Pagination, limite, reprise | ★★ | 1 h |
| B1.2 Conversion | Workflow + exécutions → événements : trouver les nœuds LLM et leur sous-nœud modèle (fournisseur, modèle) ; dans `runData` du sous-nœud : messages envoyés, texte rendu, jetons (`tokenUsage`), heure, durée ; appels d'outils de l'agent (pour R5 et R6) ; `app_id` = workflow et nœud ; **`trace.id` = identifiant d'exécution** (regroupement exact, meilleur que la déduction de D1.4) ; erreurs | ★★★★ | 3 h |
| B1.3 Taux de compréhension | Ce qu'on n'a pas su lire : nœuds ignorés, appels sans jetons, modèles inconnus. Un chiffre « X % des appels LLM du workflow compris » dans le rapport | ★★ | 1 h |
| B1.4 Confidentialité | Dossier `private/` ignoré par git, option d'anonymisation (emails, téléphones) avant analyse, suppression après | ★★ | 30 min |
| B1.5 Tests | Extrait anonymisé du vrai workflow en jeu de test, résultat attendu figé | ★★ | 30 min |

**Risques** : l'instance n'enregistre pas les exécutions réussies (réglage n8n) ou les a purgées — **à vérifier
en premier** ; selon la version du nœud, les jetons ne sont pas toujours stockés ; formats qui varient d'une
version de nœud à l'autre ; gros volumes ; données sensibles.

## M — Catalogue et recommandations · gros bloc, 9 h au total

M1 fournit les données, M2 décide. Pour le weekend, on peut s'arrêter à la version courte (★ ci-dessous).

### M1 — Catalogue · ★★★ · 4 h

**Stack** : Python ; API OpenRouter (prix et contexte, déjà branchée : `make prices`) ; API Artificial Analysis
(indice de qualité, jetons/s, délai du premier jeton ; clé gratuite) ; tables JSON versionnées dans `fixtures/`.

| Sous-tâche | Contenu | ★ | Temps | Weekend |
|---|---|---|---|---|
| M1.1 Origine et hébergement | `fixtures/providers.json` : pour chaque éditeur (préfixe OpenRouter) le pays, l'hébergement UE possible, l'option souveraine, la source et la date. Environ 30 lignes, tirées de `docs/research/modeles.md` | ★ | 1 h | oui |
| M1.2 Qualité et vitesse | Artificial Analysis → indice de qualité, vitesse, premier jeton ; table de correspondance des noms avec OpenRouter (le plus pénible) ; cache daté | ★★★ | 2 h | si le temps |
| M1.3 Latence observée | Latence p50/p95 par modèle mesurée chez le client, depuis ses propres événements | ★ | 30 min | oui |
| M1.4 Rafraîchissement | `make catalog`, tests | ★ | 30 min | oui |

### M2 — Recommandations · ★★★★ · 5 h

**À quoi ça sert** : R2 propose déjà un modèle moins cher **de la même famille**. M2 ajoute les autres
fournisseurs, un garde-fou qualité et l'option souveraine. **Quand c'est nécessaire** : si le pitch porte sur la
souveraineté, ou si les vrais workflows utilisent des modèles sans petit frère au catalogue.

| Sous-tâche | Contenu | ★ | Temps | Weekend |
|---|---|---|---|---|
| M2.1 Moteur | Candidats moins chers, capacités compatibles (outils, JSON, contexte ≥ plus gros prompt observé, images), qualité suffisante pour la tâche ; trois options : moins cher, meilleur compromis, souverain | ★★★ | 2 h | oui |
| M2.2 Preuve | Rejouer un échantillon avec le modèle proposé (chemin « modèle de secours » de D3.2, clé du client) ; sinon « non prouvé » | ★★★★ | 2 h | non |
| M2.3 Rendu | Dans le rapport, et comme outil `alternatives_modele` de l'agent A1 | ★★ | 1 h | oui |

## B3 — Premier workflow : plan d'analyse et de test

But : savoir si notre système comprend tout le workflow, ce qu'il propose de modifier, et s'il a raison.

1. **Réception** (15 min) — fichier dans `private/` ; format : workflow seul, ou avec ses exécutions ? taille,
   nombre de nœuds.
2. **Cartographie à la main, avant tout outil** (30 min) — nœuds, nœuds LLM, modèles, outils, sous-workflows,
   déclencheurs ; schéma de la chaîne. **On écrit nos hypothèses** : ce qu'un expert changerait ici. C'est
   la référence pour juger le système.
3. **Données** (15 min) — des exécutions existent-elles ? combien, sur quelle période ? Sinon : demander
   d'activer l'enregistrement des exécutions, ou le faire tourner sur des exemples (option de secours).
4. **Conversion (B1)** — contrôles : nombre d'événements = nombre d'appels LLM dans les exécutions ; 100 %
   conformes au schéma ; part des appels avec jetons ; part des modèles chiffrés ; **taux de compréhension**.
5. **Audit** — six règles, chiffrage, rapport ; puis l'agent A1 dès qu'il existe.
6. **Revue humaine** (45 min) — chaque constat : vrai ou faux positif ? Ce qu'on a manqué (faux négatifs) :
   ce sont les prochaines règles. Comparaison avec les hypothèses de l'étape 2.
7. **Preuve** — pour les nœuds qui classent : extraction des règles, rejeu, verdict.
8. **Fiche d'une page** pour l'entreprise, et son retour : valident-ils ?

**Critères de réussite** : ≥ 90 % des appels LLM convertis ; 100 % conformes au schéma ; ≥ 95 % chiffrés ;
chaque constat revu ; aucun faux positif grave ; liste écrite des manques. L'extrait anonymisé devient un test.

## Planning

| | Samedi 16 h – 21 h | Dimanche 10 h – 14 h | Dimanche 14 h – 20 h |
|---|---|---|---|
| **Natan** | B3 étapes 1-3 (cartographie, hypothèses) ; testeur D4.4 ; vrai trafic OpenAI | B3 revue ; V1 | D4.4 ; V2, V3, V4 ; A3 |
| **Hugo** | **A1.1, A1.2** | A1.3, A1.4, A1.5 | corrections après D4.4 |
| **Thibaud** | **B1.1, B1.2** | B1.3, B1.4, B1.5 ; B3 étapes 4-7 | gel, relectures |
| **Alexandre** | M1.1, M1.3, M1.4 | M2.1, M2.3 | M1.2 si le temps |
| **Codex** | Q1 | — | — |
| **Claude** | relectures, fusions ; aide B1.2 et A1.5 | aide B3 ; A2 | relecture finale du README |

**Gel dimanche 14 h** : plus de nouvelle fonctionnalité. Ensuite, corrections, D4.4, vidéo et dépôt (20 h).

## Ordre de coupe si on déborde

1. M1.2, puis M2.2 (déjà hors weekend), puis M2.1 et M2.3 (R2 suffit).
2. A1.4 (le journal) — mais jamais A1.1 à A1.3 : sans agent, pas d'éligibilité.
3. B1.3 et B1.5 — on garde la conversion et un vrai workflow analysé.

**On ne coupe jamais A1 (hors A1.4), B1.1-B1.2, B3 sur un workflow, A2, A3, D4.4, la vidéo et le dépôt.**

## D4.4 — protocole du test par un tiers

- **Qui** : quelqu'un hors de l'équipe, jamais briefé, avec un terminal, Python 3.11, sa clé OpenAI et
  idéalement une petite appli. Pas un ami proche. Prévoir un remplaçant.
- **Quand** : dimanche vers 15 h 30, 45 minutes.
- **Comment** : on lui envoie le lien du repo, rien d'autre. Un observateur note l'heure de chaque étape,
  chaque hésitation de plus de 30 s, chaque question, chaque erreur, **sans jamais aider**.
- **Critères** : il change `base_url` seul ; il fait passer du trafic ; une commande lui donne le rapport ;
  il ne nous a pas appelés ; le tout en moins de 10 minutes.
- **Après** : qu'est-ce qui t'a bloqué ? qu'as-tu compris du rapport, en une phrase ? le paierais-tu ?
  Chaque blocage devient une correction avant 18 h, README et messages d'erreur d'abord.

## Tâches hors code

| Tâche | Qui |
|---|---|
| Recevoir les workflows, demander le format (export n8n, logs, ou accès via la passerelle), envoyer l'engagement de confidentialité | Natan |
| Trouver un 3ᵉ workflow (B4) | Natan ou Hugo |
| Testeur D4.4 et remplaçant | Natan |
| Faire lire le rapport à quelqu'un hors équipe (critère de D4.1 jamais vérifié) | n'importe qui, 15 min |
| Script, tournage, montage de la vidéo | Natan + un volontaire |
| Liste des 5 entreprises pour la validation, message d'approche | Natan |

## Pistes de réflexion

À trancher à quatre, idéalement samedi soir : ça décide ce qu'on montre dans la vidéo et ce qu'on construit
dimanche. Rien ici n'est encore décidé.

### 1. Recadrer le problème qu'on résout

Ce qu'on a construit : une passerelle qui regarde les appels LLM d'un workflow agentique, trouve six formes de
gaspillage, **prouve** par le rejeu qu'un remplacement donne les mêmes réponses, et peut court-circuiter le
modèle. La question de départ reste la bonne : *est-ce que ça avait besoin d'être un agent ?*

Mais le même produit peut se vendre sur quatre problèmes différents. Il faut en choisir un pour le pitch :

| Problème | Ce que le client dit | Ce qu'on montre | Qui achète |
|---|---|---|---|
| **Coût** | « la facture OpenAI double tous les trimestres » | coût par mois avant/après, prouvé | CTO, CFO de scale-up |
| **Visibilité** | « on ne sait pas ce que font nos agents » | inventaire, traces, boucles | responsable ops / automatisation |
| **Fiabilité** | « nos agents se trompent sans qu'on le voie » | taux d'accord, rejeu, mode miroir | produit, qualité |
| **Souveraineté** | « nos données partent aux États-Unis » | origine et hébergement de chaque appel, alternative UE | DSI, conformité, secteur public |

Question à trancher : **une phrase de problème**, un client type, et ce qu'on ne fait pas.

### 2. Selon la verticale, la stack à optimiser change

Un workflow agentique n'est pas qu'un modèle : c'est une chaîne d'outils, et chaque verticale a la sienne.

| Verticale | Workflow typique | Outils autour du LLM | Ce qu'on optimiserait | Ce qui compte pour le client |
|---|---|---|---|---|
| Marketing / growth | enrichissement de leads, emails personnalisés, veille | recherche web (Tavily, Exa, Brave), scraping (Firecrawl, Apify), enrichissement (Clay, Apollo, Dropcontact), envoi (Lemlist, Brevo) | doublons d'enrichissement et de scraping, recherche payée deux fois, modèle haut de gamme pour écrire une accroche | coût par lead, délai |
| Support client | tri des tickets, réponse avec base de connaissances | helpdesk, RAG, embeddings | tri par LLM → règles ; contexte brut → RAG ciblé ; cache | temps de réponse, justesse |
| E-commerce | fiches produit, tri des avis, réponses aux avis | catalogue, images | génération en lot (API batch), petit modèle | coût par fiche |
| Juridique / finance | extraction de documents, conformité | OCR, stockage documentaire | modèle adapté à l'extraction, **hébergement UE** | souveraineté, exactitude |
| Recrutement | tri de CV, premiers échanges | ATS, messagerie | tri par LLM → règles ; biais à surveiller | équité, délai |

Question à trancher : **quelle verticale pour la démo et les premiers clients ?** Critères : accès à de vrais
workflows, volume d'appels, sensibilité au coût ou à la souveraineté, capacité à payer.

### 3. Au-delà du choix du modèle : la façon de l'utiliser

À modèle égal, l'usage change la facture. Pistes de nouvelles règles :

- **Cache** : jusqu'à ~90 % du coût d'entrée évitable sur un préfixe répété, mais seuils et activation propres
  à chaque fournisseur (automatique chez OpenAI et Gemini, explicite chez Anthropic et Mistral).
- **API batch** pour ce qui n'est pas urgent (génération de fiches, enrichissement de nuit).
- **Sorties structurées** plutôt que du texte libre relu par un deuxième appel.
- **Taille du contexte** : ce qu'on envoie et ne sert à rien (R3 le fait en partie).
- **Appels en série qui pourraient être parallèles** : la latence, pas le coût.
- **Routage** : petit modèle d'abord, grand modèle seulement si besoin.
- **Hors LLM** : règles, puis classifieur léger, puis embeddings, puis petit modèle ; le grand modèle en dernier.
  Pour classer, l'écart de coût va de ×10 à plus de ×100.

### 4. La souveraineté, un argument à part entière

La recherche (`docs/research/modeles.md`) montre que **l'hébergement compte plus que le fournisseur** :
l'API directe d'Anthropic n'a pas d'hébergement UE (tout part aux États-Unis) ; OpenAI et Gemini en proposent un ;
Mistral, Scaleway et OVHcloud sont les seules options entièrement françaises. Pour un client français, « passer de
X à Y » peut se justifier par la conformité avant le prix. D'où la colonne origine / hébergement du catalogue (M1).

### 5. Ce qui sort sur le marché

Chaque mois arrivent de nouvelles briques : passerelles et routeurs (LiteLLM, Portkey, OpenRouter),
observabilité (Langfuse, Helicone), serveurs MCP, SDK d'agents, fonctions natives des fournisseurs (cache
automatique, routage). Deux conséquences :

- **Se différencier** : les autres mesurent, routent ou mettent en cache. Nous, on répond à « fallait-il un
  agent ? » et on **prouve** le remplacement avant de le proposer. C'est ce qu'il faut répéter dans le pitch.
- **S'appuyer dessus plutôt que les refaire** : lire les traces d'un outil d'observabilité existant, exporter
  vers Pipelex, être un serveur MCP que les agents appellent. À surveiller : un fournisseur qui intègre nativement
  une de nos règles la rend inutile.

Question à trancher : **qu'est-ce qu'on implémente nous-mêmes, et sur quoi on se branche ?**

### 6. Ce qu'on garde pour après le weekend

Relais des outils hors LLM (lot C) si on le coupe, verticales non choisies, intégrations d'observabilité,
mode serveur MCP, validation auprès de cinq entreprises, préparation de la finale X-IA (octobre-novembre).
