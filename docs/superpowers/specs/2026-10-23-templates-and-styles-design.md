# Personal templates and styles

## Purpose

Let a signed-in user keep reusable starting points and visual styles, then use them from the web app or MCP without rebuilding the same files each time.

## Proposed behavior

- Create a template from a plain-language description within OpenArtifact. The user chooses an artifact type and opens a dedicated template editor, describes the desired structure, visual style and reusable sections in chat, and watches the preview update. The existing configured model and streaming editing agent generate and refine the files; the result is already in the user's template library.
- Add a dedicated template-authoring skill to OpenArtifact's bundled skills. Load it automatically for chats editing template library entries, and expose it through MCP so connected agents can follow the same workflow. It guides reusable sample content, valid context placeholders, components, CSS tokens, page layouts, and build/screenshot verification. Ordinary artifact chats retain their current behavior.
- Save any artifact the user can view as a named, private template. Save a fresh snapshot of its current source files, including markdown, configuration, components, images and fonts, without its history or chat. The source is unchanged.
- Create a new artifact from a saved template. Copy its files into a new artifact repository, retain its artifact type, and allow a new title and replacement markdown. Each result is independent: later template changes do not change artifacts already created from it.
- Save an artifact's stylesheet and base theme as a named, private style. Include local files referenced by CSS, such as images and fonts, but exclude the artifact's markdown and components. Also allow creating a style by pasting CSS or choosing a local CSS file.
- Apply a saved style when creating an artifact or from an existing artifact's editor. Replace the current stylesheet and base theme, preserving content, components, context and artifact type. Copy style assets into a unique directory and rewrite their CSS URLs so existing assets are never overwritten.
- On the home screen, show a personal library with templates and styles alongside the existing new-artifact choices. Templates can start a new artifact; styles can be previewed and edited using the existing artifact editor. Library entries can be removed from the library without deleting any artifact or its history.
- In the editor, provide a compact dialog to save the current artifact as a template or style, or apply an existing style. Report errors and refresh the preview after application.
- Provide equivalent MCP tools for listing, saving, creating from and applying library entries, and document their use.

## Implementation choices

These are proposed defaults, not additional user requirements.

- Keep React, FastAPI, Postgres, the current builder and the current artifact source format. Add no package dependencies.
- Template creation uses the existing model configuration, permissions and chat history. A missing model is shown clearly through the existing model picker; creating a template does not require adding another provider or background job. The template editor explains that chat creates a reusable template and encourages a concrete description.
- Library entries are ordinary, private artifact snapshots with an optional `preset_kind` metadata field (`template` or `style`). This uses the existing versioned storage and editor. The API and UI identify library entries separately from ordinary artifacts.
- Style snapshots contain a small preview page, normalized configuration, one stylesheet, and its referenced local assets. They do not contain the source artifact's content or history.
- Template snapshots preserve configuration, including custom source paths, page components and context. Change top-level TOML settings without changing table values with the same name.
- All source writes use `workspace.edit()`; creation, copying, validation and metadata updates commit atomically. Invalid saves or style applications roll back. Derived `dist/` files and git metadata are never copied.
- Library lookup is scoped to the caller's workspace even when a backing artifact is public. Saving from another artifact still requires normal view permission; applying to an artifact requires normal edit permission.
- Reject symlinks and paths escaping an artifact during copying. Local CSS imports must be copied with their referenced assets, or fail with a clear error when unsupported; never silently produce a broken style.
- Library entries remain private by default. Shared organization libraries, live inheritance, a visual CSS editor, and importing complete template archives are outside this first implementation.

## Verification

Cover snapshot independence, custom source paths, preservation of template files, content-free style snapshots, CSS asset copying and collision handling, invalid input rollback, personal library isolation, web mutation access checks, MCP workflows, template-specific skill loading, and description-driven template editing through a scripted model. Build the frontend and run the repository-required `make format`, `make lint`, and `make test`. Exercise the library UI in a browser if the local services are available.

## Agreed scope

The user selected the full personal library plus template creation from descriptions on 2026-10-23. The original design passed a fresh builder review. The new workflow uses the existing editor and configured agent with an additional bundled skill; it does not add a separate generation service.

The user subsequently prioritized how the template skill clarifies and follows descriptions. It asks a focused question when the main content or structure is unclear, summarizes explicit requirements separately from proposed defaults, and proceeds from a sufficiently specific brief. Revisions preserve the agreed requirements; explicit new instructions update the brief without another approval round. The skill checks the resulting template against the brief and reports unmet requirements.
