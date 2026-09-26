# Contrats Deadweight - figes a 12:15

Quatre fichiers circulent entre les blocs du prototype hackathon. Personne ne
renegocie ces formats.

    A/collector  ->  fixtures/profile.json  ->  A/detector
    A/detector   ->  fixtures/finding.json  ->  B/patcher
    B/patcher    ->  fixtures/patch.json    ->  B/prover
    B/prover     ->  fixtures/proof.json    ->  C/habitat

`schemas/*.schema.json` sont les JSON Schema correspondants. Celui de `patch`
est directement utilisable en structured output OpenAI. Le `finding` de ce
pipeline (workflow n8n) a son propre schema : `schemas/finding.n8n.schema.json`
(voir plus bas, deux schemas `finding` coexistent).

## Deux formats "finding" : ne pas les confondre

Il y a deux pipelines distincts, chacun avec son propre contrat `finding` :

| Schema | Producteur | Consommateurs | Cle | Requiert |
| --- | --- | --- | --- | --- |
| `schemas/finding.n8n.schema.json` | `detector/scan.py` (prototype n8n) | `patcher/`, `prover/`, `habitat/` | `workflow_id` + `node_id` | `proposed_action`, `severity` in `cut/trim/keep` |
| `schemas/finding.schema.json` | `rules/*.detect(events)` (les six regles, Lot 2) | `report/audit.py` | `app_id` + `model` + `template` | `event_ids`, `proven`, `evidence`, `severity` in `cut/trim/candidate` |

Le second n'est PAS une evolution du premier : les deux pipelines tournent en
parallele sur des donnees differentes (workflows n8n vs evenements LLM captes
par la passerelle). `rule` reste le seul champ partage par les deux formats,
avec les memes six codes (`low_entropy_output`, `oversized_model`,
`raw_context`, `no_cache`, `unbounded_loop`, `agent_where_chain`) — seules les
quatre premieres regles sont implementees a ce jour (`rules/`), les deux
dernieres sont prevues par D2.4 (`ROADMAP.md`).

`tests/test_finding_schema.py` fait tourner les six regles de `rules/` sur
`fixtures/dataset/v1/events.jsonl` (decouverte automatique, comme
`report/audit.py`) et valide chaque finding produit contre
`schemas/finding.schema.json`. Il verifie aussi que `fixtures/finding.json`
(exemple du prototype) ne matche PAS ce nouveau schema, et matche toujours
`schemas/finding.n8n.schema.json`.

## Ce que chacun lit / ecrit

| Bloc | Lit | Ecrit |
| --- | --- | --- |
| collector (A) | API n8n | profile.json |
| detector (A) | profile.json | finding.json |
| patcher (B) | finding.json + workflow n8n original | patch.json |
| prover (B) | patch.json + executions historiques | proof.json |
| habitat (C) | finding.json + proof.json | Slack + POST n8n |

## Piege connu

`POST /api/v1/workflows` refuse tout champ en dehors de
`name`, `nodes`, `connections`, `settings`. Un `id` ou un `active` qui traine
renvoie `request/body must NOT have additional properties`.
`patcher/validate_reimport.py` nettoie et teste ca.
