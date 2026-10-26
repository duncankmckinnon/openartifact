export function StyleGuide({ styleId, version }: { styleId: string; version: string | null }) {
  return (
    <iframe
      src={`/artifacts/${styleId}/?guide&type=document&v=${version ?? ''}`}
      title="Style guide"
      className="mt-4 h-[640px] w-full rounded-lg border border-line"
    />
  )
}
