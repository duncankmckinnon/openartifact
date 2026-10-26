import { useState } from 'react'
import { type Artifact, api } from '../api.ts'
import { Button } from './ui.tsx'

export function DraftBar({
  artifact,
  onSaved,
  onDiscarded,
  disabled = false,
}: {
  artifact: Artifact
  onSaved: (entry: Artifact) => void
  onDiscarded: () => void
  disabled?: boolean
}) {
  const [name, setName] = useState(artifact.title)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const act = async (save: boolean) => {
    setBusy(true)
    setError(null)
    try {
      if (save) onSaved(await api.saveDraft(artifact.id, name))
      else {
        await api.discardDraft(artifact.id)
        onDiscarded()
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-accent">Draft</span>
      <input
        aria-label="Draft name"
        value={name}
        maxLength={200}
        disabled={busy}
        className="w-36 rounded border border-line bg-bg px-2 py-1 text-xs"
        onChange={(e) => setName(e.target.value)}
      />
      <Button
        variant="primary"
        className="h-7"
        disabled={busy || disabled || !name.trim()}
        onClick={() => void act(true)}
      >
        Save
      </Button>
      <Button className="h-7" disabled={busy} onClick={() => void act(false)}>
        Discard
      </Button>
      {disabled ? <span className="text-xs text-muted">Save markdown changes first</span> : null}
      {error ? (
        <span role="alert" className="max-w-md text-xs text-danger">
          {error}
        </span>
      ) : null}
    </div>
  )
}
