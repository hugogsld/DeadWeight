# Vérification des critères sur des données réelles (13/11)

Méthode habituelle : chaque constat porte un statut (mesuré, estimé, non testé) ; aucun chiffre qui ne
vienne pas de nos outils ; preuve par rejeu quand c'est possible. Ici : les 12 vérifications qui n'avaient
été validées que sur des jeux synthétiques ont été lancées sur des données réelles, puis chaque constat a
été jugé à la main (vrai ou faux positif).

Confidentialité : les données réelles sont restées hors du dépôt. Ce document ne contient que des
comptes et des noms de règles. Les tests de non-régression utilisent des fixtures **inventées**, qui
reprennent la forme (volumes, champs) du cas réel.

## Données réelles trouvées sur le Mac

- **Journaux Claude Code** (via `connectors.agent_logs`) : 398 fichiers, 147 sessions, **18 073 appels**
  lus (215 ignorés : 178 recopiés par une session reprise, 37 messages fabriqués par l'outil). 100 % Anthropic,
  3 modèles, 159 identifiants d'application.
- **Journaux du plugin de mémoire** (observateur) : 145 fichiers, 119 sessions, 407 appels lus (318 ignorés).
- **Journaux d'un dossier de notes** : 36 appels. **Codex** : 1 session, 110 appels.
- **Historique n8n local** : 51 événements (modèle de tri d'emails) et 161 événements (tri de tickets).
  Workflow n8n réel, mais l'amont de modèle était simulé ou non vérifié : valeurs de sortie utiles pour la
  forme, pas pour juger un modèle.
- **Introuvable** : captures de la passerelle sur de vrais workflows (récap Gmail, story flow, tickets), seuls
  des jeux de démonstration générés existent ; données d'usage de Miguel : un relevé de coûts par agent, sans
  événements. Pas de fichier d'erreurs réelles.

**Limite majeure des journaux d'agents de code** (mesurée) : le connecteur ne capture ni `max_tokens`
(toujours vide), ni le mode de streaming (toujours « oui »), ni les outils déclarés (vide sur 18 073 appels),
ni le prompt système ; `request.messages` ne contient que les messages ajoutés. Et `upstream` est écrit en dur
(`api.anthropic.com`). Plusieurs vérifications ne peuvent donc **pas** conclure sur ces données, quelle que soit
la qualité de la règle. Corrections à faire côté `connectors/agent_logs` (hors de ce lot).

## Vérification par vérification

**duplicate_calls**. Données : n8n tickets (161 appels). Constat : 1, deux appels en trop, 2 vrais
positifs / 0 faux positif (même texte de ticket, même réponse, à 40 s d'écart). Sur Claude Code : 0 constat,
mais les requêtes n'y sont pas complètes (messages ajoutés seulement), donc non concluant. Correction : aucune.
Statut : **vérifié sur réel, petit échantillon** (2 positifs).

**paid_errors**. Aucune erreur dans les 18 073 appels (le connecteur écarte les erreurs), aucune dans n8n.
Statut : **pas de donnée réelle**. Donnée à obtenir : une capture de passerelle avec des réponses tronquées
(`finish_reason = length`) ou des 429 suivis de relances.

**verbose_output**. Avant : 64 constats sur Claude Code, dont **64 faux positifs** : 68 à 100 % de leurs tours
rendaient un appel d'outil, c'est-à-dire des arguments (fichier à écrire, commande) qu'un plafond couperait
(problème n°19). Correction : les tours à appel d'outil sortent de l'échantillon. Après : **12** constats, sur
les seuls tours de texte (2 275 appels). Ces 12 restent non actionnables en l'état : `max_tokens` n'est pas
capturé, donc « sans plafond » est un défaut d'information, pas un fait. Test : fixture inventée (60 tours,
90 % d'appels d'outils) + groupe texte seul. Statut : **faux positifs corrigés sur réel ; positifs non vérifiables**
tant que le connecteur ne capture pas `max_tokens`.

**excess_reasoning**. Réservé à OpenAI (champ `reasoning_tokens` inclus dans `output_tokens`, documenté) ;
aucun appel OpenAI à raisonnement dans les données (Codex : 110 appels, 0 constat). Statut : **pas de donnée
réelle**. Donnée à obtenir : une capture OpenAI avec un modèle de raisonnement sur une tâche de tri.

**tool_bloat**. Les outils déclarés ne sont pas capturés (0 appel sur 18 073 en porte). Statut : **pas de
donnée réelle**. Donnée à obtenir : capture passerelle d'un agent avec ≥ 5 outils.

**raw_context**. 0 constat sur 147 traces. Les tours de Claude Code produisent trop de sortie (médiane
supérieure au plafond de 256 jetons) pour entrer dans la règle : 0 faux positif, mais aucun positif non plus.
Statut : **données d'essai seulement** ; donnée à obtenir : un chat long à réponses courtes, par la passerelle.

**unbounded_loop**. Sur 147 traces : 49 contenaient ≥ 5 « répétitions », 0 atteignaient la part de 50 % :
**0 constat, aucun vrai manque repéré** (les cas les plus répétés sont des appels identiques d'outils de
navigateur et de lecture, 13 à 27 sur 300 à 3 000 actions). Mais le comptage des répétitions était **gonflé** :
deux lectures de fichiers différents d'un même dossier comptaient comme « quasi identiques » (mots du chemin
en commun) : 3 176 répétitions comptées, 2 534 après correction (-20 %), traces à ≥ 5 répétitions 49 → 43.
Risque évité : une lecture de 8 fichiers d'un dossier signalée comme boucle. Correction : un chemin de
fichier se compare en entier. Test : fixture inventée (10 lectures de chemins différents → aucun constat ;
8 relectures du même fichier → boucle). Statut : **vérifié sur réel pour les faux positifs ; positifs réels
absents**.

**batch_eligible**. Faits vérifiés dans la doc fournisseur : OpenAI et Anthropic facturent le batch à
**-50 %**, délai jusqu'à 24 h ; Anthropic : tous les modèles actifs. Les rafales nocturnes de la règle
n'apparaissent pas dans les données (le connecteur marque tout en streaming, que la règle écarte). Statut :
**pas de donnée réelle** ; hypothèse UTC déjà documentée. Donnée : une capture passerelle d'une tâche planifiée
nocturne non streamée sur 3 nuits.

**image_heavy**. 837 appels avec images dans les journaux. Mesure : jetons d'entrée par image, médiane 1 530
(p90 3 903) ; seuil de la règle 2 048. La doc Anthropic donne ⌈largeur/28⌉×⌈hauteur/28⌉ jetons, plafonné à
1 568 (standard) ou 4 784 (haute résolution) : la règle ne peut se déclencher qu'en haute résolution ou
avec du texte. 0 constat, 0 faux positif ; risque de **manques** sur les modèles standard. Statut : **données
d'essai seulement** (non modifié, hypothèse d'un seuil prudent). Donnée : un flux d'images de ≥ 1 megapixel.

