# Templates and Styles from References Implementation Plan

> Work through the tasks in order and track implementation and verification below. Real-reference and live-provider evaluation is separate follow-up work.

**Goal:** Templates and styles can start from attached files and links, are drafts until saved, show as thumbnails in the library, and every style has a measured style guide.

**Architecture:** Most of this reuses what exists.
- **Files.** They ride on the chat's existing AI SDK file parts. `api.chat` rewrites PowerPoint, Word and SVG parts into text and images before the run, and removes raw/generated reference input before chat is stored, keeping labels and the derived brief.
- **New agent tools.** `look_at_link` reads a page and its CSS through pydantic-ai's SSRF-safe downloader, `keep_image` writes an attachment or a linked image into the artifact, and `add_font` installs a Google font.
- **Drafts** are a `draft` column with Save, Discard and an hourly sweep of drafts idle for 24 hours.
- **The style guide** is a runtime mode of the style's own page that measures computed styles. Loaded fonts and visual fidelity are also checked in Chrome.
- **Thumbnails** are cached chrome-service screenshots.

**Tech Stack:** FastAPI, asyncpg, pydantic-ai 2.54 (`VercelAIAdapter`, function tools, `pydantic_ai._ssrf.safe_download`), FastMCP, `zipfile`, `xml.etree`, `html.parser`, `tinycss2`, the TypeScript runtime, React 19 with `@ai-sdk/react`, headless Chrome.

**Spec:** `docs/superpowers/specs/2026-10-24-styles-from-references-design.md`

## Implementation status (2026-10-25)

- All nine implementation tasks are complete. Commits: `a32cdcf` (draft lifecycle), `9a35540` (reference ingestion, draft APIs, tools and cached previews), and `022d1fb` (measured guides and the reference authoring UI). Shared files were committed as integrated backend and frontend changes rather than one commit per task.
- Regression tests were added alongside implementation. Separate red-test runs were not recorded for every task; the checklists below track the implemented coverage and verification rather than claiming those runs happened.
- Synthetic Office/PDF/SVG inputs and scripted models cover draft creation, transient reference input, deliberate image retention, link restyling and local font installation. HTTP error tests exercise the actual SSRF downloader with controlled transport.
- Headless Chrome checks all three guide types, scoped/cover colours, responsive typography and an original local WOFF2 fixture. A disposable UI server with a scripted model exercises file limits, reference-only creation, exactly one initial send, later attachments, leave cancellation, browser Back/discard, Save, guide switching and missing-service placeholders. Screenshots were inspected.
- `make format`, `make lint`, frontend typecheck and both frontend builds pass. Final full-suite result: **381 passed, 1 failed** (`tests/test_server.py::test_native_telemetry_reaches_logfire`, missing Monty session/run spans). All new tests pass. All commit hooks pass. The previously identified Monty telemetry failure also reproduces on unchanged HEAD; it is independent of this feature.
- Real reference fidelity and live gateway PDF acceptance remain in the follow-up section. No real-reference or provider calls were used for implementation verification.

## Global Constraints

- `backend/build.py` stays standard-library only. Every artifact file change goes through `workspace.edit()`.
- The runtime stays synchronous: guide mode measures with `getComputedStyle` inside `main()`.
- No em dash (U+2014) in any source file or doc.
- A draft is visible only to its creator and appears in no list: `/api/artifacts`, `/api/presets`, MCP `list_artifacts` and `list_presets`. A draft with no change for 24 hours is deleted. The agent never saves.
- Reference payloads are transient: raw files, SVG markup and extracted reference facts are removed from stored chat input. Attachment labels and the agent's derived brief remain. Only deliberately kept assets enter the artifact or its history. Check instrumentation and browser history conversion as well as database serialization for payload retention.
- Attachment limits: at most 5 files per message, 20 MB in total and 5 MB per image. They are accepted only on drafts. The accepted files are PDF, `.pptx`, `.docx`, PNG, JPEG, GIF, WebP and SVG.
- Every server-side fetch of a user-given URL goes through `pydantic_ai._ssrf.safe_download` (no local addresses). Fonts come only from `fonts.googleapis.com` and `fonts.gstatic.com`.
- Style guide values are measured, never typed. The levels are Title, Heading 1, Heading 2, Heading 3, Body, Small and Code, and the types are Deck, Document and Page.
- Each task ends with `make format`, `make lint` and `make test`. Frontend tasks also run `pnpm -C frontend typecheck`, `pnpm -C frontend lint` and `pnpm -C frontend build`. Each task updates the `CLAUDE.md` paragraphs for what it changes.

## Review Focus

1. **A PowerPoint arriving as `application/octet-stream` or with no media type**, as browsers on machines without Office send it, is still unpacked: detection falls back to the file extension. Task 3: `test_office_detected_by_extension`.
2. **A link answering 401 or 403** (a login wall) says so in the tool's text, so the agent doesn't mistake a sign-in page for the brand. Task 4: `test_non_200_is_reported`.
3. **A deck whose embedded media are mostly large photos** still shows the agent the small images, where logos are: SVG and PNG first, smallest first, at most 8 and each up to 1 MB. Task 3: `test_media_prefer_small_images`.
4. **A first message with references but no description** is accepted, and the dialog supplies a default brief. Task 3: `test_message_with_only_files_is_accepted`. Task 7: the default brief.
5. **A library with no chrome service** gets a 503 from the thumbnail route and shows a placeholder card. Task 6: `test_thumbnail_without_chrome_is_503`. Task 7: the `onError` placeholder.
6. **Concurrent save, edit and expiry** cannot save an unvalidated version or delete a draft that was saved or edited while the sweep waited. Task 1 rechecks eligibility under the row lock.
7. **Reference and guide quality with real artifacts** is a separate follow-up after implementation, described at the end of this plan. It is not required to complete Tasks 1 to 9.

---

### Task 1: Draft rows and their lifecycle

**Progress (2026-10-25):** Committed as `a32cdcf`. Implemented draft rows, atomic save, conditional discard/expiry and durable cleanup retries. Added 12 integration cases, including locked validation, rollback on build/upload errors, stale sweep candidates and partial cleanup failures. Formatting and lint pass (existing CSS warnings). The full suite reports 331 passed and one telemetry failure (`test_native_telemetry_reaches_logfire`, missing Monty spans); the same failure reproduces on an unchanged HEAD snapshot. All 46 workspace/preset tests pass in the full run.

**Files:**
- Create: `backend/migrations/0006_drafts.sql`
- Modify: `backend/workspace.py`, `backend/presets.py`
- Test: `tests/test_workspace.py`, `tests/test_presets.py`

