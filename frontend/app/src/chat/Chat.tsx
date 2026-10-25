/**
 * The editing conversation for one artifact, over the Vercel AI SDK protocol to `/api/artifacts/<id>/chat`.
 *
 * The server owns the history: the browser sends only the new message each turn (`prepareSendMessagesRequest`),
 * the server runs the agent with the stored history, and `GET .../chat` restores the conversation on load. The
 * preview beside the chat is told to reload whenever a `build` call completes and when a turn ends.
 */

import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport, type FileUIPart, isToolUIPart, type UIMessage } from 'ai'
import { ArrowUp, Paperclip, Square, Trash2 } from 'lucide-react'
import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react'
import { ATTACH_ACCEPT, api, checkAttachments, type ModelChoice } from '../api.ts'
import { Button, Spinner } from '../components/ui.tsx'
import { takePending } from '../pending.ts'
import { Message } from './Message.tsx'

interface ChatProps {
  artifactId: string
  draftKind: 'template' | 'style' | null
  /** The page the preview shows, 1-based, sent with each message so the agent knows what "this slide" means. */
  page: number | null
  /** Called when the artifact may have changed: a `build` finished, or a turn ended. */
  onChanged: () => void
}

interface Loaded {
  messages: UIMessage[]
  model: string | null
  models: ModelChoice[]
  defaultModel: string | null
}

export function Chat(props: ChatProps) {
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    Promise.all([api.chat(props.artifactId), api.configure()])
      .then(([chat, configure]) =>
        setLoaded({
          messages: chat.messages as UIMessage[],
          model: chat.model,
          models: configure.models,
          defaultModel: configure.default,
        }),
      )
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
  }, [props.artifactId])

  if (error) return <p className="p-4 text-sm text-danger">{error}</p>
  if (!loaded) {
    return (
      <div className="p-4">
        <Spinner label="Loading conversation" />
      </div>
    )
  }
  return <Conversation {...props} loaded={loaded} />
}

async function fileParts(files: File[]): Promise<FileUIPart[]> {
  return Promise.all(
    files.map(
      (file) =>
        new Promise<FileUIPart>((resolve, reject) => {
          const reader = new FileReader()
          reader.onerror = () => reject(new Error(`Could not read ${file.name}`))
          reader.onload = () =>
            resolve({
              type: 'file',
              mediaType: file.type || 'application/octet-stream',
              filename: file.name,
              url: String(reader.result),
            })
          reader.readAsDataURL(file)
        }),
    ),
  )
}

