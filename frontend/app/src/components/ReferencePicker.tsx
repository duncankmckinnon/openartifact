import { ATTACH_ACCEPT, checkAttachments } from '../api.ts'

export function ReferencePicker({
  files,
  links,
  onFiles,
  onLinks,
  disabled,
}: {
  files: File[]
  links: string[]
  onFiles: (files: File[]) => void
  onLinks: (links: string[]) => void
  disabled: boolean
}) {
  const add = (added: File[]) => onFiles([...files, ...added])
  const error = checkAttachments(files)
  return (
    <div className="space-y-3">
      <label
        className="block rounded-lg border border-dashed border-line p-4 text-sm text-muted"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault()
          if (!disabled) add([...e.dataTransfer.files])
        }}
      >
        Drop a PDF, PowerPoint or Word file, or an image
        <input
          className="mt-2 block w-full text-xs"
          type="file"
          multiple
          accept={ATTACH_ACCEPT}
          disabled={disabled}
          onChange={(e) => {
            add([...(e.target.files ?? [])])
            e.target.value = ''
          }}
        />
      </label>
      <div className="flex flex-wrap gap-2">
        {files.map((file, i) => (
          <button
            key={`${file.name}-${i}`}
            type="button"
            disabled={disabled}
            className="rounded border border-line px-2 py-1 text-xs"
            onClick={() => onFiles(files.filter((_, index) => index !== i))}
            aria-label={`Remove ${file.name}`}
          >
            {file.name} ×
          </button>
        ))}
      </div>
      {links.map((url, i) => (
        <div className="flex gap-2" key={`reference-${i}`}>
          <input
            type="url"
            aria-label={`Reference link ${i + 1}`}
            placeholder="https://example.com"
            value={url}
            disabled={disabled}
            className="min-w-0 flex-1 rounded border border-line bg-bg px-3 py-2 text-sm"
            onChange={(e) => onLinks(links.map((value, index) => (index === i ? e.target.value : value)))}
          />
          <button
            type="button"
            aria-label={`Remove reference link ${i + 1}`}
            disabled={disabled}
            onClick={() => onLinks(links.filter((_, index) => index !== i))}
          >
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        className="text-xs text-accent underline"
        disabled={disabled}
        onClick={() => onLinks([...links, ''])}
      >
        Add a link
      </button>
      {error ? (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
    </div>
  )
}
