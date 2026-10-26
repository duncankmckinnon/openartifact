# Templates and styles from references

## Intent

People usually already have something that looks right: a brand deck, a PDF report, a Word document, a company
website. At the moment the library's creation flows start only from text: "Create template" takes a written description
and "Add style" takes pasted CSS. This feature lets a user give OpenArtifact a **reference** instead. The agent works out
its visual language and rebuilds it as an OpenArtifact template or style that works in **any form factor**. That
language covers the colours and how each one is used, the fonts, the text levels and sizes, the logo and the recurring
layouts. A PowerPoint deck can become a document template, and a website can become a deck style.

The result is developed in conversation, beside a live preview, and joins the library only when the user saves it.

This builds on the personal library in `2026-10-23-templates-and-styles-design.md` (templates and styles as private
artifact snapshots with `preset_kind`, the template-authoring skill, the editor's chat). OpenArtifact is already a
working product and this is an addition to it, so the design reuses what exists and keeps new machinery small.

## Goals

1. Both creation flows accept references:
   - files: PDF, PowerPoint `.pptx`, Word `.docx` and images
   - links to public web pages

   One draft can have several references.
2. The agent works out the reference's palette with the role of each colour, its fonts, text levels and sizes, its logo
   and, for templates, its recurring layouts.
3. The output's form factor is chosen independently of the reference's form, and a style works on decks, documents and
   pages alike.
4. Templates and styles are drafts until the user saves them.
5. The library shows each template as a selectable thumbnail of its first page.
6. Selecting a style shows its style guide: the colour scheme, the fonts and every text level with its size, switchable
   between deck, document and page.
7. In any artifact's chat, "make it look like our site" works when the user gives a link.

## Non-goals

- Pictures of web pages. The agent reads a link's HTML and CSS, not a screenshot.
- Pictures of PowerPoint or Word slides and pages. The agent gets their exact theme values and embedded images. For the
  layouts, the user adds a PDF export.
- Keynote files, pages behind a login, and private Google files. The user exports these to PDF.
- Exact font matching (see Fonts).
- Keeping references after the turn they were given in.
- Carrying the reference's own text into a template. Templates get sample content, as now.
- Draft copies of saved entries. Refining a saved entry edits it in place, as now.
- Files in an ordinary artifact's chat. Only links work there.

## Anti-goals

The feature fails if any of these happen, even if it technically works:

- Colours land in the wrong roles, such as the accent used as the page background.
- The agent implies it inspected a reference it couldn't read, such as a link that answered with an error or a login
  page.
- The user's files are kept: in the artifact, its history or the stored chat.
- A link the user gives can make the server reach a private or internal address.
- A style only looks right in the reference's own form factor.
- The style guide shows sizes or colours that differ from what the style renders.

## Behaviour

### Giving references

The **Create template** dialog has a name, "Make it a" (Deck, Document or Page), a drop zone for files, a field for
links, and the description. The description is optional when there are references.

The **Add style** dialog has the same reference fields, plus the existing paste or import of CSS.

"Create with chat" makes a draft and opens the editor. The first chat message carries the description, the links as text
and the files as attachments.

In a template or style draft, files can also be attached to any later chat message, such as a different logo. In an
ordinary artifact's chat, the user pastes a link and asks.

### What the agent receives

- **PDFs and images** go to the model as they are. Claude and the OpenAI models read both.
- **PowerPoint and Word files** are unzipped on the server. The model gets a text summary of the exact values instead
  of the file:
  - the theme colours
  - the heading and body fonts
  - for PowerPoint, the slide size and count
  - for Word, the sizes and fonts of Title, Heading 1 to 3 and Normal

  The model also gets the embedded images as pictures, which is where the logo usually is.
- **SVG images** go as text, since models don't take SVG pictures.
- **Each attachment** is labelled with its file name, so the agent can refer to it.
- **Links** are text in the message. The agent reads one with a tool that fetches the page and its stylesheets. The
  tool returns the title, the CSS custom properties, the font families, the most used colours (with the selectors that
  use them) and the logo candidates (images marked as a logo, icons, the social image). The fetch refuses private and
  internal addresses, at every redirect too, using pydantic-ai's SSRF-safe downloader. A page that answers anything but
  200 is reported as such.

### What the agent does

1. Looks at every reference and reports what it found before building: the palette with each colour's role, the fonts
   it will use, the logo and, for a template, the recurring layouts and sections.
2. Builds a first version in the chosen form factor. It maps colours onto the CSS token contract by role and sets text
   sizes for each form factor. For a template, it also builds a page component and components for the recurring layouts,
   with sample content.
3. Revises from feedback, keeping the agreed brief, as the template-authoring skill already describes.
4. Suggests saving when it thinks the work is done, and never saves on its own.

When there is a reference but no description, the reference's structure suggests the template's sections, filled with
sample text and never the reference's own words. When references disagree, the agent says so and asks which one leads.
To keep a matching style from a template, the user saves the template as a style with the editor's existing save dialog.

**Fonts.** Matching the exact font doesn't matter much: people rarely notice a substitute of the same character. What
does matter is that a style carries its font files, since saved styles can only use files stored in them. Without
them, the artifact looks different on every machine and in the PDF export. The agent picks a free Google font of the
same character (serif or sans, geometric or humanist, similar weight) and installs it with a tool that downloads it into
the artifact.

**Logo.** The logo carries over by default. The agent keeps an attached image, an image embedded in a PowerPoint or Word
file, or a logo candidate from a link, with a tool that writes it into the artifact. A template places it in its page
component, and a style places it with CSS, such as on covers. Anything the user says wins. When no logo can be
extracted, such as one drawn inside a PDF, the agent says so and asks for the file.

**Sizes in every form factor.** A style sets text sizes per form factor with type-scoped selectors, which win over the
type's own stylesheet. These are `.deck .page h1`, `.artifact-document .prose h1` and `.artifact-page .prose h1`, with
covers as `.page.cover h1`. They are documented in `references/styles.md`.

### References are used, then gone

- **Attachments.** The model sees them during the turn they arrive in. When the chat is stored, the attachments are
  dropped and only the label ("Attached brand.pdf") stays. Later turns rely on what the agent already wrote down and
  built.
- **Links** are fetched when the agent looks, and nothing is stored.
- **What the entry keeps** is only what the agent deliberately writes into it: the logo and the font files.
- **Limits:** up to five attachments per message, 20 MB in total and 5 MB per image, which keeps a request within the
  providers' limits.

### Drafts

- Creating a template or style makes a draft, from references, a description or pasted CSS. A draft is visible only to
  its creator and appears in no list.
- **Save** in the editor (with the name) adds it to the library. **Discard** deletes it. Leaving the editor with an
  unsaved draft warns, and the in-app warning's "Discard and leave" deletes it.
- A draft left behind, after a closed tab or an MCP session that never saved, is deleted after 24 hours without a
  change.
- After saving, the editor carries on with the saved entry, edited in place as library entries are now.
- Saving an existing artifact as a template or style from the editor's save dialog stays an immediate save.

### The library

**Templates** appear as a grid of cards. Each card has a thumbnail of its first page at the type's shape, the title and
the type. Clicking a card selects it, and the selected card shows Use template, Edit, Preview and Remove.

**Styles** appear as cards with a thumbnail of the top of their style guide. Selecting one shows the full guide below
the grid.

Thumbnails are cached per version, so the library doesn't ask Chrome for a picture on every load. Without the chrome
service, cards show a placeholder.

### The style guide

This matches the approved mockup. It is shown when a style is selected in the library, and as the preview while a style
is edited. It has:

- a header with the style's name and a Deck / Document / Page toggle
- the colour scheme: a swatch, a role name ("Background", "Accent", "Headings") and the hex value for each colour token
- the heading, body and code fonts
- the levels Title, Heading 1 to 3, Body, Small and Code, each with a live sample and its size, line height and weight
  for the selected form factor

The guide is drawn by the runtime with the style's own CSS and fonts, and its values are **measured** from what renders,
so it can't disagree with the style. Every style gets one, however it was made. The agent's `screenshot` of a style shows
its guide, with pages 1 to 3 for deck, document and page, so it can check its work in each form factor.

### Over MCP

`new_template` and `new_style` start drafts, and `save_draft` keeps one when the user says so. External agents read the
user's files and links with their own tools, upload what the entry keeps with `upload_url`, and install fonts with
`add_font`. The skills describe the workflow for both.

## Constraints

- The repository's rules in `CLAUDE.md` hold:
  - `build.py` stays dependency-free.
  - Every artifact change goes through `workspace.edit()`.
  - The runtime stays synchronous.
  - No em dashes.
  - `make format`, `make lint` and `make test` pass.
- **The SSRF-safe downloader is private API.** `pydantic_ai._ssrf.safe_download` is pinned by the exact
  `pydantic-ai-slim` version in `pyproject.toml`. A test imports it, so an upgrade that moves it fails loudly.
- **Fonts come only from Google Fonts.** They are all open-licensed, and only `fonts.googleapis.com` and
  `fonts.gstatic.com` are contacted.
- **Saved styles hold only local files.** They accept local images and WOFF / WOFF2 fonts and reject `@import`
  (`styles.py`), so fonts are downloaded into the artifact.
- **Images must be readable by the model.** The agent's model must accept images and PDFs. Every configured model
  accepts images. Accepting PDFs through the gateway is checked first, while building.

## How it is made (my calls)

- **Chat attachments** use the AI SDK's file parts, which the existing adapter turns into model input. The server
  rewrites PowerPoint, Word and SVG parts before the run, and strips binary parts before storing the chat.
- **The agent's new tools:**
  - a link reader and a "keep this image" tool, both pydantic-ai function tools on the editing agent, since attachments
    live in the run
  - `add_font`, an MCP tool, so external agents have it too
- **The style guide** is a runtime mode of the style's own page (`?guide&type=`).
- **Thumbnails** are chrome-service screenshots at half scale, cached per head sha.
- **Drafts** are a `draft` column on `artifacts`, with a sweep in the server's lifespan.

## Left to the builder

- Tool names and signatures.
- How the dialog's files reach the editor's first message.
- The exact facts layout.
- The thumbnail cache's location.
- UI details beyond the mockup.

## Verification

- **Drafts:** unlisted, saved, discarded, swept after 24 hours; saved entries untouched by the sweep.
- **Attachments:**
  - PowerPoint and Word files become a facts summary and images
  - SVG becomes text
  - stored chats keep no attachment bytes
  - the limits are enforced
  - files on an ordinary artifact are refused
- **Links:** the reader's facts from a stub page, private addresses refused, and a non-200 status reported.
- **Fonts:** downloads only from Google's hosts, and the CSS builds.
- **Chat:** scripted-model runs for a template from a PowerPoint file, a style from a link, and "make it look like our
  site" in an ordinary chat.
- **Library:** thumbnails rendered once per version, and the style guide's measured sizes in each form factor (real
  Chrome where available).
- **End to end:** a real deck, PDF, Word file and website, each turned into a style and into a template of a different
  form factor.
