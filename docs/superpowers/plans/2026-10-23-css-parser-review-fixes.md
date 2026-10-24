# CSS Parser Review Fixes

**Goal:** Replace the custom CSS tokenizer with tinycss2 in server-side style handling and update PR #1.

**Approved approach:** Parse CSS into structured nodes, inspect imports and local assets, copy permitted assets, rewrite references, and serialize. Keep `backend/build.py` dependency-free through an optional CSS validation callback. The user's approval of tinycss2 supersedes the original no-new-dependencies default for the server only.

## Constraints

- Keep the synchronous browser runtime unchanged.
- Preserve current artifact file and access rules, transaction rollback, and CSS comments/sample strings.
- Bound CSS bytes, tokens, nesting and asset counts before expensive work. Do not fetch remote imports or assets.
- Handle escaped identifiers, quoted/unquoted `url()`, string candidates in `image-set()`, queries and fragments. Reject imports and malformed CSS with actionable errors.
- All server builds use parser-backed validation. Standalone builder validation remains dependency-free and keeps existing simple CSS image checks.
- Fix the related native-dialog cancellation review finding without changing ordinary dialog behavior.

## Tasks

- [x] Add failing CSS parser, resource-copy, bounded-input and callback integration regressions.
- [x] Add tinycss2 (and type stubs if needed), create `backend/styles.py`, and remove the custom tokenizer. Provide parser-backed validation and rewriting with explicit resource policy.
- [x] Connect presets and all server build entry points to the validator. Keep the builder's optional callback free of server imports.
- [x] Prevent native Escape dismissal while a library operation is pending.
- [x] Run focused regressions, `make format`, `make lint`, `make test`, and the frontend build. Review the final change and prepare the fixes for PR #1.

## Verification

- Parser regressions reproduce the former malformed-comment slowdown in a bounded subprocess and exercise escaped identifiers, imports, responsive images, path containment, input limits and resource relocation.
- Review found that serializing escaped sample text could produce a literal closing style tag. String and URL nodes now retain HTML-safe CSS escaping; regressions verify the decoded values and media range operators are preserved, including a saved-style application.
- The builder runs under Python `-S`, without third-party site packages. The server supplies its parser-backed validator at each build entry point.
- `make format`, `make lint`, and `pnpm -C frontend build` pass. Lint reports the existing 17 CSS specificity warnings.
- `make test`: 319 passed, 1 failed. The existing `test_native_telemetry_reaches_logfire` failure was previously reproduced at unchanged base commit `c3d4359`; this environment does not emit the expected native Monty spans.
- The updated lockfile passes `uv lock --check --offline` with the Docker image's pinned uv 0.12.16.
