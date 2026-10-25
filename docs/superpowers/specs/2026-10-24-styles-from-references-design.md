# Templates and styles from references

## Intent

People usually already have something that looks right: a brand deck, a PDF report, a Word document, a company
website. At the moment the library's creation flows start only from text: "Create template" takes a written description
and "Add style" takes pasted CSS. This feature lets a user give OpenArtifact a **reference** instead. The agent works out
its visual language and rebuilds it as an OpenArtifact template or style that works in **any form factor**. That
language covers the colours and how each one is used, the fonts, the text levels and sizes, the logo and the recurring
layouts. A PowerPoint deck can become a document template, and a website can become a deck style.

The result is developed in conversation: the agent shows what it found, builds a first version beside a live preview
and revises it from the user's feedback. It joins the library only when the user saves it.

This builds on the personal library described in `2026-10-23-templates-and-styles-design.md` (templates and styles as
private artifact snapshots with `preset_kind`, the template-authoring skill, the editor's chat).

## Goals

1. Both creation flows accept references: files (PDF, PowerPoint `.pptx`, Word `.docx`) and links to public web
   pages. One draft can have more than one reference, such as a deck and a website.
2. The agent works out from the reference:
   - **Colours and their roles**: page background, surfaces, body text, headings, accents, muted text. This means
     where each colour is used, not just a list of values.
   - **Fonts** for headings, body and code, each replaced by the closest free font when the original needs a licence.
   - **Text levels and sizes**: title, heading levels, body, small text and code, with size, line height and weight.
   - **The logo**.
   - **Recurring layouts** (for templates): covers, section dividers, headers and footers, callouts, card grids,
     figure and table treatments, spacing rhythm.
3. The output's form factor is chosen independently of the reference's own form. A style works on decks, documents and
   pages alike.
4. Templates and styles are developed interactively, as drafts, and are kept only when the user saves them.
5. The library shows each template as a selectable thumbnail of its first page.
6. Selecting a style shows its **style guide**: the colour scheme, the fonts and every text level with its size,
   switchable between deck, document and page.
7. In an ordinary artifact's chat, "make it look like our site" works when the user gives a link.
8. Agents connected over MCP can do the same.

## Non-goals

- Dropping files into an ordinary artifact's chat. Only links work there.
- Keynote files. The user exports them to PDF first.
- Pages behind a login, and private Google Slides or Docs. The user downloads these as PDF first.
- Copying a reference's paid fonts.
- Keeping reference files after the draft ends.
- Carrying the reference's actual text into a template. Templates get sample content, as they do now.
- Shared organisation libraries. These are unchanged from the previous design, so the library stays personal.

## Anti-goals

The feature fails if any of these happen, even if it technically works:

- A style has the right colours in the wrong roles, such as the accent used as the page background.
- The agent implies it inspected a reference it couldn't open, such as a link that answered with a login page, a
  corrupt file or a timeout. It must say so plainly.
- The user's documents are kept after the draft ends: in the artifact's files, its git history, the object store or a
  forgotten temporary folder.
- A paid font file ends up in a style.
- A link the user gives can make the server or the Chrome service reach a private or internal address.
- A style only looks right in the reference's own form factor. A deck style must also make a sensible document and
  page.
- The style guide shows sizes or colours that differ from what the style actually renders.

## Behaviour

### Starting from a reference

The **Create template** dialog has these fields:

- Name
- Make it a: Deck, Document or Page
- Reference (optional): a drop zone for one or more files, and a field for one or more links
- Describe your template

The description is optional when there is a reference. "Create with chat" opens the editor on a new draft. A template
made from a description alone still works as it does now, except that it is now a draft.

The **Add style** dialog has a name, references and an optional description. Pasting or importing CSS still works, and
that path also opens a draft. Every way of creating a style opens the editor on a draft whose preview pane is the style
guide.

### What the agent does

1. **It looks at the reference.** It sees pictures of the pages. Where the file holds exact values, it also reads them:
   theme colours, fonts and sizes from a PowerPoint or Word file, font names from a PDF, and colours, font families,
   `@font-face` rules and custom properties from a web page's CSS.
2. **It reports what it found before building**: the palette with the role of each colour, the fonts and their free
   substitutes, the logo it will use and, for a template, the recurring layouts it will reproduce. If a reference can't
   be opened, it says which one and why.
3. **It builds a first version** in the chosen form factor. For a style, it maps the colours onto the CSS token
   contract (`references/styles.md`) by role, sets text sizes for each form factor and installs the fonts and the logo.
   For a template, it also builds the page component and components for the recurring layouts, and fills them with
   sample content.
4. **It revises from feedback.** The template-authoring skill's rules carry over: one focused question when something
   essential is unclear, keeping the agreed brief through revisions, and checking the result against it with
   screenshots.
5. **It suggests saving** when it thinks the work is done. It never saves on its own.

*My call:* when a template has a reference but no description, the reference's structure suggests the sections, such
as a deck's agenda, market, team and asks slides. The agent fills them with sample text, never the reference's own
words, and names them in its report so the user can change them. When there are several references and they disagree,
such as a deck in navy and a website in black, the agent says so and asks which one leads.

To keep a matching style from a template made from a reference, the user saves the template as a style with the
editor's existing save dialog. Nothing new is needed for that.

**Fonts.** When the original font needs a licence, the agent uses the closest free font (open licence, such as OFL or
Apache) and stores its WOFF2 files in the style, as saved styles already require. The style guide names both, for
example "Söhne in the original, Inter here". When the original font is itself free, the agent uses it.

**Logo.** The logo carries over by default. A template places it in its page component or components, such as on
covers and in headers. A style keeps it as an asset its CSS places, such as on covers. Anything the user says in chat
wins: "no logo", or "use this one instead" with a file dropped into the draft's chat.

**Sizes in every form factor.** A deck heading is much larger than a document heading, so a style sets text levels for
each of deck, document and page. At the moment heading sizes are fixed in each type's stylesheet (`deck.css`,
`prose.css`) rather than exposed as tokens. The builder decides whether to add size tokens to the CSS contract or have
styles override sizes with type-scoped selectors, and documents the result in `references/styles.md`.

