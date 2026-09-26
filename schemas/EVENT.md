# Schéma d'événement v1 (D0.1)

`schemas/event.schema.json` décrit un appel LLM capturé par la passerelle. C'est le contrat
unique : la passerelle l'écrit (D1.2, D1.3), les règles le lisent (lot 2).

Fixtures : `fixtures/events.jsonl` (50 événements, une ligne = un événement) et
`fixtures/events.labels.json` (scénario → règles attendues ; `[]` = cas négatif).
Régénérer : `python3 fixtures/gen_events.py`. Vérifier : `pytest tests/test_event_schema.py`.

## Invariants

- **Jamais de clé** : pas d'en-tête d'autorisation, pas d'en-têtes du tout. `additionalProperties: false`
  partout, et un test le vérifie.
- Images : comptées (`n_images`), jamais stockées.
- `trace` est `{id: null, source: null}` tant que D1.4 n'a pas regroupé l'appel.
- `app_id` vient de l'en-tête `x-deadweight-app`, sinon `"default"`. Trace : `x-deadweight-trace`.
- Arguments d'outils toujours en chaîne JSON (format OpenAI).

## `provider` = format, `upstream` = destination

`provider` dit quel **format** de requête est utilisé, pas chez qui l'appel part. Le format
`openai` est parlé par Mistral, DeepSeek, Groq, Together, OpenRouter, Azure OpenAI, vLLM,
Ollama… `upstream` (optionnel) garde l'hôte réellement appelé, par exemple `api.mistral.ai`.
La passerelle le remplit toujours ; le chiffrage et le rapport s'en servent pour ne pas
confondre deux modèles de même nom chez deux hébergeurs.

## Normalisation par fournisseur

| Champ | OpenAI | Anthropic | Gemini |
|---|---|---|---|
| `request.system` | messages `role=system` concaténés | `system` | `systemInstruction.parts[].text` |
| `messages[].role` | `user` / `assistant` / `tool` | `user` / `assistant` ; bloc `tool_result` → `tool` | `user` / `model`→`assistant` ; `functionResponse` → `tool` |
| `messages[].content` | `content` (texte des parts) | blocs `text` concaténés | `parts[].text` concaténés |
| `tool_calls` | `tool_calls[].function` | blocs `tool_use` (`input` → chaîne JSON) | `parts[].functionCall` (`args` → chaîne JSON) |
| `request.tools` | `tools[].function` | `tools[]` (`input_schema` → `parameters`) | `tools[].functionDeclarations[]` |
| `finish_reason` | `stop`, `length`, `tool_calls`, `content_filter` | `end_turn`/`stop_sequence`→`stop`, `max_tokens`→`length`, `tool_use`→`tool_calls` | `STOP`→`stop`, `MAX_TOKENS`→`length`, `SAFETY`/`RECITATION`→`content_filter` |
| `usage.input_tokens` | `prompt_tokens` | `input_tokens` | `promptTokenCount` |
| `usage.output_tokens` | `completion_tokens` | `output_tokens` | `candidatesTokenCount` |
| `usage.cached_input_tokens` | `prompt_tokens_details.cached_tokens` | `cache_read_input_tokens` | `cachedContentTokenCount` |
| `usage.reasoning_tokens` | `completion_tokens_details.reasoning_tokens` | — (null) | `thoughtsTokenCount` |

La valeur brute reste dans `finish_reason_raw`. Un champ absent chez un fournisseur vaut `null`,
jamais une valeur par défaut inventée.
