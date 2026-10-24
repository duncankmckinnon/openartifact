/** The personal library: reusable templates, imported CSS, and appearance controls in the editor. */

import { BookOpen, Palette, Plus } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { type Artifact, type ArtifactType, api, type Presets, type Theme } from '../api.ts'
import { navigate } from '../router.ts'
import { Button, Dialog, Field, LinkButton, Select, Spinner } from './ui.tsx'

const INPUT = 'w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm outline-none focus:border-accent'
const EMPTY: Presets = { templates: [], styles: [] }

/** One-off draft storage lets the template brief follow navigation without appearing in the URL. */
export function templateBriefKey(id: string): string {
  return `openartifact:template-brief:${id}`
}

function TypeSelect({ value, onChange }: { value: ArtifactType; onChange: (type: ArtifactType) => void }) {
  return (
    <Select id="template-type" value={value} onChange={(e) => onChange(e.target.value as ArtifactType)}>
      <option value="deck">Deck</option>
      <option value="document">Document</option>
      <option value="page">Page</option>
    </Select>
  )
}

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

/** A home-screen library with template authoring, CSS import, and independent artifact creation. */
export function Library({ entries, refresh }: { entries: Presets; refresh: () => Promise<void> }) {
  const [mode, setMode] = useState<'template' | 'style' | 'use' | null>(null)
  const [template, setTemplate] = useState<Artifact | null>(null)
  const [name, setName] = useState('')
  const [type, setType] = useState<ArtifactType>('deck')
  const [brief, setBrief] = useState('')
  const [css, setCss] = useState('')
  const [theme, setTheme] = useState<Theme>('light')
  const [style, setStyle] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const open = (next: 'template' | 'style' | 'use', entry?: Artifact) => {
    setName(next === 'use' ? `${entry?.title ?? 'Template'} copy` : '')
    setBrief('')
    setCss('')
    setStyle('')
    setError(null)
    setTemplate(entry ?? null)
    setMode(next)
  }
  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      if (mode === 'use' && template) {
        const created = await api.create({ template_id: template.id, title: name, style_id: style || undefined })
        navigate(`/edit/${created.id}`)
      } else {
        const created = await api.savePreset(
          mode === 'style' ? { name, kind: 'style', css, theme } : { name, kind: 'template', type },
        )
        if (mode === 'template') {
          if (brief.trim()) sessionStorage.setItem(templateBriefKey(created.id), brief.trim())
          navigate(`/edit/${created.id}`)
        } else {
          setMode(null)
          await refresh()
        }
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
        Describe a template in chat, or save one from an artifact. Your library is private.
      </p>
      {error && !mode ? (
        <p role="alert" className="mb-2 text-sm text-danger">
          {error}
        </p>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        {(['templates', 'styles'] as const).map((kind) => (
          <div key={kind} className="rounded-xl border border-line bg-panel p-4">
            <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
              {kind === 'templates' ? <BookOpen size={15} /> : <Palette size={15} />}
              {kind === 'templates' ? 'Templates' : 'Styles'}
            </h3>
            {entries[kind].length === 0 ? (
              <p className="text-xs text-muted">
                {kind === 'templates'
                  ? 'Create a reusable layout from a description, then use it for new artifacts.'
                  : 'Add your CSS or save an artifact’s appearance from its editor.'}
              </p>
            ) : (
              <ul className="space-y-3">
                {entries[kind].map((entry) => (
                  <li key={entry.id} className="border-t border-line pt-3">
                    <div className="mb-2 flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate font-medium">{entry.title}</span>
                      {kind === 'templates' ? <span className="text-xs text-muted">{entry.type}</span> : null}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {kind === 'templates' ? (
                        <Button variant="primary" disabled={busy} onClick={() => open('use', entry)}>
                          Use template
                        </Button>
                      ) : null}
                      <Button onClick={() => navigate(`/edit/${entry.id}`)} disabled={busy}>
                        Edit
                      </Button>
                      <LinkButton href={entry.url} target="_blank" rel="noopener">
                        Preview
                      </LinkButton>
                      <Button
                        onClick={() => void remove(entry)}
                        disabled={busy}
                        title="Remove from the library; the artifact and its history are kept"
                      >
                        Remove
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      <Dialog
        open={mode !== null}
        onClose={() => {
          if (!busy) setMode(null)
        }}
        title={mode === 'style' ? 'Add a style' : mode === 'use' ? 'Use template' : 'Create a template'}
        wide={mode === 'style'}
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
            <>
              <Field id="template-type" label="Artifact type">
                <TypeSelect value={type} onChange={setType} />
              </Field>
              <Field id="template-brief" label="Describe your template">
                <textarea
                  id="template-brief"
                  className={INPUT}
                  rows={5}
                  value={brief}
                  onChange={(e) => setBrief(e.target.value)}
                  placeholder="A monthly board report with a cover, key metrics, progress, risks and next steps. Use a clean layout with blue accents."
                />
              </Field>
              <p className="text-xs text-muted">
                The template-authoring skill builds your description in chat using your configured model. You can
                refine it beside the live preview.
              </p>
            </>
          ) : null}
          {mode === 'style' ? (
            <>
              <Field id="style-theme" label="Base theme">
                <Select id="style-theme" value={theme} onChange={(e) => setTheme(e.target.value as Theme)}>
                  {(['light', 'dark', 'markdown-light', 'markdown-dark'] as const).map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field id="css-file" label="Import a CSS file">
                <input
                  id="css-file"
                  type="file"
                  accept=".css,text/css"
                  onChange={(e) => void importCss(e.target.files?.[0])}
                  disabled={busy}
                />
              </Field>
              <Field id="library-css" label="CSS">
                <textarea
                  id="library-css"
                  className={`${INPUT} font-mono`}
                  rows={10}
                  value={css}
                  onChange={(e) => setCss(e.target.value)}
                  placeholder=":root { --accent: #2563eb; }"
                  required
                  disabled={busy}
                />
              </Field>
              <p className="text-xs text-muted">
                To include local images or fonts, save a style from an artifact that already contains those files.
                Combine CSS imports first.
              </p>
            </>
          ) : null}
          {mode === 'use' ? (
            <>
              <Field id="template-style" label="Style">
                <StyleSelect id="template-style" styles={entries.styles} value={style} onChange={setStyle} />
              </Field>
              <p className="text-xs text-muted">
                Creates a private copy with its own files. Later template edits affect future copies.
              </p>
            </>
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
            <Button type="submit" variant="primary" disabled={busy || !name.trim()}>
              {busy ? <Spinner /> : null}
              {mode === 'style' ? 'Save style' : mode === 'use' ? 'Create artifact' : 'Create with chat'}
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
