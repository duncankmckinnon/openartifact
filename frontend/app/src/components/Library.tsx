/** Personal templates, styles and transient reference-driven creation. */
import { BookOpen, Palette, Plus } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { type Artifact, type ArtifactType, api, checkAttachments, type Presets, type Theme } from '../api.ts'
import { setPending } from '../pending.ts'
import { navigate } from '../router.ts'
import { ReferencePicker } from './ReferencePicker.tsx'
import { StyleGuide } from './StyleGuide.tsx'
import { Button, Dialog, Field, LinkButton, Select, Spinner } from './ui.tsx'

const INPUT = 'w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm outline-none focus:border-accent'
const EMPTY: Presets = { templates: [], styles: [] }

function StyleSelect({
  styles,
  value,
  onChange,
  id,
}: {
  styles: Artifact[]
  value: string
  onChange: (value: string) => void
  id: string
}) {
  return (
    <Select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">Keep current style</option>
      {styles.map((style) => (
        <option key={style.id} value={style.id}>
          {style.title}
        </option>
      ))}
    </Select>
  )
}

function LibraryCard({ entry, selected, onSelect }: { entry: Artifact; selected: boolean; onSelect: () => void }) {
  const [failed, setFailed] = useState(false)
  const aspect =
    entry.preset_kind === 'style' || entry.type === 'deck'
      ? 'aspect-video'
      : entry.type === 'document'
        ? 'aspect-[210/297]'
        : 'aspect-[4/3]'
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      className={`overflow-hidden rounded-lg border bg-bg text-left ${selected ? 'border-accent ring-1 ring-accent' : 'border-line'}`}
    >
      {failed ? (
        <div className={`${aspect} flex items-center justify-center bg-raised text-3xl text-muted`}>
          {entry.title[0]}
        </div>
      ) : (
        <img
          className={`${aspect} w-full object-cover object-top`}
          loading="lazy"
          alt=""
          src={api.thumbnailUrl(entry)}
          onError={() => setFailed(true)}
        />
      )}
      <div className="p-2">
        <div className="truncate text-sm font-medium">{entry.title}</div>
        <span className="text-xs text-muted">{entry.preset_kind === 'style' ? 'Style' : entry.type}</span>
      </div>
    </button>
  )
}