### Drafts

The rule is that **unsaved means gone**.

- Creating a template or style opens a draft, whatever it starts from (references, a description or pasted CSS).
- A draft is visible only to its creator, through the editor. It appears in no list: not on the home screen, not in
  the library and not in MCP's `list_artifacts` or `list_presets`.
- **Save** in the editor header, with the name editable, adds the draft to the library. **Discard** deletes it.
- Leaving the editor with an unsaved draft brings up the browser's leave-page warning. If the user leaves anyway, the
  draft is deleted.
- *My call:* a draft that ends without a clean exit, such as a crashed tab or an MCP session that never saved, is
  deleted 24 hours after its last change.
- Deleting a draft removes its row, its bundles in the object store, its checkout, its chat and any reference files
  held for it.
- *My call:* reopening a **saved** entry to refine it follows the same rule. Changes are made on a draft of the entry,
  replace the entry only on Save, and are dropped if the user leaves without saving. At the moment library entries are
  edited in place, so this is a change.
- Saving an existing artifact as a template or style from the editor's save dialog is unchanged, because it is already
  an explicit save.
- Ordinary artifacts are unchanged: every edit is a commit.

### References are pointers, not stored copies

- **A link stays a link.** The agent opens the page whenever it needs to look, and nothing is downloaded and kept.
  Public Google Slides and Docs links are fetched through their PDF export (*my call*).
