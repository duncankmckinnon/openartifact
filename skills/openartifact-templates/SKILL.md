---
name: openartifact-templates
description: Use when creating or refining a reusable OpenArtifact template from a description, or saving a reusable layout and style for future decks, documents or pages.
---

# Reusable template authoring

For files and links, follow [Working from visual references](references/deconstructing.md), also served as
`skill://openartifact-templates/references/deconstructing.md`.

Create a working starting point the user can reuse. Its markdown, configuration, components, CSS and assets
form the template. The user describes and refines it beside the live preview.

In OpenArtifact's template editor, work on the current artifact: it is an unsaved draft that the user keeps by pressing Save; never say it is saved.
For external MCP clients, `new_template` and `new_style` start drafts and `save_draft` keeps one when the user says so. `save_preset(..., kind="template")` snapshots an artifact,
and `list_presets` and `new_from_template` find and reuse them. Copies retain their type and independent files.

## Clarify and preserve the brief

Read the existing files and conversation. Carry forward decisions already made, including the selected
artifact type. Identify the purpose, audience, required sections, page count, reusable fields, visual cues,
references and explicit exclusions that the user actually supplied.

When the description leaves the main content or structure open, ask one focused question before choosing
sections, metrics or a page count. For example, "Which sections should customers receive in each monthly
report?" Ask about a reference you cannot access; never imply you inspected it. Do not repeat answered
questions or turn minor visual choices into a questionnaire.

Once enough is known, summarize what you will build in one or two sentences, distinguishing user requirements
from your proposed defaults, then build the preview. A specific brief needs no extra approval round. If the
user delegates choices, state your assumptions and proceed. Choose reasonable defaults for spacing,
typography and other details that preserve the requested structure.

## Build and check against the brief

Use the OpenArtifact authoring guide for syntax and its style reference for CSS tokens. Match the selected
type, requested sections and page limits. Use concise sample content and label example metrics as samples.
Declare every reusable uppercase placeholder, such as `{{ TEAM }}` or `{{ PERIOD }}`, with a useful sample
value in `artifact.toml`'s `[context]` table. The unfilled template must build successfully.

Use a page component for repeated headers, footers and counters, with exactly one `{{ CONTENT }}`.
Use parameterized components for repeated layouts. Keep required images and fonts in the artifact;
relative asset URLs resolve from its root.

Write files with `run_code`, call `build`, fix errors, and inspect representative pages with `screenshot`,
including the densest page. Check the result against every explicit requirement and exclusion. If a
requirement cannot be met, explain the limitation instead of silently substituting something else.

For revisions, preserve the agreed brief and change the requested part. "More engaging" can improve hierarchy
and rhythm while retaining sections, page count and exclusions. Explicit new instructions update the brief;
do not ask the user to approve that same decision again. Clarify only unresolved contradictions, such as
"keep two pages and add a third," or missing assets. Finish with what changed, what users replace, and where
to reuse it.

`save_preset(..., kind="style")` saves CSS, its local images/WOFF fonts and base theme separately. Combine CSS
imports first. Applying a style preserves content and components. Template edits affect future copies only.
