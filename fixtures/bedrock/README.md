# Fixtures Bedrock : SYNTHÉTIQUES

Écrites à la main d'après la documentation AWS (model invocation logging), jamais capturées chez un client.
Compte 123456789012, ARN d'exemple. Régénérer : `python3 fixtures/bedrock/gen.py`.
Tarifs : `python3 fixtures/bedrock/pricing_from_aws.py <dossier>` (catalogue public AWS Price List, voir son en-tête).

Vérifié (sources dans le rapport de PR) : compteurs de cache sous `input` (`cacheReadInputTokenCount`,
`cacheWriteInputTokenCount`) ; `inferenceRegion` au premier niveau ; `inputBodyS3Path` pour les gros corps ;
`inputTokens` de Converse exclut le cache (doc AWS « Prompt caching »).

Toujours hypothèses, à confirmer sur un vrai journal : forme de `outputBodyJson` pour ConverseStream et
InvokeModelWithResponseStream (liste d'évènements ? chunks base64 ?), nom exact de `outputBodyS3Path`
(par symétrie avec `inputBodyS3Path`), compteurs de cache des modèles non Anthropic, et si `inputTokenCount`
de l'enregistrement exclut le cache comme `usage.inputTokens` du corps (le connecteur compte les écarts).
