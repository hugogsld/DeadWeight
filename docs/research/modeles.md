# Catalogue modèles/stack — recherche pour Deadweight (audit LLM)
Date de la recherche : 26 septembre 2026. Sources primaires citées quand disponibles ; sinon agrégateurs (à considérer comme indicatifs, non garantis).

⚠️ Avertissement méthodologique : les pages officielles OpenAI/Anthropic/Google/Mistral ont été récupérées directement (WebFetch) et font foi. Les chiffres Groq/Cerebras/Together/Scaleway/OVHcloud proviennent en partie d'agrégateurs SEO (cloudzero, aipricing.guru, pricepertoken, etc.) — plausibles mais non vérifiés page par page. Les benchmarks Artificial Analysis (TTFT, tok/s, intelligence index) sont partiels : accès direct au site bloqué, données reconstituées via extraits de recherche, à re-vérifier avant publication finale du rapport client.

---

## 1. Tableau des ~20 LLMs pertinents pour recommandation de remplacement

| Modèle | Fournisseur | Origine société | Input $/M | Output $/M | Cached input $/M | Contexte | Hébergement EU / résidence données | Compat. API OpenAI | TTFT | Tok/s sortie | Indice qualité (Artificial Analysis) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| GPT-5-nano | OpenAI | US | $0.05 | $0.40 | $0.005 | 400K (std) | Oui — région EU dispo (`eu.api.openai.com`) depuis 2025, extension GPU inférence UE janv. 2026 | Native | non trouvé (à vérifier AA) | non trouvé | non trouvé |
| GPT-5-mini | OpenAI | US | $0.25 | $2.00 | $0.025 | 400K | Oui (EU data residency) | Native | ~72–79s en config "high effort"(AA, forte variance selon reasoning effort), 0.5–2s en mode direct | ~100 tok/s (config high) | non trouvé (indice précis AA) |
| GPT-5 | OpenAI | US | $1.25 | $10.00 | $0.125 | 400K | Oui (EU data residency) | Native | non trouvé | non trouvé | non trouvé |
| GPT-5.4-mini | OpenAI | US | $0.75 | $4.50 | $0.075 | non trouvé | Oui | Native | TTFT ~7.6s (xhigh reasoning, AA) | non trouvé | non trouvé |
| GPT-5.6-Luna | OpenAI | US | $0.20 | $1.20 | $0.02 | non trouvé | Oui | Native | non trouvé | non trouvé | non trouvé |
| GPT-5.6-Sol | OpenAI | US | $4.00 | $20.00 | $0.40 | non trouvé | Oui | Native | non trouvé | non trouvé | ~58.9% (AA Intelligence Index, source secondaire non vérifiée) |
| GPT-6-Astra (flagship le + cher) | OpenAI | US | $10.00 | $50.00 | $1.00 | non trouvé | Oui | Native | non trouvé | non trouvé | non trouvé |
| Claude Haiku 4.5 | Anthropic | US | $1.00 | $5.00 | read $0.10 / write $1.25 | jusqu'à 1M (variable) | **Non** en direct (API 100% US) ; EU possible via AWS Bedrock (Francfort/Irlande/Paris/Stockholm) ou Vertex AI | Compatible via SDK Anthropic (pas OpenAI-native, wrappers existent) | 0.77s (non-reasoning, AA) | 84.5 tok/s (non-reasoning) | non trouvé |
| Claude Sonnet 5 | Anthropic | US | $2.00 | $10.00 | read $0.20 / write $2.50 | jusqu'à 1M | Non en direct API ; via Bedrock/Vertex EU oui | Non native | non trouvé | non trouvé | non trouvé |
| Claude Opus 5.5 | Anthropic | US | $4.00 | $20.00 | read $0.20 / write $5.00 | jusqu'à 1M | Non en direct API ; via Bedrock/Vertex EU oui | Non native | non trouvé | non trouvé | ~57.6% (AA, source secondaire) |
| Gemini 2.5 Flash-Lite | Google | US | $0.10 | $0.40 | cache $0.01 | non trouvé | Oui — europe-west1/4, europe-north1 (résidence + calcul UE) | Non native (API Gemini propre, proxys compatibles existent) | non trouvé | non trouvé | non trouvé |
| Gemini 3.5 Flash-Lite | Google | US | $0.30 | $2.50 | cache $0.03 | non trouvé | Oui (EU multi-région + Francfort/Londres pour 3.5 Flash) | Non native | non trouvé | non trouvé | non trouvé |
| Gemini 3.8 Flash | Google | US | $0.75 (promo jusqu'au 31/12/26, puis $1.50) | $3.75 (puis $7.50) | cache $0.075 (puis $0.15) | non trouvé | Oui | Non native | non trouvé | non trouvé | non trouvé |
| Gemini 3.1 Pro | Google | US | $2.00 (>200K: $4.00) | $12.00 (>200K: $18.00) | non trouvé | >200K seuil tarifaire | Oui | Non native | 0.49s (variante 2.5 Flash non-reasoning, AA) | non trouvé | "le moins cher du top 10" selon AA (source secondaire) |
| Mistral Small 4 | Mistral AI | **France (UE)** | $0.15 | $0.60 | ~10% du prix input (mécanisme cache) | non trouvé | Oui — natif UE, + Scaleway/OVHcloud pour hébergement souverain FR | Compatible API OpenAI (endpoint compatible) | non trouvé | non trouvé | non trouvé |
| Ministral 8B | Mistral AI | France (UE) | $0.15 | $0.15 | non trouvé | non trouvé | Oui | Compatible | non trouvé | non trouvé | non trouvé |
| Ministral 3B | Mistral AI | France (UE) | $0.10 | $0.10 | non trouvé | non trouvé | Oui | Compatible | non trouvé | non trouvé | non trouvé |
| Mistral Medium 3.5 | Mistral AI | France (UE) | $1.50 | $7.50 | ~10% input | non trouvé | Oui | Compatible | non trouvé | non trouvé | non trouvé |
| Mistral Large 3 | Mistral AI | France (UE) | $0.50 | $1.50 | ~10% input | non trouvé | Oui | Compatible | non trouvé | non trouvé | non trouvé |
| Llama 3.3 70B (via Groq) | Meta (poids ouverts) / hébergé par Groq (US) | US (Meta) / hébergeur US (Groq) | ~$0.59 | ~$0.79 | non trouvé (Groq ne publie pas de cache documenté) | non trouvé | Non confirmé — pas de région UE Groq identifiée (à vérifier) | Compatible (API OpenAI-like chez Groq) | non trouvé | 280–1000 tok/s (LPU, très rapide) | non trouvé |
| Llama 3.3 70B (via Cerebras) | Meta / Cerebras (US) | US | non trouvé précis (plage $0.60–$3.90/M citée par agrégateurs) | idem | non trouvé | non trouvé | Non confirmé UE | Compatible | TTFT <200ms (Llama 4 70B) | 1800+ tok/s (Llama 3.3 70B), 750+ tok/s (Llama 4 70B) | non trouvé |
| Qwen3.6-27B (via Groq) | Alibaba (Chine) / Groq (US) | **Chine** (poids) / US (hébergeur) | $0.60 | $3.00 | non trouvé | non trouvé | Non confirmé UE | Compatible | non trouvé | très rapide (LPU) | non trouvé |
| DeepSeek V3 (via Together AI) | DeepSeek (Chine) / Together (US) | **Chine** (poids) / US (hébergeur) | ~$1.25 combiné (agrégateur, à vérifier) | idem | non trouvé | non trouvé | Non confirmé UE | Compatible | non trouvé | non trouvé | non trouvé |
| Llama 3.3 70B (via Scaleway, FR) | Meta / **Scaleway (France)** | US (poids) / **France** (hébergeur souverain, SecNumCloud) | €0.90 | €0.90 | non trouvé | non trouvé | **Oui — 100% UE, datacenters français** | Compatible OpenAI-like | non trouvé | non trouvé | non trouvé |
| Mistral Medium 3.5 (via Scaleway, FR) | Mistral / Scaleway | France / France | €1.50 | €7.50 | non trouvé | non trouvé | Oui, souverain FR | Compatible | non trouvé | non trouvé | non trouvé |
| DeepSeek V4 Flash (via Scaleway, FR) | DeepSeek (Chine, poids) / Scaleway (FR, hébergeur) | Chine (poids) / **France** (hébergement souverain) | €0.40 | €0.80 | non trouvé | non trouvé | Oui — hébergé en France malgré poids chinois (souveraineté d'hébergement, pas d'origine du modèle) | Compatible | non trouvé | non trouvé | non trouvé |
| Llama/Mistral/Qwen (via OVHcloud AI Endpoints, FR) | Divers / **OVHcloud (France)** | Mixte (poids) / **France** (hébergeur SecNumCloud) | de $0.04 à $0.91/M selon modèle (plage agrégée, non vérifiée modèle par modèle) | idem | non trouvé | non trouvé | Oui — 100% UE | Compatible OpenAI-like | non trouvé | non trouvé | non trouvé |

**Point clé souveraineté** : OpenAI propose une résidence de données UE native (`eu.api.openai.com`, depuis 2025-2026) — traitement ET stockage en Europe pour comptes éligibles. **Anthropic ne propose PAS de résidence UE en API directe** : tout appel à `api.anthropic.com` transite et est traité aux US, quel que soit le siège du client — seule option UE = passer par AWS Bedrock (Francfort/Irlande/Paris/Stockholm) ou Google Vertex AI. Google Gemini a une résidence UE mature (europe-west1 Belgique, europe-west4 Pays-Bas, europe-north1 Finlande, europe-west3 Francfort). Mistral est nativement français/UE. Scaleway et OVHcloud sont les seules options 100% souveraines France/UE (y compris pour héberger des poids ouverts non-européens comme Llama ou DeepSeek : le modèle peut être "étranger" mais l'exécution reste en France).

---

## 2. Alternatives non-LLM pour classification/extraction

| Approche | Coût typique | Latence typique | Remarques |
|---|---|---|---|
| Règles / regex | ~0 $ (coût de calcul serveur négligeable) | <1ms | Pertinent quand la tâche du LLM auditée est une classification simple à catégories fixes/mots-clés — remplaçable à 100% |
| Classifieur fine-tuné léger (ex. DistilBERT, petit sklearn/XGBoost sur embeddings) | Coût d'entraînement ponctuel + inférence ~négligeable ($ fraction de cent par 1000 requêtes en CPU/GPU partagé) | 1–20ms | Nécessite un jeu d'exemples labellisés ; ROI fort si le LLM audité tourne à haut volume juste pour classifier |
| Embeddings + kNN / recherche de similarité | Voir tableau ci-dessous ($0.02–$0.13/M tokens en une fois, puis quasi gratuit en lookup) | ~10–100ms (appel API embedding) + quelques ms pour le kNN | Bon compromis pour classification/routing/déduplication sans réentraîner un modèle |

### Prix embeddings (par million de tokens, sources officielles / agrégateurs récents)
| Modèle | Fournisseur | Prix $/M tokens | Dimensions | Contexte max |
|---|---|---|---|---|
| text-embedding-3-small | OpenAI | $0.02 | 1536 | non trouvé (dans le résultat) |
| text-embedding-3-large | OpenAI | $0.13 | 3072 | non trouvé |
| Mistral Embed | Mistral AI (FR/UE) | $0.10 | 1024 | 8 000 tokens |
| Voyage-4-lite | Voyage AI (racheté par MongoDB, US) | $0.02 | non trouvé | non trouvé |
| Cohere Embed v4 | Cohere (Canada) | $0.12 | 1536 | 128 000 tokens |

So what : pour toute "classification" détectée dans l'audit Deadweight, la recommandation par défaut doit être — dans l'ordre de préférence — règles > classifieur fine-tuné > embeddings+kNN > petit LLM (nano/mini/Flash-Lite/Ministral), et seulement en dernier recours un LLM taille "flagship".

---

## 3. Règles de prompt caching par fournisseur (pour la règle `no_cache` de l'audit)

| Fournisseur | Seuil minimum | Remise cache hit | Coût cache write | TTL | Activation |
|---|---|---|---|---|---|
| OpenAI (GPT-5.6+) | 1 024 tokens | 90% (0.1× prix input) | 1.25× prix input | 30 min (`prompt_cache_options.ttl`, seule valeur supportée : "30m") | Automatique (implicite) + option explicite via `prompt_cache_breakpoint` |
| OpenAI (modèles antérieurs à 5.6) | 1 024 tokens (probable, à confirmer modèle par modèle) | variable selon modèle, ~50 à 90% selon la période 2026 | non applicable (pas de write cost documenté) | `in_memory` (5–10 min, jusqu'à 1h) ou `24h` | Automatique |
| Anthropic (Claude) | non trouvé de seuil minimum précis en tokens (à vérifier docs Claude) | 90% (0.1× prix input) sur cache hit | 1.25× (TTL 5 min) ou 2.0× (TTL 1h) prix input | 5 min par défaut (régression depuis mars 2026, était 1h avant) ; option 1h disponible | Nécessite déclaration explicite des breakpoints de cache (pas automatique comme OpenAI) |
| Google Gemini | Implicite : 1024 tokens (Flash) / 4096 tokens (Pro) — anciens seuils 2.5 : 2048 tokens Flash/Pro | Coût cache ~10% du prix input standard (tarif "cache" publié par modèle) | non trouvé de surcoût "write" distinct type Anthropic | Défaut 1h (explicite), configurable ; implicite géré automatiquement par Google | Implicite activé par défaut sur Gemini 3.x et 2.5 ; économies réelles documentées surtout sur 2.5 |
| Mistral | ~64 tokens (taille de bloc de cache — en dessous, pas de cache hit possible) | 90% (cache à 10% du prix input) | non trouvé de surcoût write | TTL non confirmé officiellement pour Mistral lui-même (5 min mentionné dans un contexte AWS Bedrock, à vérifier sur docs.mistral.ai) | Nécessite `prompt_cache_key` stable (conversation/session/workflow id) pour maximiser les hits — pas 100% automatique |

So what pour la règle `no_cache` : le seuil de déclenchement pertinent tourne autour de 1000-2000 tokens de préfixe stable selon le fournisseur (Mistral est plus permissif à 64 tokens). Un appel avec préfixe système/contexte long et réutilisé qui n'active pas le cache (absence de `prompt_cache_key`/breakpoint chez Anthropic ou Mistral) est un vrai signal de gaspillage — l'audit peut chiffrer l'économie potentielle à ~90% du coût input pour la portion répétée.

---

## Sources citées

- OpenAI pricing officiel : https://developers.openai.com/api/docs/pricing (WebFetch direct, 26/09/2026)
- OpenAI prompt caching : https://developers.openai.com/api/docs/guides/prompt-caching
- OpenAI EU data residency : https://openai.com/index/introducing-data-residency-in-europe/ ; https://openai.com/index/expanding-data-residency-access-to-business-customers-worldwide/
- Anthropic pricing officiel : https://claude.com/pricing#api (WebFetch direct, 26/09/2026)
- Anthropic caching TTL regression : https://github.com/anthropics/claude-code/issues/46829 ; https://brandonwie.dev/posts/anthropic-prompt-cache-ttl
- Anthropic absence résidence UE : https://amitkoth.com/claude-regulated-finance-eu-residency/ ; https://sonomos.ai/blog/claude-eu-data-residency-2026/
- Google Gemini pricing officiel : https://ai.google.dev/gemini-api/docs/pricing (WebFetch direct)
- Google Gemini context caching : https://ai.google.dev/gemini-api/docs/caching
- Google Vertex AI EU régions : https://optinest.de/ai-infrastructure/sovereignty/residency-guarantees/vertex-ai-data-residency-gdpr-rules-and-eu
- Mistral pricing : https://mistral.ai/pricing/ (WebFetch, incomplet — seul un exemple de prix confirmé sur la page) + agrégateur cloudzero.com/blog/mistral-api-pricing
- Mistral prompt caching : https://docs.mistral.ai/studio-api/conversations/advanced/prompt-caching
- Groq pricing/vitesse : https://www.cloudzero.com/blog/groq-pricing/ ; https://www.eesel.ai/blog/groq-pricing (non vérifié page officielle Groq)
- Cerebras pricing/vitesse : https://www.cerebras.ai/inference ; https://deploybase.ai/articles/cerebras-inference-pricing
- Together AI pricing : https://www.aipricing.guru/together-pricing/ ; https://lmmarketcap.com/together-ai-pricing (agrégateurs, non vérifié page officielle)
- Scaleway pricing : https://www.scaleway.com/en/generative-apis/ (via agrégateur computecomparison.com, non vérifié page officielle exhaustive)
- OVHcloud pricing : https://www.ovhcloud.com/en/public-cloud/ai-endpoints/ (via futureagi.com, plage agrégée non vérifiée modèle par modèle)
- Embeddings pricing : https://www.buildmvpfast.com/blog/best-embedding-model-comparison-voyage-openai-cohere-2026 ; https://tokencost.app/embeddings
- Artificial Analysis (TTFT, tok/s, intelligence index) : https://artificialanalysis.ai/models ; https://artificialanalysis.ai/leaderboards/models — **accès direct bloqué pendant cette recherche, données reconstituées via extraits Google indexés, à revalider avant publication finale**
