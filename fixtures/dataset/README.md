# Jeu de données réaliste (D0.3)

`v1/events.jsonl` : 1 332 appels sur 7 jours, 13 applications, 3 fournisseurs, au schéma
`schemas/event.schema.json`. `v1/labels.json` : pour chaque scénario, les règles attendues
(`[]` = ne doit rien déclencher), les événements concernés et le découpage réel en traces.

Régénérer : `python3 fixtures/dataset/gen_dataset.py` (déterministe, graine fixe).
Une nouvelle version = un nouveau dossier `v2/`, on ne réécrit jamais `v1`.

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

Les traces sans en-tête ont `trace = {id: null, source: null}` : la vérité est dans
`labels.json > traces`, c'est ce que D1.4 doit retrouver.

Correctif v1 (26/09, D2.1) : les réponses de `contract-bot` et `support-chat` étaient trop
répétitives (« Réponse 1. ») et faisaient déclencher R1 à tort. Elles sont maintenant uniques.
