import { FileCode2 } from "lucide-react";

import { buildGithubBlobUrl } from "@/lib/github";
import { cn } from "@/lib/utils";

export interface CitationChipProps {
  filePath: string;
  symbolName?: string;
  startLine: number;
  endLine: number;
  repoUrl: string;
  commitSha: string | null;
  label?: string;
  className?: string;
}

export function CitationChip({
  filePath,
  symbolName,
  startLine,
  endLine,
  repoUrl,
  commitSha,
  label,
  className,
}: CitationChipProps) {
  const href = commitSha
    ? buildGithubBlobUrl({ repoUrl, commitSha, filePath, startLine, endLine })
    : null;

  const lineText =
    startLine === endLine ? `L${startLine}` : `L${startLine}-${endLine}`;
  const content = (
    <>
      <FileCode2 className="size-3.5 shrink-0" />
      <span className="truncate">
        {label ? <span className="font-semibold">{label}</span> : null}
        {label ? " " : ""}
        {filePath}
        {symbolName ? ` · ${symbolName}` : ""} · {lineText}
      </span>
    </>
  );

  const chipClasses = cn(
    "inline-flex max-w-full items-center gap-1.5 rounded-md border bg-muted px-2 py-1 text-xs",
    href && "hover:bg-accent hover:text-accent-foreground transition-colors",
    className,
  );

  if (!href) {
    return <span className={chipClasses}>{content}</span>;
  }

  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={chipClasses}
    >
      {content}
    </a>
  );
}
