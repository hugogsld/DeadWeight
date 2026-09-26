# 8. Un agent qui tourne en rond

| | |
|---|---|
| Famille | Forme des briques d'IA |
| Gain argent | Chaque tour en trop |
| Gain latence | Forte |
| Comment prouver | Traces |
| Données nécessaires | Événements regroupés en traces |
| État | Fait (R5) |
| Règle | R5 unbounded_loop |

## Le signal
Le même outil appelé encore et encore avec des arguments quasi identiques.

## Comment le détecter
Répétitions d'actions dans une trace (arguments comparés clé par clé).

## Ce qu'on propose au client
Plafond d'étapes, détection de répétition, sortie de secours.

## Comment le prouver avant de le recommander
Traces montrées au client ; coût des tours en trop.

## Suite
—