export function Library({ entries, refresh }: { entries: Presets; refresh: () => Promise<void> }) {
  const [mode, setMode] = useState<'template' | 'style' | 'use' | null>(null)
  const [template, setTemplate] = useState<Artifact | null>(null)
  const [selectedTemplate, selectTemplate] = useState<string | null>(null)
  const [selectedStyle, selectStyle] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [type, setType] = useState<ArtifactType>('deck')
  const [brief, setBrief] = useState('')
  const [css, setCss] = useState('')
  const [theme, setTheme] = useState<Theme>('light')
  const [style, setStyle] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [links, setLinks] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const open = (next: 'template' | 'style' | 'use', entry?: Artifact) => {
    setName(next === 'use' ? `${entry?.title ?? 'Template'} copy` : '')
    setBrief('')
    setCss('')
    setStyle('')
    setFiles([])
    setLinks([])
    setError(null)
    setTemplate(entry ?? null)
    setMode(next)
  }
  const submit = async () => {
    const invalid = checkAttachments(files)
    if (invalid) {
      setError(invalid)
      return
    }
    setBusy(true)
    setError(null)
    try {
      if (mode === 'use' && template) {
        const created = await api.create({ template_id: template.id, title: name, style_id: style || undefined })
        navigate(`/edit/${created.id}`)
      } else {
        const kind = mode === 'style' ? 'style' : 'template'
        const created = await api.savePreset(
          kind === 'style' ? { name, kind, css: css || undefined, theme } : { name, kind, type },
        )
        const references = links.map((link) => link.trim()).filter(Boolean)
        let text = brief.trim()
        if (!text && (files.length || references.length))
          text = `Work out the visual language of these references and build the first version of this ${kind}.`
        if (references.length) text += `\n\nReference links:\n${references.map((link) => `- ${link}`).join('\n')}`
        if (text || files.length) setPending(created.id, { text, files })
        navigate(`/edit/${created.id}`)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }
  const remove = async (entry: Artifact) => {
    setBusy(true)
    setError(null)
    try {
      await api.removePreset(entry.id)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }
  const importCss = async (file: File | undefined) => {
    if (!file) return
    try {
      if (file.size > 1_000_000) throw new Error('Choose a CSS file smaller than 1 MB.')
      setCss(await file.text())
      if (!name.trim()) setName(file.name.replace(/\.css$/i, ''))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }
  return (
    <section className="mb-8">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="mr-auto font-semibold">Templates &amp; styles</h2>
        <Button onClick={() => open('template')} disabled={busy}>
          <Plus size={14} /> Create template
        </Button>
        <Button onClick={() => open('style')} disabled={busy}>
          <Palette size={14} /> Add style
        </Button>
      </div>
      <p className="mb-4 text-sm text-muted">
        Build from descriptions, files or links. Save to keep an entry in your private library.
      </p>
      {error && !mode ? (
        <p role="alert" className="mb-2 text-sm text-danger">
          {error}
        </p>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        {(['templates', 'styles'] as const).map((kind) => {
          const selected = entries[kind].find(
            (entry) => entry.id === (kind === 'templates' ? selectedTemplate : selectedStyle),
          )
          return (
            <div key={kind} className="min-w-0 rounded-xl border border-line bg-panel p-4">
              <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
                {kind === 'templates' ? <BookOpen size={15} /> : <Palette size={15} />}
                {kind === 'templates' ? 'Templates' : 'Styles'}
              </h3>
              {!entries[kind].length ? (
                <p className="text-xs text-muted">
                  Create a {kind === 'templates' ? 'template' : 'style'} from references or a description.
                </p>
              ) : null}
              <div className="grid grid-cols-2 items-start gap-3 lg:grid-cols-3">
                {entries[kind].map((entry) => (
                  <LibraryCard
                    key={`${entry.id}:${entry.version}`}
                    entry={entry}
                    selected={selected?.id === entry.id}
                    onSelect={() => (kind === 'templates' ? selectTemplate(entry.id) : selectStyle(entry.id))}
                  />
                ))}
              </div>
              {selected ? (
                <div className="mt-3 flex flex-wrap gap-2">
                  {kind === 'templates' ? (
                    <Button variant="primary" disabled={busy} onClick={() => open('use', selected)}>
                      Use template
                    </Button>
                  ) : null}
                  <Button onClick={() => navigate(`/edit/${selected.id}`)} disabled={busy}>
                    Edit
                  </Button>
                  {kind === 'templates' ? (
                    <LinkButton href={selected.url} target="_blank" rel="noopener">
                      Preview
                    </LinkButton>
                  ) : null}
                  <Button onClick={() => void remove(selected)} disabled={busy}>
                    Remove
                  </Button>
                </div>
              ) : null}
              {selected && kind === 'styles' ? <StyleGuide styleId={selected.id} version={selected.version} /> : null}
            </div>
          )
        })}
      </div>
      <Dialog
        open={mode !== null}
        dismissible={!busy}
        onClose={() => {
          if (!busy) setMode(null)
        }}
        title={mode === 'style' ? 'Add a style' : mode === 'use' ? 'Use template' : 'Create a template'}
        wide
      >
        <form
          onSubmit={(e) => {
            e.preventDefault()
            void submit()
          }}
          className="space-y-4"
        >
          <Field id="library-name" label={mode === 'use' ? 'Artifact title' : 'Name'}>
            <input
              id="library-name"
              className={INPUT}
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={200}
              required
              disabled={busy}
            />
          </Field>
          {mode === 'template' ? (
            <Field id="template-type" label="Make it a">
              <Select
                id="template-type"
                value={type}
                onChange={(e) => setType(e.target.value as ArtifactType)}
                disabled={busy}
              >
                <option value="deck">Deck</option>
                <option value="document">Document</option>
                <option value="page">Page</option>
              </Select>
            </Field>
          ) : null}
          {mode === 'style' ? (
            <Field id="style-theme" label="Base theme">
              <Select
                id="style-theme"
                value={theme}
                onChange={(e) => setTheme(e.target.value as Theme)}
                disabled={busy}
              >
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </Select>
            </Field>
          ) : null}
          {mode !== 'use' ? (
            <>
              <ReferencePicker files={files} links={links} onFiles={setFiles} onLinks={setLinks} disabled={busy} />
              <Field id="library-brief" label="Describe">
                <textarea
                  id="library-brief"
                  className={INPUT}
                  rows={3}
                  value={brief}
                  onChange={(e) => setBrief(e.target.value)}
                  disabled={busy}
                  placeholder="What should this be used for? References can supply the visual direction."
                />
              </Field>
            </>
          ) : null}
          {mode === 'style' ? (
            <details>
              <summary className="cursor-pointer text-sm">Start from CSS instead</summary>
              <input
                type="file"
                accept=".css,text/css"
                aria-label="Import CSS"
                className="my-3 text-sm"
                disabled={busy}
                onChange={(e) => void importCss(e.target.files?.[0])}
              />
              <Field id="library-css" label="CSS">
                <textarea
                  id="library-css"
                  className={`${INPUT} font-mono`}
                  rows={8}
                  value={css}
                  onChange={(e) => setCss(e.target.value)}
                  disabled={busy}
                />
              </Field>
            </details>
          ) : null}
          {mode === 'use' ? (
            <Field id="template-style" label="Style">
              <StyleSelect id="template-style" styles={entries.styles} value={style} onChange={setStyle} />
            </Field>
          ) : null}
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button type="button" onClick={() => setMode(null)} disabled={busy}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" disabled={busy || !name.trim() || !!checkAttachments(files)}>
              {busy ? <Spinner /> : null}
              {mode === 'use' ? 'Create artifact' : 'Create with chat'}
            </Button>
          </div>
        </form>
      </Dialog>
    </section>
  )
}

/** Save reusable snapshots or apply a library style to the current artifact. */
export function ArtifactLibrary({ artifact, onChanged }: { artifact: Artifact; onChanged: () => void }) {
  const controlId = useId()
  const [open, setOpen] = useState(false)
  const [entries, setEntries] = useState<Presets>(EMPTY)
  const [name, setName] = useState(artifact.title)
  const [style, setStyle] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  useEffect(() => {
    if (!open) return
    setName(artifact.title)
    setError(null)
    setNotice(null)
    setStyle('')
    api
      .presets()
      .then(setEntries)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
  }, [open, artifact.title])
  const act = async (kind: 'template' | 'style' | 'apply') => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      if (kind === 'apply') {
        await api.applyStyle(artifact.id, style)
        onChanged()
        setOpen(false)
      } else {
        await api.savePreset({ artifact_id: artifact.id, name, kind })
        setEntries(await api.presets())
        setNotice(`Saved ${name.trim()} to your ${kind === 'template' ? 'templates' : 'styles'}.`)
        onChanged()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <Button onClick={() => setOpen(true)} className="h-7">
        <Palette size={14} /> Library
      </Button>
      <Dialog
        open={open}
        dismissible={!busy}
        onClose={() => {
          if (!busy) setOpen(false)
        }}
        title="Templates & styles"
      >
        <div className="space-y-4">
          <p className="text-sm text-muted">Save the current saved files as a reusable, private snapshot.</p>
          <Field id={`${controlId}-name`} label="Name">
            <input
              id={`${controlId}-name`}
              className={INPUT}
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={200}
              disabled={busy}
            />
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => void act('template')} disabled={busy || !name.trim()}>
              Save as template
            </Button>
            <Button onClick={() => void act('style')} disabled={busy || !name.trim()}>
              Save as style
            </Button>
          </div>
          {artifact.can_edit ? (
            <div className="border-t border-line pt-4">
              <Field id={`${controlId}-style`} label="Apply a saved style">
                <StyleSelect id={`${controlId}-style`} styles={entries.styles} value={style} onChange={setStyle} />
              </Field>
              <p className="my-2 text-xs text-muted">
                Replaces the current CSS and base theme. Content and layout components are kept.
              </p>
              <Button variant="primary" onClick={() => void act('apply')} disabled={busy || !style}>
                Apply style
              </Button>
            </div>
          ) : null}
          {busy ? <Spinner label="Updating library" /> : null}
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
          {notice ? (
            <p role="status" className="text-sm text-accent">
              {notice}
            </p>
          ) : null}
          <div className="flex justify-end">
            <Button onClick={() => setOpen(false)} disabled={busy}>
              Close
            </Button>
          </div>
        </div>
      </Dialog>
    </>
  )
}
