# Rule packs for the SKB Reference Checker

The three official SKB guides are built into `skbref.html` and always apply:

* 1215757 — Angivande av referenser i publika rapporter
* 1469987 — Fördjupade skrivregler för publika rapporter
* 1715629 — Skrivhandboken

Everything beyond them is project-specific and lives in a rule pack: a JSON
file loaded from the **Rule packs** panel on the page. Packs are remembered in
the browser, several can be active at once, and the open document is
re-analysed whenever one is added, disabled or removed.

## Format

A pack is either a bare array of rules or an object with a name:

```json
{
  "name": "PSAR PSU",
  "description": "Terminology agreed for the PSAR PSU radionuclide transport report.",
  "rules": [
    { "pattern": "\\bflux(?:es)?\\b", "description": "Use release when activity release is meant." }
  ]
}
```

### Rule fields

| Field | Required | Meaning |
|---|---|---|
| `pattern` | yes | JavaScript regular expression source, as a JSON string. Backslashes are doubled. |
| `description` | yes in practice | What the writer should do. This is the text they will read, so write it as advice, not as a note to yourself. |
| `enabled` | no | `false` keeps a rule in the file without applying it. Default `true`. |
| `flags` | no | Regular-expression flags. Default `gu`. Add `i` for case-insensitive matching. |
| `language` | no | `"en"` or `"sv"` — only apply the rule to text Word marks as that language. |
| `severity` | no | `"review"` (a suggestion, the default) or `"warning"`. |

Rules never run on the reference list, because the titles of cited works must
be reproduced as published.

## Export

**Export active rules** writes the built-in terminology plus every loaded pack
to a single JSON file, which is a convenient way to start a new pack from what
is already in use.
