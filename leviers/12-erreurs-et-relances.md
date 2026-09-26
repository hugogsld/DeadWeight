# 12. Des erreurs et relances payées

| | |
|---|---|
| Famille | Usage des LLM |
| Gain argent | Variable, parfois énorme |
| Gain latence | Forte (attentes, relances) |
| Comment prouver | Calcul exact |
| Données nécessaires | Événements |
| État | En cours (R9) |
| Règle | R9 paid_errors |

## Le signal
Taux d'erreur, relances en rafale, sorties coupées relancées.

## Comment le détecter
Statut, erreur, fin de réponse ; même requête relancée en quelques secondes.

## Ce qu'on propose au client
Attente progressive, plafond de relances, sortie structurée pour éviter les JSON invalides.

## Comment le prouver avant de le recommander
Coût réellement facturé des appels en échec.

## Suite
—
