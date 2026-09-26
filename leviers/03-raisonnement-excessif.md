# 3. Un modèle qui réfléchit trop

| | |
|---|---|
| Famille | Usage des LLM |
| Gain argent | 50 à 80 % des appels concernés |
| Gain latence | Forte (le raisonnement précède la réponse) |
| Comment prouver | Banc (effort bas vs haut) |
| Données nécessaires | Événements (reasoning_tokens) |
| État | En cours (R7) |
| Règle | R7 excess_reasoning |

## Le signal
Beaucoup de jetons de réflexion facturés pour des réponses courtes ou triviales.

## Comment le détecter
Rapport jetons de réflexion / jetons de sortie visibles, croisé avec la simplicité de la tâche.

## Ce qu'on propose au client
Baisser l'effort de raisonnement, ou passer à un modèle sans raisonnement pour cette étape.

## Comment le prouver avant de le recommander
Banc de modèles : même modèle avec effort bas, comparer l'accord.

## Suite
Les modèles récents (gpt-5, o-series, Claude avec réflexion) rendent ce levier de plus en plus gros.
