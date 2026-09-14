import { useMemo } from "react";
import { marked } from "marked";

/** Render agent-written Markdown (reports under logs/). Content comes from the local repo, not the network. */
export function Markdown({ source }: { source: string }) {
  const html = useMemo(() => marked.parse(source, { gfm: true, async: false }) as string, [source]);
  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />;
}
