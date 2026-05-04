# Aeternus DeepWiki

This site is the visual documentation layer for the Aeternus platform.

## Canonical Sources

- Architecture article source: `/Users/aeternusholdings/Documents/AeternusAgentsAG/memory/DeepWiki_System_Architecture.md`
- Memory control plane:
  - `/Users/aeternusholdings/Documents/AeternusAgentsAG/memory/Prompt.md`
  - `/Users/aeternusholdings/Documents/AeternusAgentsAG/memory/Plans.md`
  - `/Users/aeternusholdings/Documents/AeternusAgentsAG/memory/Architecture.md`
  - `/Users/aeternusholdings/Documents/AeternusAgentsAG/memory/Documentation.md`

## How To Run

```bash
cd /Users/aeternusholdings/Documents/AeternusAgentsAG
./.venv/bin/pip install -r requirements-docs.txt
./.venv/bin/mkdocs serve
```

Then open `http://127.0.0.1:8000`.

## Build Static Site

```bash
cd /Users/aeternusholdings/Documents/AeternusAgentsAG
./.venv/bin/mkdocs build
```

Generated static site output is written to `/Users/aeternusholdings/Documents/AeternusAgentsAG/site/`.
