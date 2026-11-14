"use client";

import { useState, useTransition } from "react";
import { Loader2 } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CitationChip } from "@/components/citation-chip";
import { Textarea } from "@/components/ui/textarea";
import { askAction } from "@/lib/actions";
import type { AskResponse, DebugChunkResponse } from "@/lib/types";

export function AskPanel({
  repositoryId,
  repoUrl,
  commitSha,
}: {
  repositoryId: string;
  repoUrl: string;
  commitSha: string | null;
}) {
  const [question, setQuestion] = useState("");
  const [debug, setDebug] = useState(false);
  const [answer, setAnswer] = useState<AskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    startTransition(async () => {
      const result = await askAction(repositoryId, question, debug);
      if (!result.ok || !result.data) {
        setError(result.error ?? "Failed to get an answer.");
        setAnswer(null);
        return;
      }
      setAnswer(result.data);
    });
  }

  return (
    <div className="flex flex-col gap-4">
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <Textarea
          placeholder="Ask something about this repo, e.g. “How does the ingestion orchestrator handle a failed clone?”"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          disabled={isPending}
          rows={3}
        />
        <div className="flex items-center justify-between">
          <label className="text-muted-foreground flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={debug}
              onChange={(event) => setDebug(event.target.checked)}
              className="accent-primary"
            />
            Debug
          </label>
          <Button type="submit" disabled={isPending}>
            {isPending ? <Loader2 className="animate-spin" /> : null}
            Ask
          </Button>
        </div>
      </form>

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Couldn&apos;t answer that</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {answer ? (
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Answer</CardTitle>
            <Badge
              variant={answer.confidence === "low" ? "warning" : "success"}
            >
              {answer.confidence} confidence
            </Badge>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {answer.confidence === "low" ? (
              <Alert variant="warning">
                <AlertTitle>Low confidence</AlertTitle>
                <AlertDescription>
                  The agent couldn&apos;t fully verify this answer against the
                  cited chunks. Treat it as a starting point, not a final word.
                </AlertDescription>
              </Alert>
            ) : null}

            <p className="text-sm whitespace-pre-wrap">{answer.answer}</p>

            {answer.citations.length > 0 ? (
              <div className="flex flex-col gap-2">
                <span className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                  Citations
                </span>
                <div className="flex flex-wrap gap-2">
                  {answer.citations.map((citation) => (
                    <CitationChip
                      key={citation.label}
                      label={citation.label}
                      filePath={citation.file_path}
                      symbolName={citation.symbol_name}
                      startLine={citation.start_line}
                      endLine={citation.end_line}
                      repoUrl={repoUrl}
                      commitSha={commitSha}
                    />
                  ))}
                </div>
              </div>
            ) : null}

            {answer.debug ? (
              <div className="flex flex-col gap-3 border-t pt-4">
                <div className="text-sm">
                  <span className="text-muted-foreground">
                    Rewritten query:{" "}
                  </span>
                  <span className="font-mono">
                    {answer.debug.rewritten_query}
                  </span>
                </div>
                <DebugChunks
                  title="Retrieved"
                  chunks={answer.debug.retrieved}
                />
                <DebugChunks
                  title="Expanded (graph)"
                  chunks={answer.debug.expanded}
                />
              </div>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}

function DebugChunks({
  title,
  chunks,
}: {
  title: string;
  chunks: DebugChunkResponse[] | undefined;
}) {
  if (!chunks || chunks.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      <span className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
        {title}
      </span>
      <ul className="flex flex-col gap-1">
        {chunks.map((chunk, index: number) => (
          <li
            key={`${chunk.label}-${index}`}
            className="flex flex-wrap items-center gap-2 text-xs"
          >
            <Badge variant="outline">{chunk.label}</Badge>
            <span className="font-mono">{chunk.file_path}</span>
            <span className="text-muted-foreground">· {chunk.symbol_name}</span>
            <Badge variant="secondary">{chunk.sources.join(", ")}</Badge>
            <span className="text-muted-foreground">
              score {chunk.score.toFixed(3)}
            </span>
            <span className="text-muted-foreground">{chunk.reason}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
