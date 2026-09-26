# 9. Un agent là où une chaîne fixe suffit

| | |
|---|---|
| Famille | Forme des briques d'IA |
| Gain argent | Coût d'orchestration |
| Gain latence | Moyenne |
| Comment prouver | Traces |
| Données nécessaires | Événements regroupés en traces |
| État | Fait (R6) |
| Règle | R6 agent_where_chain |

## Le signal
L'agent suit toujours le même chemin d'outils.

## Comment le détecter
Part du chemin dominant parmi les traces (seuil 90 %, 10 traces minimum).

## Ce qu'on propose au client
Remplacer par une chaîne fixe ; garder l'agent pour les cas atypiques.

## Comment le prouver avant de le recommander
Distribution des chemins.

## Suite
—
