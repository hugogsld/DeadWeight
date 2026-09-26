# Jeu de données réaliste (D0.3)

`v1/events.jsonl` : 1 554 appels sur 7 jours, 21 applications, 3 fournisseurs, au schéma
`v1/events.jsonl` : 1 436 appels sur 7 jours, 22 applications, 3 fournisseurs, au schéma
`schemas/event.schema.json`. `v1/labels.json` : pour chaque scénario, les règles attendues
(`[]` = ne doit rien déclencher), les événements concernés et le découpage réel en traces.

Régénérer : `python3 fixtures/dataset/gen_dataset.py` (déterministe, graine fixe).
Extension additive R13–R16 (#71) : nouveaux événements et apps uniquement ; les scénarios historiques restent inchangés.

| Scénario | App | Règles attendues | Ce qu'il teste |
|---|---|---|---|
| mail_triage | mail-triage | R1, R2 | 400 appels gpt-4o, 3 étiquettes bruitées (« Spam. », « SPAM ») : la normalisation est obligatoire |
| reviews_opus | reviews | R2, R1 | sentiment binaire sur claude-opus ; modèle possiblement absent du catalogue de prix |
| contract_bot | contract-bot | R3 | contrat renvoyé à chaque tour, +1 700 tokens/tour, réponses courtes |
| faq_bot | faq-bot | R4 | 5 prompts exacts × 12, zéro cache |
| daily_report_timestamp | daily-report | R4 | prompts identiques **sauf un horodatage** : positif après normalisation |
| sales_loop | sales-agent | R5 | 3 traces de 25 recherches quasi identiques, jamais de réponse ; 2 traces sans en-tête |
| order_chain | order-agent | R6 | 30 traces sans en-tête, toujours get_order → check_stock → send_email |
| ticket_summary | ticket-summary | — | sorties courtes mais uniques, petit modèle (négatif R1/R2) |
| eng_copilot | eng-copilot | — | vrai raisonnement gpt-4o en streaming : ne doit RIEN déclencher |
| support_chat | support-chat | — | fenêtre glissante, input constant (négatif R3) |
| kb_bot_cached | kb-bot | — | préfixe répété mais en cache (négatif R4) |
| translate | translate | — | même gabarit, contenus tous différents (négatif R4, R1) |
| research_agent | research-agent | — | outils qui progressent puis réponse finale (négatif R5, R6) |
| travel_agent | travel-agent | — | ordre des outils variable (négatif R6) |
| upstream_errors | * | — | 429/500/529 : capturés, exclus du coût |
| reasoning_trivia | trivia-bot | R7 | gpt-5, 1 800-3 000 tokens de raisonnement facturés pour une addition en une phrase |
| reasoning_used_well | analysis-bot | — | négatif R7 : raisonnement minoritaire, réponses visibles longues et variées |
| status_poll | status-poll | R8 | 6 appels identiques (requête ET réponse), en dessous du seuil de taille de R4 |
| status_poll_varies | status-poll-live | — | négatif R8 : même demande mais réponse différente à chaque fois |
| checkout_retries | checkout-bot | R9 | 15 réponses tronquées (finish_reason=length), facturées, relancées en moins de 30 s |
| notify_retries_unbilled | notify-bot | — | négatif R9 : échecs upstream jamais facturés, malgré des relances rapides |
| brainstorm_bot | brainstorm-bot | R12 | 40 appels sans max_tokens, médiane ~600 tokens, une réponse sur six dépasse 2 000 |
| capped_writer | capped-writer | — | négatif R12 : max_tokens fixé et sorties homogènes |

Les traces sans en-tête ont `trace = {id: null, source: null}` : la vérité est dans
`labels.json > traces`, c'est ce que D1.4 doit retrouver.

Correctif v1 (26/09, D2.1) : les réponses de `contract-bot` et `support-chat` étaient trop
répétitives (« Réponse 1. ») et faisaient déclencher R1 à tort. Elles sont maintenant uniques.

Extension v1 (26/09, R7/R8/R9/R12) : 8 scénarios ajoutés (8 nouvelles applications), toujours
dans `v1/` — les 1 332 événements et les 15 scénarios d'origine restent identiques (voir
`test_generation_is_deterministic` et le test de non-régression par règle). Nécessite un champ
`usage.reasoning_tokens` optionnel dans `fixtures/gen_events.py::event()` (défaut `None`,
rétrocompatible) pour simuler les modèles de raisonnement de `reasoning_trivia`.
## Extension #71

| App | Signal attendu | Contre-exemple |
|---|---|---|
| wide-tools | R13 : 9 outils sur 10 inutilisés, définitions volumineuses répétées | focused-tools : 8 outils utilisés |
| night-batch | R14 : 3 rafales de 10 appels à 02h UTC | day-burst : mêmes rafales à 14h UTC |
| image-titles | R15 : entrée élevée et titre court | image-analysis : réponse longue et différente |
| systematic-review | R16 : 6 relectures courtes après génération | useful-followup : approfondissements longs |
