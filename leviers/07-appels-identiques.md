# 7. Les mêmes appels payés plusieurs fois

| | |
|---|---|
| Famille | Usage des LLM |
| Gain argent | 100 % de chaque doublon |
| Gain latence | Réponse immédiate si mise en cache |
| Comment prouver | Calcul exact |
| Données nécessaires | Événements |
| État | En cours (R8) |
| Règle | R8 duplicate_calls |

## Le signal
Même modèle, même requête, même réponse, payés à nouveau.

## Comment le détecter
Empreinte de la requête normalisée ; fenêtre de temps.

## Ce qu'on propose au client
Mettre les réponses en cache avec une durée de vie adaptée.

## Comment le prouver avant de le recommander
Nombre de doublons × coût mesuré.

## Suite
Cache sémantique (requêtes proches) plus tard, avec preuve par rejeu.
