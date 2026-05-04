## Implementation Plan: Interactive Manual Workflow

Date: 2026-03-12

1. Add `--interactive` flag to `workflow-run`
2. Add helper functions in `cli/commands/dealflow.py` for:
   - multiline paste capture with `END`
   - interactive X-feed completion
   - interactive macro completion
   - interactive earnings/options completion
   - short stage renderers
3. Route `workflow-run --interactive --mode manual` through the interactive branch
4. Reuse existing persistence and validation helpers:
   - X-feed `generate_prompts`, `ingest_pass`, `get_readiness`
   - macro `_MACRO_PROMPT_TEMPLATE`, `_validate_macro_payload`, `_save_macro_cache`
   - earnings/options `_PROMPT_TEMPLATE`, `_validate_payload`, `save_earnings_options_scout`
5. Use direct `DealFlowPipeline.discover()` / `collect()` for scout and collector stages
6. Keep analyze / plan / execute / sync / learning on existing back-half semantics
7. Add focused CLI tests
8. Run focused verification
9. Update memory files
