# Templates and Styles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add a private reusable library, including template creation from descriptions using a bundled OpenArtifact skill.

**Architecture:** Represent library entries as private artifact snapshots with `preset_kind` metadata. A focused presets module copies and validates files through the existing edit protocol. Extend the JSON API, MCP tools and React editor without changing the dependency-free builder or synchronous runtime.

**Tech Stack:** Python, FastAPI, Postgres, React, TypeScript, existing pydantic-ai editing agent.

**Spec:** `docs/superpowers/specs/2026-10-23-templates-and-styles-design.md`

## Global Constraints

- Add no package dependencies; use pnpm and uv.
- All artifact changes go through `workspace.edit()`.
- Every template instance is independent, and library lookup is scoped to the caller's workspace.
- Preserve artifact type and content when applying styles; copy local assets without overwriting existing files.
- Never copy git metadata, derived output, symlinks or paths outside the source artifact.
- Use plain hyphens in source and documentation.

## Review Focus

- Custom markdown/styles paths and context keys named like top-level settings must survive copying and editing.
- CSS font/image URLs, fragments and query strings must survive namespacing; unsupported imports fail clearly.
- Invalid template or style inputs must leave no partially created library entry or modified target.
- Public or organization-visible entries must not bypass the personal library ownership check.
- Template-specific instructions must reach the configured agent, including a scripted model test.

### Task 1: Versioned library snapshots and styles

**Files:** Create `backend/presets.py`, `backend/migrations/0005_presets.sql`, `tests/test_presets.py`; modify `backend/workspace.py`.

**Interfaces:** `Artifact.preset_kind` and `NewArtifact.preset_kind` are nullable strings. `presets.save(source, workspace_id, name, kind)` creates a private snapshot. `presets.create(workspace_id, name, type, css=None, theme='light')` creates a style preview or starter template. `presets.instantiate(source, workspace_id, title=None, content=None, style=None, visibility='private', organization_id=None, org_editable=False)` creates an independent artifact. `presets.apply_style(target, style)` replaces appearance atomically. `presets.remove(entry)` clears library membership only. Invalid files raise `build.BuildError`.

- [x] Write snapshot, asset copying, isolation and rollback tests; run them to observe missing functionality.
- [x] Add the metadata migration and implement safe snapshot/configuration/CSS handling and library operations.
- [x] Run `uv run pytest tests/test_presets.py` and resolve failures.

### Task 2: JSON API and MCP workflows

**Files:** Modify `backend/api.py`, `backend/mcp_server.py`, `backend/instructions.md`, `tests/test_api.py`, `tests/test_mcp_server.py`.

**Interfaces:** Add `GET/POST /api/presets`, `DELETE /api/presets/{id}`, `POST /api/artifacts/{id}/style`; extend artifact creation with `template_id` and `style_id`. Expose MCP `list_presets`, `save_preset`, `new_template`, `new_style`, `new_from_template`, `apply_style`, `remove_preset`.

- [x] Write API/MCP tests for save, list, create, apply, removal, wrong kinds, foreign workspace, read-only targets, sign-in and same-origin checks.
- [x] Implement those endpoints and tools using Task 1, scoped library resolution, and existing permission rules. Include `preset_kind` in artifact JSON.
- [x] Run the focused API, MCP and presets tests.

### Task 3: Template-authoring skill and description workflow

**Files:** Create `skills/openartifact-templates/SKILL.md`; modify `backend/agent.py`, `backend/mcp_server.py`, `tests/test_chat.py`, `skills/openartifact/SKILL.md`.

**Interfaces:** MCP serves a second SkillProvider; `agent.about_this_run` includes the template skill only for `preset_kind == 'template'`.

- [x] Add a scripted-model chat test that sees template instructions, writes reusable files, builds successfully, and leaves the entry in the library.
- [x] Write the bundled skill and wire conditional loading and MCP discovery.
- [x] Run `uv run pytest tests/test_chat.py tests/test_mcp_server.py`.

### Task 4: Web library and final verification

**Files:** Create `frontend/app/src/components/Library.tsx`; modify `frontend/app/src/api.ts`, `frontend/app/src/pages/ArtifactList.tsx`, `frontend/app/src/pages/Editor.tsx`, `frontend/app/src/chat/Chat.tsx`, `README.md`.

**Interfaces:** Typed library methods in `api.ts`; home library supports template creation, CSS entry/import, preview/edit, removal, and starting from templates with an optional style. Editor library dialog supports save-as-template/style and applying styles. Template chat explains the reusable authoring workflow.

- [x] Implement the library and editor dialogs using existing UI primitives, accessible labels, busy/error states and normal preview refresh.
- [x] Ensure library entries are separate from ordinary artifact rows, template edits are visibly identified, and custom markdown paths use the configured source.
- [x] Document the workflows and run `pnpm -C frontend build`, `make format`, `make lint`, `make test`.
- [x] Review the whole change and exercise the UI with local services when available; fix any findings before delivery.

## Verification outcome

Format, lint, TypeScript checks, frontend build, skill validation and browser smoke tests passed. The full suite reports 295 passed and one pre-existing failure: `test_native_telemetry_reaches_logfire`, also reproduced against untouched HEAD. No templates/styles tests fail.
