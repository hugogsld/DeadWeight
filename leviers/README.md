# Leviers d'optimisation

Tout ce sur quoi Deadweight peut faire gagner de l'argent, de la latence ou de la fiabilité à un workflow
agentique, **classé par importance** (gain × fréquence × facilité à prouver). Une fiche par levier : le
signal, la détection, ce qu'on propose, comment on le prouve, les données nécessaires, l'état.

Principe commun : **rien n'est recommandé sans preuve sur le vrai trafic du client** (rejeu, banc de
modèles, calcul exact sur l'historique). Un levier non prouvé reste une piste.

Fichiers générés par `python leviers/_generer.py` : modifier la liste dans ce script, pas les fiches.

| Rang | Levier | Famille | Argent | Latence | Preuve | État |
|---|---|---|---|---|---|---|
| 1 | [Un LLM qui ne fait qu'aiguiller](01-llm-qui-aiguille.md) | Usage des LLM | 90 à 100 % de l'étape | ×1 000 (700 ms → 0,2 ms) | Rejeu, seuil 95 % | Fait (R1, D3.1, D3.2, D3.3, D4.3) |
| 2 | [Un modèle trop gros pour la tâche](02-modele-surdimensionne.md) | Usage des LLM | ÷10 à ÷20 (gpt-4o → mini) | Premier mot plus rapide | Banc de modèles | Détection faite (R2), banc en cours, M1/M2 (Hugo) |
| 3 | [Un modèle qui réfléchit trop](03-raisonnement-excessif.md) | Usage des LLM | 50 à 80 % des appels concernés | Forte (le raisonnement précède la réponse) | Banc (effort bas vs haut) | En cours (R7) |
| 4 | [Le cache de prompt non utilisé](04-cache-de-prompt.md) | Usage des LLM | Jusqu'à 90 % du coût d'entrée répété | Premier mot plus rapide | Calcul exact | Fait (R4) ; prix du cache branchés (OpenRouter) |
| 5 | [Trop de contexte envoyé (historique, RAG)](05-contexte-et-rag.md) | Forme des briques d'IA | Coût d'entrée ÷2 à ÷10 | Moyenne | Banc (contexte réduit) | Symptôme détecté (R3) ; causes RAG à faire |
| 6 | [Des étapes en série qui pourraient tourner en parallèle](06-etapes-paralleles.md) | Forme du workflow | Aucun | Le plus gros gain : ×2 à ×5 sur le workflow | Horaires d'exécution | Détection faite (R10), indépendance métier à confirmer |
| 7 | [Les mêmes appels payés plusieurs fois](07-appels-identiques.md) | Usage des LLM | 100 % de chaque doublon | Réponse immédiate si mise en cache | Calcul exact | En cours (R8) |
| 8 | [Un agent qui tourne en rond](08-agent-en-boucle.md) | Forme des briques d'IA | Chaque tour en trop | Forte | Traces | Fait (R5) |
| 9 | [Un agent là où une chaîne fixe suffit](09-agent-ou-chaine.md) | Forme des briques d'IA | Coût d'orchestration | Moyenne | Traces | Fait (R6) |
| 10 | [Un appel LLM par élément au lieu d'un appel groupé](10-boucle-sur-elements.md) | Forme du workflow | ÷5 à ÷20 | ÷5 à ÷20 | Banc (lot vs unitaire) | À faire (R11, après B1) |
| 11 | [Des réponses trop longues](11-sorties-trop-longues.md) | Usage des LLM | 20 à 60 % (la sortie coûte 4 à 8 fois l'entrée) | Proportionnelle | Calcul + banc | En cours (R12) |
| 12 | [Des erreurs et relances payées](12-erreurs-et-relances.md) | Usage des LLM | Variable, parfois énorme | Forte (attentes, relances) | Calcul exact | En cours (R9) |
| 13 | [Des tâches non urgentes payées plein tarif](13-api-batch.md) | Usage des LLM | 50 % | Aucun (elle augmente, c'est voulu) | Calcul exact | Détection faite (R14), éligibilité à confirmer |
| 14 | [Les autres API du workflow (recherche, scraping, enrichissement)](14-autres-api.md) | Appels d'autres API | Doublons : 100 % ; choix du fournisseur : ÷3 | Appels parallélisables | Calcul exact | Mis de côté (C1, C2) |
| 15 | [Des définitions d'outils envoyées à chaque appel](15-definitions-outils.md) | Forme des briques d'IA | 10 à 40 % de l'entrée d'un agent | Faible | Calcul | Détection faite (R13), gain estimé à confirmer |
| 16 | [Des données qui partent hors d'Europe](16-souverainete.md) | Conformité | — | — | Catalogue (origine, hébergement) | Bloc M (Hugo) |
| 17 | [Autres gains sur la forme du workflow](17-forme-du-workflow.md) | Forme du workflow | Variable | Variable | Graphe + historique | À faire, après B1 |
| 18 | [Images en haute résolution, relecture par un LLM juge](18-images-et-relecture.md) | Usage des LLM | Images : ÷5 à ÷10 ; relecture : ×2 évité | Moyenne | Calcul + banc | Détection faite (R15, R16), qualité et gains à confirmer |
