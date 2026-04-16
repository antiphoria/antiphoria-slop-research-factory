# Prompt Changelog

All prompt modifications are recorded here with date,
file(s) changed, motivation, and summary.

Reference: D-3 §8.2 — Prompt Modification Procedure.

---

## v0.1 — 2026-04-15

**Initial release.** All prompts transcribed verbatim from
D-3 (Prompt Engineering Dossier v0.1).

### Files created

| File | D-3 Section | Description |
|------|-------------|-------------|
| `generator/system_v0.1.txt` | §3.1 | Generator system prompt |
| `generator/user_template_v0.1.txt` | §3.2 | Generator user message template |
| `verifier/system_v0.1.txt` | §4.1 | Verifier system prompt |
| `verifier/user_template_v0.1.txt` | §4.2 | Verifier user message template |
| `reviser/system_v0.1.txt` | §5.1 | Reviser system prompt |
| `reviser/user_template_v0.1.txt` | §5.2 | Reviser user message template |
| `citation_extractor/system_v0.1.txt` | §6.1 | Citation extractor system prompt |
| `citation_extractor/user_template_v0.1.txt` | §6.2 | Citation extractor user message |

### Design decisions

- **No persona inflation** (D-3 §2.2 Rule 1, D-3 §12 row 1).
- **Critique before verdict** ordering enforced in verifier

  prompt (D-3 §2.2 Rule 2; Feng et al. 2026a Appendix A).
- **Explicit uncertainty framing** in all prompts

  (D-3 §2.2 Rule 3).
- **Verbatim brief injection** via XML tags

  (D-3 §2.2 Rule 4).
- **Think-token isolation**: prompts never reference or

  control the `<think>` trace (D-3 §2.2 Rule 6).
- **Closed-book Verifier**: does not receive Generator's

  think trace (D-0 §6.3; D-3 §12 row 4).
- Generator and Reviser instruct `NO_OUTPUT` as a valid

  terminal output (D-3 §3.3, §7; Feng et al. 2026b §2.2).
- Verifier prompt injects `VerifierOutput.model_json_schema()`

  at runtime (D-3 §4.3) using `instructor.Mode.JSON`.
- User templates use a custom directive syntax (`{if}`,

  `{/if}`, `{for}`, `{/for}`) rendered by the template
  engine at runtime (implementation: Step 6–8).