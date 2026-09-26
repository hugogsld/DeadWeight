# 2. Un modèle trop gros pour la tâche

| | |
|---|---|
| Famille | Usage des LLM |
| Gain argent | ÷10 à ÷20 (gpt-4o → mini) |
| Gain latence | Premier mot plus rapide |
| Comment prouver | Banc de modèles |
| Données nécessaires | Événements + catalogue |
| État | Détection faite (R2), banc en cours, M1/M2 (Hugo) |
| Règle | R2 oversized_model |

## Le signal
Un modèle haut de gamme produit des sorties courtes ou simples.

## Comment le détecter
Prix du modèle au catalogue, longueur et diversité des sorties, famille de la tâche.

## Ce qu'on propose au client
Proposer trois options : la moins chère, le meilleur compromis, la souveraine. Jamais un modèle trop faible : garde-fou qualité.

## Comment le prouver avant de le recommander
**Banc de modèles** : rejouer un échantillon du vrai trafic sur les candidats (petits, locaux via Ollama, en ligne via OpenRouter), mesurer l'accord, la latence, le coût. Rien n'est recommandé sans ce test.

## Suite
Bibliothèque de candidats versionnée ; indice de qualité (Artificial Analysis) pour présélectionner.