**Interfaces:**
- Produces:
  - **Fields.** `Artifact.draft: bool = False` (in `ARTIFACT_FIELDS` and `from_row`) and `NewArtifact.draft: bool = False` (`$10` in `edit()`'s `INSERT`).
  - **Lists.** `workspace.list_artifacts` and `list_shared_artifacts` exclude drafts.
  - **Deletion.** `workspace.delete_artifact` runs under `artifact_lock` and the row lock (`ArtifactBusy` on timeout, `LookupError` if missing). Draft discard and expiry pass conditions that are rechecked on the locked row before deletion, including the expiry cutoff. It deletes the row (chats cascade) and records durable cleanup work in the same transaction. After commit, idempotent cleanup deletes every store key under `artifacts/<id>/`, the cache's `<id>/` directory and the `_synced` entry. Failed cleanup remains discoverable for retry even though the artifact row is gone; include the cleanup schema in this migration.
  - **In `presets.py`:**
    - `create(workspace_id, name, type, *, kind, css=None, theme='light', draft=False)`
    - `DRAFT_TTL = timedelta(hours=24)` and `SWEEP_INTERVAL = 3600.0`
    - `async def save_draft(draft: workspace.Artifact, name: str) -> workspace.Artifact`
    - `async def discard_draft(draft: workspace.Artifact) -> None`
    - `async def sweep_drafts() -> int`
    - `async def sweep_drafts_forever() -> None`
- `save_draft`:
  1. `name_of(name)`.
  2. Enter one `workspace.edit()` block and recheck the locked row is still an owned draft.
  3. Update the title in `artifact.toml`, then validate the resulting source with `build.build_page_data(configuration(tx.path), css_validator=styles.validate)`. A `BuildError` rolls back the operation and the draft is kept.
  4. Update the row's title and `draft = false` through `tx.conn`. The title commit and row changes succeed together. Do not nest `rename_artifact()` or `open_artifact()` inside the edit lock. Return a freshly loaded row after commit.
- `sweep_drafts` selects candidates with `draft AND updated_at < cutoff`, then deletes through `delete_artifact` only if those conditions still hold under the row lock. Saved or newly edited candidates are skipped. Log failures, retry pending cleanup, and count only actual deletions. `sweep_drafts_forever` loops it with `asyncio.sleep(SWEEP_INTERVAL)`.
- The draft portion of the migration (also add the durable cleanup record described above):

```sql
-- Drafts: library entries being developed, listed nowhere and kept only when saved (`presets.save_draft`); one left
-- without a change for a day is deleted by `presets.sweep_drafts`.
alter table artifacts add column draft boolean not null default false;
create index artifacts_drafts_idx on artifacts (updated_at) where draft;
```

- [x] **Step 1: Write the failing tests**
  - `tests/test_workspace.py::test_drafts_are_not_listed`: a row created with `NewArtifact(..., preset_kind='template', draft=True)` has `.draft`, and is not in `list_artifacts`.
  - `tests/test_workspace.py::test_delete_artifact_removes_row_bundles_checkout_and_chat`: after two edits and a `chats.save`:
    - `get_artifact` gives `None`
    - `storage.list(f'artifacts/{id}/') == []`
    - the cache directory is gone
    - `chats.load` gives `([], None)`
    - a second delete raises `LookupError`
  - `tests/test_presets.py::test_draft_is_unlisted_until_saved`: `d = await presets.create(ws, 'Brand', 'deck', kind='template', draft=True)`. After `saved = await presets.save_draft(d, 'Harbor')`: `saved.id == d.id`, `not saved.draft`, `saved.title == 'Harbor'`, `load_config(...).title == 'Harbor'`, and it is listed.
  - `tests/test_presets.py::test_saving_a_broken_draft_is_refused_and_kept`: `main.md` is `'# {{ UNKNOWN }}\n'`, `pytest.raises(build.BuildError, match='UNKNOWN')`, and the row is still a draft.
  - `tests/test_presets.py::test_discard_deletes_the_draft`.
  - `tests/test_presets.py::test_sweep_deletes_only_idle_drafts`:
    - one draft has `updated_at` 25 hours back (set by SQL)
    - one draft is fresh
    - one saved entry has `updated_at` 25 hours back

    `sweep_drafts() == 1`, and only the idle draft is gone.
  - Add concurrency tests: an edit between candidate selection and deletion keeps the draft; a save before the sweeper obtains the row lock keeps the saved entry; an edit cannot interleave between save validation and publishing.
  - Add rollback and cleanup tests: failed save leaves both title and draft status unchanged; a failed store deletion is retried from durable cleanup work after the row is gone.

- [x] **Step 2: Run them and see them fail**

Run: `uv run pytest tests/test_workspace.py tests/test_presets.py -v`
Expected: the new tests FAIL, with `unexpected keyword argument 'draft'`.

- [x] **Step 3: Implement the migration, the `workspace.py` changes and the `presets.py` functions**

- [x] **Step 4: Run them and see them pass**

Run: `uv run pytest tests/test_workspace.py tests/test_presets.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/migrations/0006_drafts.sql backend/workspace.py backend/presets.py tests/test_workspace.py tests/test_presets.py CLAUDE.md
git commit -m "Add draft library entries: unlisted, saved on request, swept after a day"
```

---

### Task 2: Drafts in the API, MCP and the agent

**Progress:** Draft API/MCP creation, owner-only Save/Discard, direct artifact lookup, sharing/fork guards, version JSON, sweeper lifespan and agent draft instructions are implemented and covered by integration tests.

**Files:**
- Modify: `backend/api.py`, `backend/server.py`, `backend/mcp_server.py`, `backend/agent.py`, `backend/instructions.md`, `skills/openartifact-templates/SKILL.md`
- Test: `tests/test_api.py`, `tests/test_mcp_server.py`, `tests/test_chat.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - **The JSON.** `artifact_json` adds `'draft'` and `'version'` (the head sha).
  - **`POST /api/presets`** without `artifact_id` creates with `draft=True`. With `artifact_id`, it is unchanged: an immediate snapshot.
  - **`async def draft_for(draft_id: str, viewer: auth.Principal) -> workspace.Artifact`** answers 404 unless the row is a draft in the viewer's workspace.
  - **`POST /api/drafts/{id}/save`** takes `{"name": str}` and answers 200 with the entry's JSON. A `BuildError` is a 400 with the checkout path stripped, as `put_source` does, and `ArtifactBusy` is a 409.
  - **`POST /api/drafts/{id}/discard`** answers 204. Both draft routes pass `mutation()`.
  - **Refusals.** `preset_for` answers 404 for drafts, and `PATCH /api/artifacts/{id}` on a draft is a 400 with `'save the draft before sharing it'`.
  - **The lifespan** in `server.py` runs `presets.sweep_drafts_forever()` as a task and cancels and awaits it on shutdown.
  - **MCP:**
    - `new_template(...)` and `new_style(title, css: str | None = None, theme='light')` create drafts, and their replies end with `DRAFT_REPLY`.
    - `save_draft(artifact: str, name: str | None = None) -> str` resolves with `edit=True` and requires `.draft`. Otherwise it raises `ToolError('not a draft: drafts come from new_template and new_style')`. It returns `created(entry.id, True)`.
    - `resolve_preset` refuses drafts with `ToolError('this is an unsaved draft; save it with `save_draft` first')`.
  - **The agent.** `about_this_run` loads the template skill for `preset_kind in ('template', 'style')` and appends `DRAFT_NOTE.format(kind=...)` for drafts. `AGENT_TOOLS` is unchanged.
- Exact copy:
  - `DRAFT_REPLY = 'This is an unsaved draft. Build it with the user and call `save_draft` only when they say to save it; an unsaved draft is deleted a day after its last change.\n'`
  - `DRAFT_NOTE = 'This is an unsaved draft of a library {kind}. It is kept only when the user presses Save in the editor; you cannot save it. When you think it is ready, suggest saving. Never say that it has been saved.'`
  - **`SKILL.md`:** replace "it is already saved in the user's library" with "it is an unsaved draft that the user keeps by pressing Save; never say it is saved". For external clients, replace the sentence on `new_template` with "`new_template` and `new_style` start drafts and `save_draft` keeps one when the user says so".
  - **`instructions.md`:** the same change, and `save_draft` is listed.

- [x] **Step 1: Add regression tests**
  - `tests/test_api.py::test_creating_a_library_entry_opens_a_draft`:
    - `POST /api/presets {name: 'Report', kind: 'template', type: 'document'}` gives 201 with `draft is True`.
    - The draft is in neither `/api/presets` nor `/api/artifacts` `mine`.
    - Save `{name: 'Board report'}` gives 200 with `draft is False`, and the entry is listed in `templates`.
  - `tests/test_api.py::test_style_from_css_opens_a_draft`.
  - `tests/test_api.py::test_saving_a_broken_draft_over_the_api_is_400`: `UNKNOWN` is in the detail, and the source is still served.
  - `tests/test_api.py::test_discard_deletes_the_draft`: 204, then the source gives 404.
  - `tests/test_api.py::test_draft_routes_belong_to_their_creator`: the outsider from `org_members` gets 404, and `sec-fetch-site: cross-site` gets 403.
  - `tests/test_api.py::test_drafts_cannot_be_shared`: the PATCH gives 400.
  - `tests/test_api.py::test_lifespan_runs_the_sweeper`: monkeypatch `presets.sweep_drafts` with a recorder and `SWEEP_INTERVAL = 0.01`. Within `TestClient`, poll up to 2 s until the recorder was called.
  - Update `test_personal_library_workflow`: it saves the CSS style's draft before using it.
  - `tests/test_mcp_server.py::test_mcp_drafts_are_saved_only_on_request`: the reply contains `unsaved draft`. The draft is absent from `list_presets`, then present after `save_draft(id, 'Board report')`.
  - `tests/test_mcp_server.py::test_drafts_cannot_be_used_as_templates_yet`: `new_from_template(draft_id)` raises a `ToolError` matching `save_draft`.
  - `tests/test_chat.py`: update `test_description_creates_a_reusable_template_with_the_bundled_skill` (a draft, `'unsaved draft'` in `info.instructions`, `save_draft` not in the function tool names). Add `test_style_draft_chat_gets_the_authoring_skill`.

- [x] **Step 2: Run focused regression tests**

Run: `uv run pytest tests/test_api.py tests/test_mcp_server.py tests/test_chat.py -v`
Expected: the regression tests exercise the implemented behavior. See implementation status for results.

- [x] **Step 3: Implement the routes, the lifespan task, the MCP changes, the agent note and the copy**

- [x] **Step 4: Run them and see them pass**

Run: `uv run pytest tests/test_api.py tests/test_mcp_server.py tests/test_chat.py tests/test_server.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/api.py backend/server.py backend/mcp_server.py backend/agent.py backend/instructions.md skills/openartifact-templates/SKILL.md tests/test_api.py tests/test_mcp_server.py tests/test_chat.py CLAUDE.md
git commit -m "Create library entries as drafts in the API and over MCP"
```

---

### Task 3: Attachments in the chat

**Progress:** Bounded data-URL input, Office extraction, SVG text, per-turn files, deliberate keep_image writes and history/telemetry retention controls are implemented. The adapter history boundary is tested, including preservation of prior turns.

**Files:**
- Create: `backend/attachments.py`
- Modify: `backend/api.py` (`chat`), `backend/agent.py` (`ChatDeps.files`, the `keep_image` tool)
- Test: `tests/test_attachments.py`, `tests/test_chat.py`

**Interfaces:**
- Consumes: Task 2 (drafts).
- Produces, in `attachments.py`:
  - **Request bounds.** Bound the chat request body before `VercelAIAdapter.from_request` parses JSON, including bodies without `Content-Length`. Allow bounded base64 and JSON overhead above the 20 MB decoded-file limit. Reject oversized encoded payloads before decoding and accept only valid data URLs for attachment parts, never remote URLs. Test malformed base64, an oversized streamed body and remote file URLs.
  - **Limits.** `MAX_FILES = 5`, `MAX_TOTAL_BYTES = 20 * 1024 * 1024` and `MAX_IMAGE_BYTES = 5 * 1024 * 1024`.
  - **Media.** `MAX_MEDIA = 8` and `MAX_MEDIA_BYTES = 1024 * 1024`.
  - **Zip limits.** `ZIP_MAX_MEMBERS = 2000`, `ZIP_MAX_BYTES = 200 * 1024 * 1024` and `XML_MAX_BYTES = 5 * 1024 * 1024`. `SVG_TEXT_LIMIT = 50_000`.
  - **Media types.** `MODEL_IMAGE_TYPES = frozenset({'image/png', 'image/jpeg', 'image/gif', 'image/webp'})`. `OFFICE_KINDS = {'.pptx': 'PowerPoint', '.docx': 'Word'}`, detected by the extension of `filename` whatever the media type.
  - **Types.** `class AttachmentError(ValueError)` and `@dataclass(frozen=True) class Attachment: name: str; media_type: str; data: bytes`.
  - **`def office_facts(name: str, data: bytes) -> tuple[str, list[Attachment]]`**, read with `zipfile` and `xml.etree`:
    - From `ppt/theme/theme1.xml` or `word/theme/theme1.xml`: `theme colour <dk1|lt1|dk2|lt2|accent1..6|hlink|folHlink>: #RRGGBB`, `heading font: X` (`a:majorFont/a:latin`) and `body font: Y` (`a:minorFont`).
    - PowerPoint: `slide size: W x H in` and `slides: N`.
    - Word: `<Title|Heading 1..3|Normal>: <pt>pt, <font>, bold, colour #RRGGBB`, with the parts present, from `word/styles.xml`.
    - The media under `ppt/media/` and `word/media/` (`.svg`, `.png`, `.jpg`, `.jpeg`, `.gif`): SVG and PNG first, then smallest first. At most `MAX_MEDIA` of them, each up to `MAX_MEDIA_BYTES`, as `Attachment(f'{name}/{basename}', ...)`.
    - Errors: `AttachmentError('<name> is not a PowerPoint or Word file')` and `AttachmentError('<name> is too large to read safely')`.
  - **`def prepare(message: UIMessage) -> tuple[UIMessage, dict[str, Attachment]]`** decodes each `FileUIPart` data URL and checks the limits and types. A wrong type is `AttachmentError('<name>: attach a PDF, PowerPoint or Word file, or an image')`. Each file becomes a `TextUIPart` `Attached <name> (<PDF|PowerPoint|Word|image>).`, then:
    - a PDF or model image: its original `FileUIPart`
    - an office file: a `TextUIPart` with its facts, then for each media image `TextUIPart('Embedded image <name>.')` and a `FileUIPart` data URL (SVG media as text)
    - an SVG: a `TextUIPart` with the markup in an `svg` code fence, cut at `SVG_TEXT_LIMIT`

    The returned dict holds every original and every media file by name.
  - **`strip` and stored history.** Remove `BinaryContent`, `ImageUrl` and `DocumentUrl` from user input and remove generated SVG markup and office facts too. Track generated reference input explicitly rather than filtering arbitrary user text; extend `strip`'s arguments as needed to carry that provenance. Preserve the attachment labels, original user text and the agent's derived brief. Verify the persisted model history and the UI history returned on reload, including SVG and office inputs. Check telemetry configuration for raw reference payload retention.
- In `agent.py`:
  - **`ChatDeps.files: dict[str, attachments.Attachment] = field(default_factory=dict)`.**
  - **`@agent.tool async def keep_image(ctx: RunContext[ChatDeps], source: str, path: str) -> str`.** `source` is a name from `ctx.deps.files`; Task 4 adds URLs. It checks `upload.validate_path(path)` and that the path ends with a `build.IMAGE_EXTS` extension. It writes in `workspace.edit(ctx.deps.artifact.id, f'keep image: {path}')` and returns `kept <source> as <path> (<n> bytes)`.
  - **An unknown source** raises `ModelRetry('no attachment called <source> in this turn: attachments are only available in the turn they were sent')`.
- In `api.chat`, after `from_request`:
  - Take `last = adapter.run_input.messages[-1]`.
  - If it has a `FileUIPart` and `not found.draft`, answer 400 with `'attach files to a template or style draft; in other chats, paste a link'`.
  - Otherwise `prepare(last)` replaces it in place, and an `AttachmentError` is a 400.
  - `deps.files` gets the dict. The save callback strips generated reference text only from this turn, starting at `len(stored_history)`: the UI adapter appends the incoming prompt before Agent.run, so `result.new_messages()` excludes that prompt. Binary inputs and linked-page tool results are also removed from persisted history.

- [x] **Step 1: Add regression tests**
  - In `tests/test_attachments.py`, the helper `with_theme(path, accent1, major, minor)` rewrites the theme XML inside a file saved by `python-pptx` / `python-docx`. The helper `file_part(name, media_type, data)` builds a `FileUIPart` with a base64 data URL.
    - `test_pptx_becomes_facts_and_images`: `accent1='FF6B4A'`, `major='Söhne'`, `minor='Inter'`, and one PNG picture on a slide.
      - The facts contain `theme colour accent1: #FF6B4A`, `heading font: Söhne`, `body font: Inter` and `slides: 1`.
      - The parts' kinds are, in order: text `Attached brand.pptx (PowerPoint).`, facts text, text `Embedded image brand.pptx/image1.png.`, file `image/png`.
      - The files dict has the keys `brand.pptx` and `brand.pptx/image1.png`.
    - `test_docx_heading_styles`: `Heading 1` at 20 pt in Fraunces gives a line starting `Heading 1: 20pt, Fraunces`.
    - `test_office_detected_by_extension`: the same pptx with `media_type='application/octet-stream'` still gives facts.
    - `test_media_prefer_small_images`: one 2 MB PNG and one 10 KB PNG give only the small one shown.
    - `test_svg_goes_as_text`.
    - `test_pdf_and_png_pass_through`: the original `FileUIPart`s are kept, each preceded by its label.
    - `test_limits`, each an `AttachmentError` match:
      - 6 files: `5`
      - 21 MB in total: `20 MB`
      - a 6 MB PNG: `5 MB`
      - `notes.txt`: `attach a PDF`
      - a corrupt pptx: `not a PowerPoint`
      - `ZIP_MAX_BYTES` monkeypatched to 10: `too large`
    - `test_message_with_only_files_is_accepted`: a message with no text part is prepared without error.
    - `test_strip_drops_binary_content`: a `ModelRequest` with `UserPromptPart(['Attached a.pdf (PDF).', BinaryContent(b'%PDF', media_type='application/pdf')])` keeps only the text.
  - In `tests/test_chat.py`, add `parts: list[dict[str, Any]] | None = None` to `send`:
    - `test_attachments_reach_the_model_and_are_not_stored`, on a template draft created through `POST /api/presets`. The scripted model:
      1. asserts that a `BinaryContent` with `media_type == 'application/pdf'` and the text `Attached deck.pdf (PDF).` are in the last `UserPromptPart`
      2. calls `keep_image(source='logo.png', path='assets/logo.png')`
      3. answers

      Afterwards the checkout has `assets/logo.png` with the sent bytes, and `chats.load` holds no `BinaryContent` anywhere.
    - `test_files_are_refused_outside_drafts`: a file part on `starter(client)` gives 400.

- [x] **Step 2: Run focused regression tests**

Run: `uv run pytest tests/test_attachments.py tests/test_chat.py -v`
Expected: the regression tests exercise the implemented behavior. See implementation status for results.

- [x] **Step 3: Implement `attachments.py`, `keep_image` and the `api.chat` changes**

- [x] **Step 4: Run them and see them pass**

Run: `uv run pytest tests/test_attachments.py tests/test_chat.py -v`
Expected: PASS.

**Follow-up:** Live gateway PDF acceptance is deferred with real-reference evaluation; see the final section.

- [x] **Step 6: Commit**

```bash
git add backend/attachments.py backend/api.py backend/agent.py tests/test_attachments.py tests/test_chat.py CLAUDE.md
git commit -m "Pass chat attachments to the agent for one turn, unpacking office files, and keep chosen images"
```

---

### Task 4: Reading links and installing fonts

**Progress:** Public link/CSS facts, explicit HTTP failures, bounded SSRF-safe fetching, URL images and local Google Fonts installation are implemented. Saved styles enforce local assets; controlled-transport and scripted-model tests pass.

**Files:**
- Create: `backend/links.py`, `backend/fonts.py`
- Modify: `backend/agent.py` (`look_at_link`, URL sources for `keep_image`, `AGENT_TOOLS`, `PREAMBLE`), `backend/mcp_server.py` (`add_font`), `backend/instructions.md`
- Test: `tests/test_links.py`, `tests/test_fonts.py`, `tests/test_chat.py`

**Interfaces:**
- Consumes: Task 3 (`keep_image`).
- Produces, in `links.py`:
  - **Constants.** `PAGE_MAX_BYTES = 2 * 1024 * 1024`, `SHEET_MAX_BYTES = 1024 * 1024`, `MAX_SHEETS = 10` and `IMAGE_MAX_BYTES = 5 * 1024 * 1024`.
  - **The seam.** `download = safe_download`, from `pydantic_ai._ssrf import safe_download`, kept as a module attribute so tests can stub it.
  - **`class LinkError(Exception)`.**
  - **`def page_facts(base_url: str, html: str, sheets: list[tuple[str, str]]) -> str`**, using `html.parser` and `tinycss2`:
    - `title: ...`
    - up to 40 custom properties `--name: value` from `:root`, `html` or `body` rules
    - up to 8 `font-family <value> (<count>)`, most used first
    - `@font-face: <family>`
    - up to 12 colours normalised to `#rrggbb`, as `#0e2238 (5): body, .hero, h1`, with up to three selectors each
    - `logo candidates:` with the absolute URLs of `<img>` whose `src`, `alt`, `class` or `id` contains `logo`, then `<link rel~="icon">` (SVG first), then `og:image`
  - **`async def read_link(url: str) -> str`** downloads the page (`max_bytes=PAGE_MAX_BYTES`) and up to `MAX_SHEETS` `<link rel="stylesheet">` sheets (each `SHEET_MAX_BYTES`, failures reported). It returns `page_facts`, prefixed with `<final url>`. The pinned `safe_download` raises on HTTP errors: catch its HTTP status exception and report `The page answered <status>: it could not be inspected as the site itself.` Do not assume an error response body is available or parse it as brand evidence. For a successful response whose status is not 200, report the status explicitly as well.
  - **`async def download_image(url: str) -> tuple[str, bytes]`** requires an `image/*` content type and `IMAGE_MAX_BYTES`.
  - **Errors.** A `safe_download` error becomes `LinkError(f'could not read {url}: {exc}')`.
- Produces, in `fonts.py`:
  - **Constants.** `CSS_API = 'https://fonts.googleapis.com/css2'`, `FONT_HOST = 'fonts.gstatic.com'`, `SUBSETS = ('latin', 'latin-ext')`, and `USER_AGENT`, a current desktop Chrome user agent so the API answers WOFF2.
  - **`class FontError(Exception)`** and a stub-friendly download seam using `safe_download`, with bounded responses and Google host allowlists checked at every redirect. Require HTTPS; the CSS request permits only `fonts.googleapis.com` and font requests only `fonts.gstatic.com`.
  - **`def slug(family: str) -> str`.**
  - **`@dataclass(frozen=True) class FontFile: path: str; weight: int; style: str; unicode_range: str | None; data: bytes`.**
  - **`async def fetch_family(family: str, weights: list[int], italic: bool) -> list[FontFile]`:**
    - It sends `family=<Family+With+Plus>:ital,wght@0,400;0,700`, with `1,<w>` added when italic.
    - A 400 raises `FontError('<family> is not a Google Fonts family, or lacks those weights')`.
    - It keeps the blocks after `/* latin */` and `/* latin-ext */`. Every `src` must be on `FONT_HOST`, otherwise it raises `FontError('unexpected font host')`.
    - The paths are `fonts/<slug>-<weight>[-italic]-<subset>.woff2`.
  - **`def font_face_css(family: str, files: list[FontFile]) -> str`** writes one `@font-face` per file, with `font-display: swap`, a relative `url()` and `unicode-range`.
- The tools:
  - **MCP `add_font(artifact: str, family: str, weights: list[int] = [400, 700], italic: bool = False) -> str`:**
    - It resolves with `edit=True`. The weights are 100..900 in steps of 100, at most 6.
    - It writes in `editing(found.id, f'add font: {family}')` and returns the CSS, then: `Put these rules in styles.css and set --font-heading, --font-body or --font-mono to '<family>' with a generic fallback.`
  - **Agent `@agent.tool async def look_at_link(ctx, url: str) -> str`** returns `read_link`, or the `LinkError` text so the agent reports it.
  - **`keep_image`** accepts an http(s) `source` through `download_image`.
  - **`AGENT_TOOLS`** gains `'add_font'`.
  - **Appended to `PREAMBLE`:** `- When the user gives a link and asks for the artifact to look like it, read it with `look_at_link`, then restyle styles.css, the theme, fonts (`add_font`) and logo (`keep_image`) while keeping the content.`
  - **`instructions.md`** lists `add_font`, and tells external agents to read the user's files and links with their own tools and to upload kept images with `upload_url`.

- [x] **Step 1: Add regression tests**
  - `tests/test_links.py`:
    - `test_safe_download_is_available`: `from pydantic_ai._ssrf import safe_download` succeeds. This pins the private API.
    - `test_page_facts_reads_tokens_fonts_colours_and_logo`:
      - The HTML has `<title>Harbor</title>`, `<link rel="icon" href="/favicon.svg">` and `<img src="/img/logo.svg" alt="Harbor">`.
      - The sheet is `:root{--brand:#0e2238} body{font-family:"Söhne",sans-serif;color:#1B1F24} h1{color:rgb(14,34,56)} @font-face{font-family:"Söhne";src:url(s.woff2)}`, at `https://harbor.example/`.
      - The text contains `title: Harbor`, `--brand: #0e2238`, `font-family "Söhne", sans-serif (1)`, `@font-face: Söhne`, `#0e2238 (2)`, `https://harbor.example/img/logo.svg` and `https://harbor.example/favicon.svg`.
    - `test_non_200_is_reported`: `links.download` raises the HTTP status exception exposed by the pinned downloader for 401 and 403; the text reports the status without claiming to have read the site. Exercise the actual downloader with a controlled transport too, so the stub cannot hide a dependency mismatch.
    - `test_private_addresses_are_refused`: the real `read_link('http://127.0.0.1:9/')` raises a `LinkError` matching `could not read`.
  - `tests/test_fonts.py`, with the download seam stubbed and controlled transport tests for allowlists and redirects:
    - `test_slug`: `Source Serif 4` gives `source-serif-4`.
    - `test_fetch_family_keeps_latin_subsets`: the stub has `/* cyrillic */`, `/* latin-ext */` and `/* latin */` blocks, giving the two paths `fonts/inter-400-latin-ext.woff2` and `fonts/inter-400-latin.woff2`.
    - `test_unknown_family_is_reported`.
    - `test_foreign_font_hosts_are_refused`.
    - Test HTTPS enforcement, response-size bounds and redirects to a foreign or private host.
    - `test_add_font_writes_files_and_the_css_builds`: after appending the returned CSS to `styles.css`, `build_artifact` succeeds.
  - `tests/test_chat.py::test_ordinary_chat_restyles_from_a_link`:
    - `links.download` is stubbed to return a page with `--brand:#ff6b4a`.
    - The scripted model calls `look_at_link('https://harbor.example/')`, asserts that `#ff6b4a` is in the return, runs `run_code` writing `styles.css` as `':root { --accent: #ff6b4a }'`, then `build`.
    - Afterwards `styles.css` has it and `main.md` is unchanged.

- [x] **Step 2: Run focused regression tests**

Run: `uv run pytest tests/test_links.py tests/test_fonts.py tests/test_chat.py -v`
Expected: the regression tests exercise the implemented behavior. See implementation status for results.

- [x] **Step 3: Implement `links.py`, `fonts.py`, the tools and the copy**

- [x] **Step 4: Run them and see them pass**

Run: `uv run pytest tests/test_links.py tests/test_fonts.py tests/test_chat.py tests/test_mcp_server.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add backend/links.py backend/fonts.py backend/agent.py backend/mcp_server.py backend/instructions.md tests/test_links.py tests/test_fonts.py tests/test_chat.py CLAUDE.md
git commit -m "Read links safely, keep linked images and install Google fonts"
```

---

### Task 5: The style guide

**Progress:** The synchronous guide mode is implemented for all three types. Real Chrome verifies measured sizes, colours, cover overrides, responsive rules, no-CSS fallback and local font readiness.

**Files:**
- Create: `frontend/src/guide.ts`, `frontend/src/styles/guide.css`
- Modify: `frontend/src/main.ts`, `skills/openartifact/references/styles.md`
- Test: `tests/test_guide.py`

**Interfaces:**
- Produces. These are the DOM contract the tests and the app rely on.
  - **The mode.** `export function guideRequested(): boolean` (a `guide` query parameter) and `export function guideType(fallback: ArtifactType): ArtifactType` (the `type` parameter when valid).
  - **The renderer.** `export function renderGuide(root: HTMLElement, data: ArtifactData, config: ArtifactConfig): void` shows `config.type`.
  - **The constants.** `export const LEVELS = ['Title', 'Heading 1', 'Heading 2', 'Heading 3', 'Body', 'Small', 'Code'] as const`. `export const GUIDE_TOKENS: Array<[string, string]>` is `--slide-bg` Background, `--surface` Surface, `--slide-text` Text, `--slide-heading` Headings, `--accent` Accent, `--accent-secondary` Accent 2, `--accent-tertiary` Accent 3 and `--color-muted` Muted.
  - **The DOM:**
    - the root is `div.oa-guide[data-type]`, with the header (the title, then `nav.oa-guide-types a[data-type]` with `href="?guide&type=<t>"`) and the colours at the top, so the top 800 x 450 is the card thumbnail
    - each colour is `div.oa-guide-color[data-token][data-value="#rrggbb"]`, with the role label and the hex
    - each font is `div.oa-guide-font[data-role="heading|body|mono"][data-family]`
    - each level is `tr.oa-guide-level[data-level][data-size][data-line-height][data-weight]`
  - **`main.ts`.** When `guideRequested()`, the config's type becomes `guideType(config.type)` before the type sheets are chosen. After the styles go in, it calls `renderGuide`, sets `window.openartifact = { type, title, deck: null }`, reports the selected guide as page 1, 2 or 3 (deck, document or page) when framed, matching the screenshot tool, and returns.
- How it measures:
  - **The specimen.** It goes through `splitPages` and `buildPage`, without `page_component`. It is a cover page (`<!-- class: cover -->`, `# Annual report`) and a page with `# Where we are`, `## Revenue by region`, `### Key figures`, `Steady growth across every market we serve. <small>Source: internal finance</small>` and a fenced `js` line `revenue.by('region')`.
    - It is wrapped as `main.ts` wraps the type: a deck's pages get `page--active` inside `.artifact-deck.deck-presenter > .deck`, and prose types sit in `.artifact.artifact-<type>.theme-<theme>`.
    - It is mounted in `div.oa-guide-specimen` (`position: fixed; left: -10000px; top: 0; visibility: hidden`).
  - **The levels.** Title is the cover's `h1`. The rest come from page 2: `h1`, `h2`, `h3`, `p`, `small` and `pre code`. Each reads `font-family`, `font-size`, `line-height`, `font-weight`, `font-style`, `letter-spacing`, `text-transform` and `color`, which the sample cell copies inline.
    - The label is `<size> / <line height> · <weight>`, plus ` · caps` for uppercase and ` · <letter-spacing>` unless it is `normal`.
    - Pixel values are rounded to 0.1, with a trailing `.0` dropped.
  - **Colours.** A probe in the specimen page sets `color: var(<token>)`. The computed `rgb()` becomes `#rrggbb` (with alpha hex when below 1), and tokens that resolve to nothing are skipped.
  - **Fonts.** Each font is the first family of the probe's computed `font-family` under `var(--font-heading)`, `--font-body` or `--font-mono`, without quotes.
  - **`guide.css`** is scoped to `.oa-guide`, with the theme's `--slide-bg`, `--slide-text`, `--color-muted` and `--font-body`.
  - **`styles.md`** gains a "Sizes per form factor" section with `.deck .page h1`, `.artifact-document .prose h1`, `.artifact-page .prose h1` and `.page.cover h1`.
  - **Measurement scope.** Computed font-family reports the requested stack, not proof of a loaded font. Keep runtime measurement synchronous and label that stack accurately. In Chrome verification, explicitly await font readiness and check the local font is loaded before comparing screenshots. Samples must reproduce the measured specimen's typography, colour and relevant inherited styles; copy resolved values from the actual specimen element rather than assuming guide-level tokens match it. Check cover-specific tokens separately from body tokens. A single specimen does not establish fidelity for every layout or viewport.

- [x] **Step 1: Add regression tests** in `tests/test_guide.py`.
  - Skip the module when `pdf.find_chrome() is None` or `frontend/dist/openartifact.js` is missing.
  - A fixture builds a style directory with `build.build_html(d, runtime_url='/openartifact.js')` and serves `/openartifact.js` and `/a/` (`d/dist/index.html` plus `d`'s files) from a `ThreadingHTTPServer` thread.
  - Pages are read with `pdf.dump_dom(f'{base}/a/?guide&type={t}')` and parsed with `html.parser`.
  - `test_guide_measures_type_scoped_sizes`: the CSS is `.artifact-document .prose h1 { font-size: 30px; line-height: 36px; font-weight: 600 }`.
    - In the document guide, `Heading 1` has `data-size="30px"`, `data-line-height="36px"` and `data-weight="600"`.
    - In the deck guide, its `data-size != "30px"`.
    - All seven `LEVELS` are present in each of the three types.
  - `test_guide_resolves_colours`: `:root { --accent: #ff6b4a }` gives `.oa-guide-color[data-token="--accent"][data-value="#ff6b4a"]`, whose text contains `Accent`.
  - `test_guide_without_css_still_renders`: at least one colour, and seven levels.
  - Add Chrome checks for a local WOFF2 font, cover-specific colour and font overrides, type-scoped tokens and responsive rules. Compare displayed samples with specimen computed values at the tested viewport; verify screenshots after fonts load. Keep these distinct from the synchronous DOM-value tests.

- [x] **Step 2: Build the runtime and run regression tests**

Run: `pnpm -C frontend build && uv run pytest tests/test_guide.py -v`
Expected: the regression tests exercise the implemented behavior. See implementation status for results.

- [x] **Step 3: Implement `guide.ts`, `guide.css`, the `main.ts` hook and the `styles.md` section**

- [x] **Step 4: Build, run the tests and see them pass**

Run: `pnpm -C frontend build && pnpm -C frontend typecheck && pnpm -C frontend lint && uv run pytest tests/test_guide.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add frontend/src/guide.ts frontend/src/styles/guide.css frontend/src/main.ts skills/openartifact/references/styles.md tests/test_guide.py CLAUDE.md
git commit -m "Render a measured style guide as a runtime mode"
```

---

### Task 6: Thumbnails and screenshots of styles

**Progress:** Half-scale Chrome support, style-guide screenshot selection, authenticated versioned thumbnail caching and placeholders are implemented. Tests cover coalescing, concurrent edits and stale version queries.

**Files:**
- Modify: `chrome/server.py`, `chrome/pdf.py`, `backend/render.py`, `backend/api.py`, `backend/mcp_server.py` (`screenshot` docstring)
- Test: `tests/test_chrome.py`, `tests/test_api.py`, `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: Task 5's URLs.
- Produces:
  - **The chrome service.** `ScreenshotRequest.scale: float = Field(1, ge=0.5, le=3)`. In `pdf.screenshot(..., scale: float = 1)`, the flag is `f'--force-device-scale-factor={scale:g}'` when `scale != 1`. Chrome clamps scales below 0.5, as checked.
  - **Guide URLs.** `render.print_url(found, page=None, scene=False, guide: str | None = None)`, where `guide` is a type and appends `?guide&type=<type>`.
  - **Constants.** `render.GUIDE_PAGES = ('deck', 'document', 'page')`, `render.THUMBNAIL_SCALE = 0.5` and `render.CARD_VIEWPORT = (800, 450)`.
  - **Style screenshots.** `render.screenshot(found, page)` for a style shows `GUIDE_PAGES[page - 1]` in `VIEWPORTS['page']`. A page over 3 raises `RenderError(422, 'a style has three pages: its guide for deck, document and page')`.
  - **Thumbnails.** `async def render.thumbnail(found: workspace.Artifact) -> bytes`:
    - It is cached at `cache_dir() / str(found.id) / f'thumbnail-{found.head_sha}.png'`, and older ones are removed when it writes.
    - A template uses page 1 in `VIEWPORTS[found.type]`, and a style uses `guide='document'` in `CARD_VIEWPORT`, both at `THUMBNAIL_SCALE`.
    - Coalesce concurrent renders per artifact/version, using a separate lock from `artifact_lock`: Chrome must fetch the page while rendering. Recheck the head after rendering and publish only if it still matches the requested version; otherwise retry against the new head with a bounded retry policy. Write the cache file atomically. Old `v` queries must not return a new picture with an immutable version identity: return a retryable response when the requested version is no longer current.
  - **`GET /api/presets/{id}/thumbnail`** goes through `preset_for`, so saved entries only. It answers `image/png` with `Cache-Control: private, max-age=86400`, and a `RenderError` answers with its status.
  - **The `screenshot` docstring** says that for a style, pages 1, 2 and 3 are its guide for deck, document and page.

- [x] **Step 1: Add regression tests**
  - `tests/test_chrome.py::test_screenshot_accepts_half_scale`: `--force-device-scale-factor=0.5` is in the recorded args, and `0.25` gives 422.
  - In `tests/test_api.py`, with `stub_chrome` from `test_server`:
    - `test_template_thumbnail_is_rendered_once_per_version`: two GETs give one ask ending `' 1600x900'`, and after an edit a GET asks again.
    - `test_style_thumbnail_is_the_top_of_its_guide`: the ask contains `?guide&type=document` and ends `' 800x450'`.
    - `test_thumbnail_without_chrome_is_503`.
    - `test_thumbnail_is_for_saved_entries`: a draft gives 404.
    - Test concurrent requests produce one render, an edit during rendering cannot publish bytes under the wrong SHA, and a stale `v` query cannot cache the current image as an older version.
  - `tests/test_mcp_server.py::test_screenshot_of_a_style_is_its_guide`: page 2 asks for `?guide&type=document`, and page 4 is a `ToolError` matching `three pages`.

- [x] **Step 2: Run focused regression tests**

Run: `uv run pytest tests/test_chrome.py tests/test_api.py tests/test_mcp_server.py -k "scale or thumbnail or guide" -v`
Expected: the regression tests exercise the implemented behavior. See implementation status for results.

- [x] **Step 3: Implement as listed under Interfaces**

- [x] **Step 4: Run them and see them pass**

Run: `uv run pytest tests/test_chrome.py tests/test_api.py tests/test_mcp_server.py -v`
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add chrome/server.py chrome/pdf.py backend/render.py backend/api.py backend/mcp_server.py tests/test_chrome.py tests/test_api.py tests/test_mcp_server.py CLAUDE.md
git commit -m "Render cached thumbnails and screenshot styles as their guide"
```

---

### Task 7: The library and the creation dialogs

**Progress:** Library cards, style-guide selection, reference/CSS dialogs and the in-memory first-message handoff are implemented. Typecheck/build and the synthetic headless UI workflow verify the new flow.

**Files:**
- Create: `frontend/app/src/pending.ts`, `frontend/app/src/components/ReferencePicker.tsx`, `frontend/app/src/components/StyleGuide.tsx`
- Modify: `frontend/app/src/api.ts`, `frontend/app/src/components/Library.tsx`

**Interfaces:**
- Consumes: Tasks 2 and 6.
- Produces:
  - **`api.ts`:**
    - `Artifact` gains `draft: boolean` and `version: string | null`.
    - `api.thumbnailUrl(entry: Artifact): string` is `` `/api/presets/${entry.id}/thumbnail?v=${entry.version ?? ''}` ``.
    - `api.saveDraft(id: string, name: string): Promise<Artifact>` and `api.discardDraft(id: string): Promise<void>`.
    - `export const ATTACH_ACCEPT = '.pdf,.pptx,.docx,.png,.jpg,.jpeg,.gif,.webp,.svg'`.
    - `export const ATTACH_LIMITS = { files: 5, totalBytes: 20 * 1024 * 1024, imageBytes: 5 * 1024 * 1024 }`.
    - `export function checkAttachments(files: File[]): string | null`, with the messages "Attach up to five files", "Attachments are limited to 20 MB in all" and "<name> is over 5 MB".
  - **`pending.ts`** is an in-memory hand-off that survives `navigate()`, which does not reload the page: `export function setPending(id: string, value: { text: string; files: File[] }): void` and `export function takePending(id: string): { text: string; files: File[] } | null`. It replaces `templateBriefKey` and its `sessionStorage` use.
  - **`ReferencePicker({ files, links, onFiles, onLinks, disabled }: { files: File[]; links: string[]; onFiles: (f: File[]) => void; onLinks: (l: string[]) => void; disabled: boolean })`:**
    - a drop zone reading "Drop a PDF, PowerPoint or Word file, or an image"
    - `<input type="file" multiple accept={ATTACH_ACCEPT}>`
    - removable chips for the chosen files
    - link inputs with "Add a link"
    - the `checkAttachments` message shown under it
  - **`StyleGuide({ styleId, version }: { styleId: string; version: string | null })`** is an iframe of `` `/artifacts/${styleId}/?guide&type=document&v=${version ?? ''}` ``, `title="Style guide"`, full width and 640 px tall.
  - **The library:**
    - **Grids.** Templates and styles are grids (`grid-cols-2 lg:grid-cols-3`) of card buttons with `aria-pressed`. Each card is `<img loading="lazy" alt="">` of `api.thumbnailUrl` with `object-cover object-top`, at deck `aspect-video`, document `aspect-[210/297]`, page `aspect-[4/3]` and style `aspect-video`. `onError` swaps in a placeholder with the title's first letter.
    - **Selection.** A selected template shows Use template, Edit, Preview and Remove. A selected style shows `<StyleGuide>` under the grid, with Edit and Remove.
    - **Create template**: Name, Artifact type, `ReferencePicker` and Describe. **Add style**: Name, Base theme, `ReferencePicker`, Describe, and `<details>` "Start from CSS instead" with the existing import and textarea.
    - **Submit:**
      1. `api.savePreset` makes the draft.
      2. The text is the description, plus `\n\nReference links:\n- <url>` per link. When the description is empty and there are references, it is "Work out the visual language of these references and build the first version of this template." (or "... of this style.").
      3. `setPending(draft.id, { text, files })`.
      4. `navigate('/edit/<id>')`.
    - **The button** reads "Create with chat" for both.

- [x] **Step 1: Implement `api.ts`, `pending.ts`, `ReferencePicker.tsx`, `StyleGuide.tsx` and `Library.tsx`**

- [x] **Step 2: Check types, lint and build**

Run: `pnpm -C frontend typecheck && pnpm -C frontend lint && pnpm -C frontend build`
Expected: no errors.

- [x] **Step 3: Check it in the browser** with `make pg-start`, `make chrome-dev` and `make dev`:
  1. A saved template shows a thumbnail, and clicking it selects it and shows the actions.
  2. A saved style shows its guide, and the type links change the sizes.
  3. Six files are refused in the dialog.
  4. With `make chrome-dev` stopped, the cards show placeholders.

- [x] **Step 4: Commit**

```bash
git add frontend/app/src/api.ts frontend/app/src/pending.ts frontend/app/src/components/ReferencePicker.tsx frontend/app/src/components/StyleGuide.tsx frontend/app/src/components/Library.tsx CLAUDE.md
git commit -m "Show library thumbnails and the style guide, and start drafts from references"
```

---

### Task 8: The editor and chat for drafts

**Progress:** Draft Save/Discard, unload/in-app/back guards, reference uploads and guide previews are implemented. Editors remount by artifact ID; the shared Dialog ignores queued programmatic close events when reopened. The synthetic UI workflow and deterministic history tests verify these transitions.

**Files:**
- Create: `frontend/app/src/components/DraftBar.tsx`
- Modify: `frontend/app/src/router.ts`, `frontend/app/src/pages/Editor.tsx`, `frontend/app/src/Preview.tsx`, `frontend/app/src/chat/Chat.tsx`

**Interfaces:**
- Consumes: Task 7 (`api.ts`, `pending.ts`).
- Produces:
  - **`router.ts`.** `export function setNavigationGuard(guard: ((to: string) => boolean) | null): void`. `navigate` asks the guard first and stops when it returns `false`. On `popstate` with a guard set, a refused target pushes the previous path back.
  - **`DraftBar({ artifact, onSaved, onDiscarded }: { artifact: Artifact; onSaved: (entry: Artifact) => void; onDiscarded: () => void })`** holds a name input (the title by default, at most 200 characters), Save (primary, `api.saveDraft`; a 400 detail shows under it) and Discard (`api.discardDraft`, then `onDiscarded`).
  - **`Editor.tsx` for a draft:**
    - **The header** shows a "Draft" badge and the `DraftBar` in place of the access select.
    - **Leaving warns.** While the draft is open, a `beforeunload` handler calls `preventDefault()`, and a navigation guard opens a `Dialog` titled "Leave without saving?" with the text "This draft is deleted." and the buttons "Keep editing" and "Discard and leave". The latter discards, clears the guard and navigates.
    - **After Save**, the editor refetches the artifact and carries on with the saved entry, and the guard is cleared.
  - **Style drafts and entries** pass `guide` to `Preview` and hide the View / Rich / Raw toggle.
  - **`Preview`** gains `guide?: boolean`, with `src` `` `/artifacts/${id}/?guide&type=document&v=${version}` ``.
  - **`Chat`:**
    - The `isTemplate` prop becomes `draftKind: 'template' | 'style' | null`.
    - On mount it calls `takePending(artifactId)`, and when there is a value it sends `sendMessage({ text, files })` once a model is ready, with the files converted to `FileUIPart`s with data URLs through `FileReader`.
    - In a draft, a paperclip button (`<input type="file" multiple accept={ATTACH_ACCEPT}>`) and dropping files on the panel attach files to the next message, shown as removable chips and checked with `checkAttachments`. Ordinary chats have no paperclip.
    - Style drafts say "Describe your style" and "The agent builds the style and its guide beside the chat. Save it when it looks right."

- [x] **Step 1: Implement `router.ts`, `DraftBar.tsx`, `Preview.tsx`, `Chat.tsx` and `Editor.tsx`**

- [x] **Step 2: Check types, lint and build**

Run: `pnpm -C frontend typecheck && pnpm -C frontend lint && pnpm -C frontend build`
Expected: no errors.

- [x] **Step 3: Check it in the browser** with `make dev`, `make chrome-dev` and a configured model:
  1. **Starting.** Create a template from a PDF and a link. The editor opens, the first message carries the file, and the agent reports what it found before building.
  2. **Later attachments.** Attach a different logo in the chat and ask for it to be used.
  3. **Leaving.** The back arrow shows the dialog, "Discard and leave" returns home, and the draft is gone.
  4. **Reloading.** The browser warns, and after the reload the draft is still there.
  5. **Saving.** Save. The library lists the entry, and reloading the chat shows "Attached deck.pdf (PDF)." with no file.
  6. **Styles.** A style draft's preview is its guide.

- [x] **Step 4: Commit**

```bash
git add frontend/app/src/router.ts frontend/app/src/pages/Editor.tsx frontend/app/src/Preview.tsx frontend/app/src/chat/Chat.tsx frontend/app/src/components/DraftBar.tsx CLAUDE.md
git commit -m "Save or discard drafts in the editor and attach references in the chat"
```

---

### Task 9: The agent's guidance and automated verification

**Progress:** Reference deconstruction guidance, skill pointers and README/CLAUDE documentation are implemented. Scripted-model tests verify guidance and restyling without external providers.

**Files:**
- Create: `skills/openartifact-templates/references/deconstructing.md`
- Modify: `skills/openartifact-templates/SKILL.md`, `skills/openartifact/SKILL.md`, `backend/agent.py` (`skill_text`), `README.md`
- Test: `tests/test_chat.py`

**Interfaces:**
- Produces:
  - **`agent.skill_text()`** appends `deconstructing.md`, so every chat can restyle from a link.
  - **Both `SKILL.md` files** point at it, served as `skill://openartifact-templates/references/deconstructing.md`.
- The content of `deconstructing.md`, kept under about 500 words, with these headings in this order:
  1. **Look, then report.** Read every reference (`look_at_link` for links). Before building, report the palette with each colour's role, the fonts you will use, the logo and, for a template, the recurring layouts and sections.
  2. **Colours by role.** Map background, surface, body text, headings, accents and muted text onto the tokens in `references/styles.md`. Use the exact values from the facts when there are any.
  3. **Fonts.** Pick a free Google font of the same character (serif or sans, geometric or humanist, similar weight) and install it with `add_font`. Don't chase the exact name, and never copy a font file from a reference.
  4. **Logo.** Keep it with `keep_image` (over MCP, `upload_url`) at `assets/logo.<ext>`. A template places it in its page component, and a style places it with CSS on `.page.cover`. When you can't extract one, say so and ask for the file. The user's instruction wins.
  5. **Every form factor.** Set sizes per type with the selectors in `references/styles.md`, and check a style's guide with `screenshot`, pages 1 to 3.
  6. **Several references.** Say which one leads, and ask when they disagree.
  7. **Content.** Never reproduce a reference's words. Sections may follow its structure, filled with sample text.
  8. **What you couldn't read.** When a reference couldn't be read, or a link answered with an error, say so plainly and never imply you saw it. Attachments are available only in the turn they were sent, so write down what you need from them as you build.

- [x] **Step 1: Write the failing test** `tests/test_chat.py::test_agent_has_the_deconstructing_guide`: `info.instructions` contains `Look, then report` in an ordinary chat.

- [x] **Step 2: Run it and see it fail**

Run: `uv run pytest tests/test_chat.py -k deconstructing -v`
Expected: the regression tests exercise the implemented behavior. See implementation status for results.

- [x] **Step 3: Write `deconstructing.md`, the pointers and `skill_text()`, and update `README.md`**

- [x] **Step 4: Run everything**

Run: `make format && make lint && make test && pnpm -C frontend build`
Expected: all pass, with `tests/test_guide.py` run, not skipped, on a machine with Chrome.

- [x] **Step 5: Commit**

```bash
git add skills/ backend/agent.py README.md tests/test_chat.py CLAUDE.md
git commit -m "Teach the agent to work out a reference's style"
```

---

## Follow-up: Real-artifact evaluation

Deferred from Tasks 1 to 9, including live gateway PDF acceptance. Completing implementation requires the automated checks and focused browser checks above; evaluation with real reference artifacts is separate follow-up work.

- Check a small PDF through the gateway on one Claude and one OpenAI model, reporting unsupported input plainly.
- Use `make dev`, `make chrome-dev` and a configured model. Start with one real public website and one PowerPoint deck, then extend to a PDF report and Word document.
- For each reference, create a style and a template in a different form factor. Apply the saved style to a deck, document and page containing representative headings, body text, code and a cover.
- Compare the reference with rendered artifacts and guides in Chrome, and check a PDF export. Check colour roles, typography and hierarchy, logo placement, font loading, and clipping or overflow in all three form factors. Compare guide values with specimen computed values at the tested viewport.
- In an ordinary artifact's chat, paste the website's link and ask for it to look like the site.
- Record extracted facts, chosen font substitutes, screenshots and mismatches in the follow-up report. Check whether website declarations describe the visible site and whether PowerPoint themes miss local overrides. Use those findings to decide whether extraction needs refinement. Report inaccessible references and extraction gaps plainly.
- Keep reference files out of committed fixtures unless explicitly intended for the repository.
