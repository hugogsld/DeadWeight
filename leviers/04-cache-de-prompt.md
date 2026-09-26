# 4. Le cache de prompt non utilisé

| | |
|---|---|
| Famille | Usage des LLM |
| Gain argent | Jusqu'à 90 % du coût d'entrée répété |
| Gain latence | Premier mot plus rapide |
| Comment prouver | Calcul exact |
| Données nécessaires | Événements + prix du cache |
| État | Fait (R4) ; prix du cache branchés (OpenRouter) |
| Règle | R4 no_cache |

## Le signal
Un long préfixe (instructions, documents) identique d'un appel à l'autre, sans jetons en cache.

## Comment le détecter
Préfixe commun des requêtes d'un même gabarit, cached_input_tokens nuls.

## Ce qu'on propose au client
Ordonner le prompt (fixe d'abord, variable ensuite) ; activer le cache là où il est explicite (Anthropic, Mistral) ; clé de cache stable.

## Comment le prouver avant de le recommander
Le gain se calcule : jetons répétés × (prix normal − prix du cache).

## Suite
Règles propres à chaque fournisseur : seuils (1 024 jetons OpenAI, 64 Mistral), durée de vie.
