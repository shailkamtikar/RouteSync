# ADR 0004: Assistant model

**Status:** accepted

## Decision
- RouteSync Companion uses Gemini through the `google-genai` SDK, behind an `LLMProvider` interface (`apps/api/app/providers/llm`). A scripted fake model is used in automated tests, so tests never spend quota.
- The model is called only from the FastAPI backend with a server-side key (`GEMINI_API_KEY`). The key never reaches the browser.
- The model id comes from `GEMINI_MODEL`. The project uses `gemini-3.5-flash-lite`.
- The model can only reach a fixed set of read-only, journey-bound tools. There is no general database or HTTP tool.

## Verified against the live service (November 2026)
| Check | Result |
|---|---|
| `gemini-3.5-flash-lite` exists | Yes; supports `generateContent` and tool calling; input limit 1,048,576 tokens |
| Plain reply | Works |
| Function call | Works; every function-call part carries a `thought_signature` that must be sent back unchanged on the next turn, or the API answers HTTP 400 |
| Tool result turn | Works once the signature is echoed |

## Quota
Google does not publish fixed per-model free-tier limits in its documentation; the real limits for this key are shown in Google AI Studio. The backend therefore treats quota as scarce: compact prompts, deterministic backend calculations, per-link and per-address throttling, output token caps, and a graceful fallback message when the quota is exhausted.

## Failure handling
| Situation | Behaviour |
|---|---|
| 429 or quota exhausted | `LLMQuotaExceeded`: the page shows a fallback message; tracking keeps working |
| Timeout or 5xx | `LLMUnavailable`: fallback message |
| Content blocked by the provider | `LLMBlocked`: a polite refusal |
| Key not configured | The assistant is disabled; everything else works |
