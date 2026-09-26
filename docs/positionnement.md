# Positionnement : là où Deadweight a un vrai avantage

Réflexion ouverte le 26/09 au soir, **à travailler dans les tâches du 27/09**. Rien ici n'est encore une
promesse client : chaque point dit ce qui est déjà vrai dans le code, ce qui reste à prouver, et comment.

## L'idée

Les outils du marché mesurent (observabilité), routent (passerelles) ou mettent en cache. Deadweight
répond à une autre question : **fallait-il un agent, un gros modèle, tout ce contexte ?** Et il **prouve** la
réponse sur le trafic réel du client avant de proposer la modification, sous forme d'une micro-PR à
accepter.

Six axes où ça donne un avantage, du plus solide au plus à construire.

## 1. Tout tourne chez le client (confidentialité, RGPD)

**Déjà vrai** : passerelle, capture, vérifications, rejeu, rapport, propositions, micro-PR tournent sur la
machine du client. La base reste chez lui ; les clés sont relayées, jamais stockées ni journalisées (testé) ;
les connecteurs masquent les secrets présents dans les journaux ; les données client vont dans `private/`,
jamais versionné. L'installation locale est une commande (voir le message envoyé à Miguel).

**À prouver** :
- Les deux briques qui appellent un modèle (agent auditeur, banc de modèles) acceptent n'importe quelle
  adresse compatible : les faire tourner **avec un modèle local (Ollama)** et le tester de bout en bout. Si ça
  passe : « aucune donnée ne quitte l'entreprise, même pour l'audit ».
- Minimisation RGPD : l'anonymisation existe pour n8n (en option) ; la rendre systématique pour tous les
  connecteurs quand le contenu n'est pas nécessaire (niveau 1 = usage seul, aucun contenu).
- Durée de conservation : purge automatique de la base après l'audit (commande et délai par défaut).
- Rédiger ce que Deadweight traite, où, et combien de temps (le texte que le DPO du client demandera).

## 2. Souveraineté (optionnelle)

**Déjà vrai** : chaque appel est rattaché à sa destination réelle (levier 16) ; le catalogue connaît l'origine
des modèles et l'hébergement UE possible ; les recommandations proposent une option souveraine.

**À prouver** : tester au banc une alternative européenne (Mistral, Scaleway, OVHcloud) sur un vrai
workflow, avec sa précision mesurée. Positionner la souveraineté en **option** (« même précision, données en
UE »), pas en argument unique : tous les clients ne l'achètent pas.

## 3. Efficacité en coût

**Déjà vrai** : 20 vérifications, coût mesuré sur le trafic réel (prix OpenRouter, cache compris), projection
honnête (pas sous une journée, même période pour tous les constats), micro-PR testées : sur le jeu de test,
tri des mails −72 % de coût à 100 % de précision.

**À prouver** : le même résultat sur trois workflows réels (en cours : passerelle, OpenTelemetry, n8n).

## 4. Efficacité en latence

**Déjà vrai** : latence médiane et p95 mesurées avant/après ; règles chronométrées sur chaque vraie entrée.

**Attention** : ne jamais annoncer un gain de latence global sans dire lequel. Sur le jeu de test, la médiane
baisse de 100 % mais le p95 de 3 % seulement (les cas non couverts restent sur le modèle). Les deux chiffres
vont ensemble.

**À construire** : les étapes parallélisables (R10) donnent le gain de latence d'un workflow entier ; le
mesurer sur un vrai workflow.

## 5. Efficacité en « stockage » : le contexte envoyé

Ce qu'on appelle stockage ici, c'est **le volume de contexte que chaque appel renvoie au modèle** (et que le
fournisseur écrit et relit en cache). C'est le premier poste de coût des agents de code : 72 % chez un
utilisateur Claude Code, 66 % chez Miguel.

**Déjà vrai** : R19 le mesure à partir de l'usage seul ; les propositions chiffrent le contexte envoyé
avant/après.

**À construire** : des propositions testables pour ce levier (sessions plus courtes, contexte de départ
allégé), qui touchent la structure du workflow : les proposer comme recommandations argumentées, pas
comme micro-PR automatiques.

## 6. Écologie et usage raisonné de l'IA

**Déjà vrai** : on mesure exactement les jetons évités (appels remplacés par des règles, contexte en moins,
sorties plafonnées).

**À prouver** : convertir les jetons évités en énergie et en CO₂ demande un facteur par modèle et par
centre de données, qui n'est publié par presque aucun fournisseur. Donc :
- afficher d'abord ce qui est mesuré (jetons et appels évités, calcul évité par des règles) ;
- n'afficher des kWh ou des grammes de CO₂ qu'avec une source citée (études publiées, facteurs
  d'hébergeur) et le statut « estimé » ;
- l'argument honnête et fort : **un appel remplacé par une règle, c'est un appel qui ne consomme plus rien.**

## Ce qu'on affiche, à qui

- **Slack (client, décideur)** : uniquement les gains prouvés, activables en acceptant une micro-PR. Pas de
  propositions rejetées : elles noient le message.
- **Interface développeur** : tout, y compris ce qui a échoué et pourquoi (c'est ce qui rend le reste
  crédible, et ce qui guide le travail suivant).
- **Démo** : on peut montrer les échecs pour prouver l'honnêteté du système.

## Tâches pour le 27/09

1. Tester agent auditeur + banc avec un modèle local (Ollama) de bout en bout.
2. Anonymisation par défaut quand le contenu n'est pas nécessaire ; purge automatique ; texte « données
   traitées » pour un DPO.
3. Banc sur une alternative européenne sur un des trois workflows réels.
4. Écologie : jetons et appels évités dans le rapport ; facteurs énergie/CO₂ seulement sourcés.
5. Recette de micro-PR pour les orchestrations qui nomment le modèle par alias (`'opus'`, cas de Miguel).
