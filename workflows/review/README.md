# Review Workflow

This workflow is separated from thesis writing and DOCX export.

It is inspired by the structure of `clolckliang/aigc-detector-toolkit`: keep input extraction, independent review dimensions, aggregation, and reports as separate concepts instead of hiding everything in one prompt.

Current lightweight flow:

```bash
bash workflows/review/review_thesis.sh
```

The script checks:

- assembled thesis input from `configs/default.yaml`
- review prompt path
- target report path

Recommended review dimensions are configured in `configs/default.yaml` with weights and dimension-specific prompts:

- structure
- formatting
- cross_reference
- academic_style
- evidence_and_data

Future extension:

```text
review/
  extractors/       split Markdown/DOCX into reviewable units
  engines/          independent review engines or prompts
  reporters/        Markdown/JSON/HTML reports
  review_thesis.sh  workflow entrypoint
```

The useful idea from multi-engine projects such as `aigc-detector-toolkit` is not that every workflow must use the same detector, but that independent engines should produce separate evidence before aggregation. For this thesis workflow, the natural equivalent is:

```text
structure checker
format checker
cross-reference checker
academic-style checker
evidence/data checker
        -> weighted review report
        -> optional conservative optimizer
```

For now, the AI review prompt remains `workflows/review/review_prompt.md`, and the recommended output is `output/review_results.md`.