function Conversation({ artifactId, draftKind, page, onChanged, loaded }: ChatProps & { loaded: Loaded }) {
  const configured = loaded.models.some((m) => m.id === loaded.model) ? loaded.model : loaded.defaultModel
  const [model, setModel] = useState<string | null>(configured)
  // Refs, so the transport (created once) reads the current choice and page when a message is sent.
  const modelRef = useRef(model)
  modelRef.current = model
  const pageRef = useRef(page)
  pageRef.current = page
  const [draft, setDraft] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [fileError, setFileError] = useState<string | null>(null)
  const [reading, setReading] = useState(false)
  const initialSent = useRef(false)
  const mounted = useRef(true)
  const picker = useRef<HTMLInputElement>(null)
  const bottom = useRef<HTMLDivElement>(null)

  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: `/api/artifacts/${artifactId}/chat`,
        credentials: 'same-origin',
        body: () => ({ model: modelRef.current, page: pageRef.current }),
        // Only the new message: the server holds the history and appends what it is sent.
        prepareSendMessagesRequest: ({ id, messages, trigger, messageId, body }) => ({
          body: { id, trigger, messageId, messages: messages.slice(-1), ...body },
        }),
      }),
    [artifactId],
  )
  const { messages, sendMessage, status, stop, error, setMessages } = useChat({
    id: artifactId,
    transport,
    messages: loaded.messages,
    onFinish: () => onChanged(),
  })

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      void stop()
    }
  }, [stop])

  useEffect(() => {
    if (initialSent.current || !model || status !== 'ready') return
    const pending = takePending(artifactId)
    if (!pending) return
    initialSent.current = true
    if (loaded.messages.length !== 0) {
      setDraft(pending.text)
      setFiles(pending.files)
      return
    }
    setReading(true)
    void fileParts(pending.files)
      .then(async (parts) => {
        if (mounted.current) await sendMessage({ text: pending.text, files: parts })
      })
      .catch((err: unknown) => {
        if (mounted.current) {
          setDraft(pending.text)
          setFiles(pending.files)
          setFileError(err instanceof Error ? err.message : String(err))
        }
      })
      .finally(() => {
        if (mounted.current) setReading(false)
      })
  }, [artifactId, loaded.messages.length, model, sendMessage, status])

  // Reload the preview as soon as a build has finished, before the model's closing words arrive.
  const builds = useRef(0)
  useEffect(() => {
    const done = messages
      .flatMap((m) => m.parts)
      .filter((p) => isToolUIPart(p) && p.type === 'tool-build' && p.state === 'output-available').length
    if (done > builds.current) onChanged()
    builds.current = done
  }, [messages, onChanged])

  // Keep the latest message in view as it streams: the effect runs whenever `messages` changes.
  // biome-ignore lint/correctness/useExhaustiveDependencies: `messages` is the trigger, not a value used inside
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  const busy = reading || status === 'submitted' || status === 'streaming'
  const attach = (added: File[]) => {
    const combined = [...files, ...added]
    const invalid = checkAttachments(combined)
    setFileError(invalid)
    if (!invalid) setFiles(combined)
  }
  const send = async () => {
    const text = draft.trim()
    if ((!text && files.length === 0) || busy || !model) return
    setReading(true)
    setFileError(null)
    try {
      const parts = await fileParts(files)
      setDraft('')
      setFiles([])
      await sendMessage({
        text: text || 'Work out the visual language of these references and update this draft.',
        files: parts,
      })
    } catch (err) {
      setFileError(err instanceof Error ? err.message : String(err))
      setDraft(text)
    } finally {
      setReading(false)
    }
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send()
    }
  }
  const clear = async () => {
    if (busy || messages.length === 0) return
    if (!window.confirm('Forget this conversation? The artifact itself is unchanged.')) return
    await api.clearChat(artifactId)
    setMessages([])
  }

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: file drop supplements the keyboard-accessible attachment button.
    <div
      className="flex h-full flex-col"
      onDragOver={(e) => {
        if (draftKind) e.preventDefault()
      }}
      onDrop={(e) => {
        if (draftKind) {
          e.preventDefault()
          if (!busy) attach([...e.dataTransfer.files])
        }
      }}
    >
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {messages.length === 0 ? (
          <div className="mt-8 text-center text-sm text-muted">
            <p className="font-medium text-fg">{draftKind ? `Describe your ${draftKind}` : 'Ask for a change'}</p>
            <p className="mt-1">
              {draftKind
                ? 'Describe its recurring sections, layouts, colors and fields to replace each time.'
                : '"Add a page about pricing", "make the headings blue", "turn the bullet list into a table".'}
            </p>
            <p className="mt-1">
              {draftKind
                ? `The agent builds the ${draftKind}${draftKind === 'style' ? ' and its guide' : ''} beside the chat. Save it when it looks right.`
                : 'The agent edits the files, rebuilds, and the preview refreshes.'}
            </p>
          </div>
        ) : null}
        {messages.map((message) => (
          <Message key={message.id} message={message} artifactId={artifactId} />
        ))}
        {status === 'submitted' ? <Spinner label="Thinking" /> : null}
        {error ? (
          <p className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
            {error.message}
          </p>
        ) : null}
        <div ref={bottom} />
      </div>
      <div className="border-t border-line p-3">
        {files.length ? (
          <div className="mb-2 flex flex-wrap gap-2">
            {files.map((file, i) => (
              <button
                type="button"
                key={`${file.name}-${i}`}
                disabled={busy}
                className="rounded border border-line px-2 py-1 text-xs"
                aria-label={`Remove ${file.name}`}
                onClick={() => setFiles(files.filter((_, index) => index !== i))}
              >
                {file.name} ×
              </button>
            ))}
          </div>
        ) : null}
        {fileError ? (
          <p role="alert" className="mb-2 text-xs text-danger">
            {fileError}
          </p>
        ) : null}
        <div className="rounded-xl border border-line bg-bg focus-within:border-accent">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKey}
            rows={3}
            placeholder={
              model
                ? draftKind
                  ? `Describe your reusable ${draftKind} (Enter to send)`
                  : 'Describe the change (Enter to send, Shift+Enter for a new line)'
                : 'No model is configured on this server'
            }
            disabled={!model}
            className="block w-full resize-none bg-transparent px-3 pt-3 text-sm outline-none placeholder:text-faint"
          />
          <div className="flex items-center gap-2 px-2 pb-2">
            {draftKind ? (
              <>
                <input
                  ref={picker}
                  type="file"
                  className="hidden"
                  multiple
                  accept={ATTACH_ACCEPT}
                  disabled={busy}
                  onChange={(e) => {
                    attach([...(e.target.files ?? [])])
                    e.target.value = ''
                  }}
                />
                <Button
                  variant="ghost"
                  title="Attach references"
                  disabled={busy}
                  onClick={() => picker.current?.click()}
                >
                  <Paperclip size={14} />
                </Button>
              </>
            ) : null}
            <select
              value={model ?? ''}
              onChange={(e) => setModel(e.target.value || null)}
              disabled={busy || loaded.models.length === 0}
              className="h-7 max-w-[55%] rounded-md border border-line bg-panel px-1.5 text-xs text-muted outline-none"
              aria-label="Model"
            >
              {loaded.models.length === 0 ? <option value="">No models configured</option> : null}
              {loaded.models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={clear}
              disabled={busy || messages.length === 0}
              title="Forget this conversation"
              className="ml-auto rounded-md p-1.5 text-muted hover:bg-white/8 hover:text-fg disabled:opacity-30"
            >
              <Trash2 size={14} />
            </button>
            {busy ? (
              <Button variant="ghost" onClick={() => stop()} className="h-7 px-2" title="Stop">
                <Square size={12} /> Stop
              </Button>
            ) : (
              <Button
                variant="primary"
                onClick={() => void send()}
                disabled={(!draft.trim() && !files.length) || !model || busy}
                className="h-7 w-7 px-0"
                title="Send"
              >
                <ArrowUp size={14} />
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