- **A file dropped in the web app** has to reach the server for the agent to see it. It is held outside the artifact's
  files and history and tied to the draft. It is deleted when the draft is saved, discarded or swept. It is never
  committed and never copied into artifacts made from the entry. The only parts of a reference that the entry keeps
  are the ones the agent deliberately copies in, such as the logo, and these become ordinary files of the entry.
- **An agent connected over MCP reads the user's files where they are.** It opens local files with its own tools and
  uploads none of them. Only what the entry keeps (the logo, and font files if it fetched them itself) goes up through
  `upload_url`. For links, it can use the server's tool for looking at references.
- **Limits** (*my call*): up to 50 MB per file and up to five references per draft. Files can also be dropped into a
  draft's chat later, such as a different logo.
- The library records only where an entry came from (the file name or the link's host) to show "from
  harbor-annual-report.pdf" on its card (*my call*).

### The library

This matches the approved mockup.

**Templates** appear as a grid of cards. Each card has:

- a thumbnail of the template's first page, at its type's shape (16:9 for a deck, A4 for a document, the top of a page
  for a page)
- the title and the type
- "from ..." when the template came from a reference

Clicking a card selects it, and the selected card shows Use template, Edit, Preview and Remove. A thumbnail always shows
the latest saved version and is redrawn when the entry changes. Thumbnails are cached, so loading the library doesn't
ask Chrome for a picture every time.

**Styles** appear as cards with:

- a strip of the palette's colours
- "Aa" in the heading font, with the name
- the font names
- the origin

Selecting a style shows its style guide.

### The style guide

The style guide is shown when a style is selected in the library, and as the preview pane while a style is edited,
whether it is a draft or saved. From the approved mockup it has:

- **a header**: the style's name and a Deck / Document / Page toggle
- **the colour scheme**: for each colour, its swatch, name, hex value and what it is used for ("Covers, headings",
  "Accent, rules, key figures")
- **fonts** for headings, body and code: an "Aa" sample, the family, what it is used for, and the original font when it
  was substituted
- **levels and sizes**: Title, Heading 1 to 3, Body, Small and Code, each with a live sample and its size, line height
  and weight (plus case or letter spacing where it matters), for the selected form factor

The guide is drawn with the style's own CSS and fonts. Its sizes are **measured** from what the style renders in each
form factor, not typed by the agent, so the guide can't disagree with the style. The names, roles, usage notes and
original-font names are written by the agent alongside the style.

Every style gets a guide, whether it came from a reference, pasted CSS or an artifact. A style without the agent's
notes uses the token names as labels, such as "Accent" and "Heading text".

### "Make it look like our site" in any chat

In an ordinary artifact's chat, the user pastes a link and asks for the artifact to be restyled. The agent has the same
abilities to look at links and to install fonts and the logo. It restyles `styles.css`, the base theme, the fonts and
the logo, and keeps the content, components and type. Every change is a commit, as usual. Files can't be dropped into
an ordinary chat.

### Over MCP

External agents get the same flow:

- `new_template` and `new_style` start drafts, from a description or from references the agent has looked at.
- The agent refines a draft with `run_code`, `build` and `screenshot`, looks at links through the server's reference
  tool and reads local files with its own tools.
- It uploads kept assets with `upload_url`.
- It saves to the library with a save tool, only when the user says to.

`backend/instructions.md`, `skills/openartifact/SKILL.md` and `skills/openartifact-templates/SKILL.md` describe the
reference workflow. The guidance on working out a style from a reference applies to both the editor's agent and
external agents.

## Constraints

- The repository's rules in `CLAUDE.md` hold:
  - `build.py` and `chrome/pdf.py` stay dependency-free.
  - Every change to an artifact goes through `workspace.edit()`.
  - The runtime stays synchronous.
  - The Chrome service stays internal.
  - No em dashes in source or docs.
  - `make format`, `make lint` and `make test` pass.
- **Link safety.** The Chrome service prints any URL it is given, which is why it is internal. Fetching user-supplied
  links through it, or fetching a page's CSS or font files from the application server, must not reach private,
  loopback, link-local or cloud-metadata addresses, including after redirects and DNS changes. The builder chooses the
  mechanism.
- **Untrusted office files.** Conversion runs isolated (in the Chrome container, not the application server), never
  runs macros, and is bounded by time and size.
- **The sandbox has no network.** `run_code` cannot fetch font files or copy anything out of a held reference, so
  those must be tools.
- **Saved styles hold only local files.** `styles.py` accepts local images and WOFF / WOFF2 fonts in saved styles and
  rejects `@import`, so fonts must be downloaded into the style rather than linked from a font service.
- **Open licences only.** Only open-licence fonts are downloaded.
- **One instance.** Production runs one instance with a persistent disk (`render.yaml`), so held reference files can
  live on that disk.
- **Image-capable models.** The agent's model must accept images. Every configured model already does, because
  `screenshot` relies on it.

## How it is made (my calls)

- **Converting references.** LibreOffice in headless mode turns PowerPoint and Word files into PDFs, and poppler
  (`pdftoppm`, `pdffonts`) turns PDF pages into pictures and lists their fonts. Both are added to `chrome/Dockerfile`
  and exposed as new internal endpoints on the Chrome service, which makes the image a few hundred MB larger. Chrome
  screenshots links.
- **Exact values.** These come from `python-pptx` and `python-docx`, which the exports already depend on, for theme
  colours, fonts and sizes, and from `tinycss2`, already a dependency, for a page's CSS.
- **Seeing the reference.** The agent gets a tool to look at a reference page by page, as `screenshot` does for
  artifacts, along with the exact values found for it.
- **Fetching fonts.** Free fonts come from an open-licence catalogue such as Google Fonts, through a tool that writes
  the font files into the artifact.

## Left to the builder

- Tool names and signatures for looking at references, fetching fonts and copying an image (the logo) from a reference
  into an artifact.
- How drafts are stored (for example a column on `artifacts`, or `preset_kind` with a saved flag), how a draft of a
  saved entry is represented (a temporary copy, or a branch in the entry's repository), and how the 24-hour sweep runs.
- Where held reference files live and how they are tied to a draft.
- The format of the agent's notes for the style guide (colour names, roles, usage, original fonts) and of the origin
  shown on cards.
- How sizes become per form factor (size tokens or type-scoped selectors) and how the guide measures them for all three.
- Thumbnail size, format and caching.
- How the agent handles long references, such as a contact sheet of every page so it can pick representative ones.
- How the agent chooses a substitute font and finds the logo, which goes in the skill's guidance.
- The mechanism for link safety.
- UI details beyond the mockup, such as how references show in the dialog and in the chat, and how the style picker
  in "Use template" previews a style.

## Verification

- **Drafts:**
  - not listed anywhere
  - saving adds the draft to the library
  - discarding, and the sweep, delete the row, bundles, checkout, chat and held files
  - refining a saved entry changes it only on Save
- **References:**
  - each kind (PDF, PPTX, DOCX, link, Google Slides export) converted and shown to the agent through stubbed
    binaries, as `tests/test_chrome.py` stubs Chrome
  - a reference that can't be opened is reported as such
  - held files are gone after save and after discard
- **Link safety:** private, loopback and metadata addresses refused, directly and through redirects.
- **Chat:** scripted `FunctionModel` runs that look at a reference, install a font and a logo, build and save, for a
  template, for a style and for "make it look like our site" in an ordinary chat.
- **Library:** thumbnails present and redrawn after a save, and every style showing a guide whose sizes match the
  rendered page in each form factor.
- **MCP:** a draft created, refined and saved, and an unsaved one swept.
- **End to end:** a real PowerPoint, PDF, Word file and website, each turned into a style and into a template of a
  different form factor, compared by screenshot with the reference.
- The repository's `make format`, `make lint` and `make test`, and `pnpm -C frontend build`.
