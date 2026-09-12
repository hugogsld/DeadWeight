# Contrats Deadweight - figes a 12:15

Quatre fichiers circulent entre les blocs. Personne ne renegocie ces formats.

    A/collector  ->  fixtures/profile.json  ->  A/detector
    A/detector   ->  fixtures/finding.json  ->  B/patcher
    B/patcher    ->  fixtures/patch.json    ->  B/prover
    B/prover     ->  fixtures/proof.json    ->  C/habitat

`schemas/*.schema.json` sont les JSON Schema correspondants. Celui de `patch`
est directement utilisable en structured output OpenAI.

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