**agent_where_chain**. 0 constat sur 147 traces (aucune trace n'a 10 chemins quasi identiques). Le trou
signalé (agents à une seule commande, n°7-8) reste ouvert : aucun jeu réel d'agents à commande fixe
(données de Miguel : un relevé de coûts, pas d'événements). Statut : **pas de donnée réelle**.

**data_outside_eu**. 173 constats sur Claude Code, 5 sur Codex, 4 sur n8n : tous « sortent de l'Europe ». Vrai
sur le fond (Anthropic direct : `inference_geo` « us » ou « global », pas d'option UE ; OpenAI : région UE sur
demande, `eu.api.openai.com`). Faux sur la **certitude** : les connecteurs d'agents de code écrivent l'hôte en
dur, et la règle l'affiche comme « observée » alors qu'il est supposé (Claude Code peut passer par Bedrock ou
Vertex en UE). Correction proposée, hors de ce lot : mettre `upstream` à vide dans les connecteurs d'agents
(la règle dit alors « déduite »). Statut : **vérifié sur le fond, certitude à corriger côté connecteur**.

**llm_judge**. 0 constat. Les messages des journaux étant incomplets (messages ajoutés seulement), la
relecture d'une réponse par un second appel n'est pas reconstituable. Statut : **pas de donnée réelle**.
Donnée : capture passerelle d'une chaîne génération → vérification.

## Problèmes ouverts traités

- **n°23 (fragments de mots)** : corrigé dans `proof/extract.py`. Les listes de mots simples deviennent des
  mots entiers (`\b(?:a|b)s?\b`), au moment de générer et au moment de lire (donc les preuves déjà écrites,
  avec « pui », sont corrigées sans les refaire). Une regex déjà structurée n'est pas touchée. Test : le cas
  « depuis » n'attrape plus « pui » ; « puis-je » reste reconnu. Conséquence assumée : une règle écrite en
  racine (« factur ») ne couvre plus « facturation » ; la couverture sur exemples baisse, le rejeu mesure.
  `patcher/rules_offline.py` génère encore des racines (non modifié, chemin hors preuve).
- **n°3 (échantillon du rejeu)** : seuil de 30 inchangé. Le rapport dit maintenant « NON CONCLU, échantillon
  trop petit (pas un échec des règles) » et combien d'appels de plus il faut.
- **n°7-8, n°6** : pas de donnée réelle (agents en ligne de commande, historique réécrit) : ouverts.
