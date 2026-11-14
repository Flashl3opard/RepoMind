"use client";

import { useState, useTransition } from "react";
import { Loader2 } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { FindingsList } from "@/components/findings-list";
import { RiskBadge } from "@/components/risk-badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { runReviewAction } from "@/lib/actions";
import type { ReviewResponse } from "@/lib/types";

const PLACEHOLDER_DIFF = `diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
-def add(a, b):
-    return a + b
+def add(a, b, c):
+    return a + b + c
`;

export function DiffPlaygroundForm({
  repos,
}: {
  repos: {
    id: string;
    full_name: string;
    url: string;
    last_commit_sha: string | null;
  }[];
}) {
  const [repositoryId, setRepositoryId] = useState(repos[0]?.id ?? "");
  const [diff, setDiff] = useState("");
  const [result, setResult] = useState<ReviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const selectedRepo = repos.find((repo) => repo.id === repositoryId);

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!repositoryId) {
      setError("Pick a repository first.");
      return;
    }
    startTransition(async () => {
      const response = await runReviewAction(repositoryId, diff);
      if (!response.ok || !response.data) {
        setError(response.error ?? "Review failed.");
        setResult(null);
        return;
      }
      setResult(response.data);
    });
  }

  return (
    <div className="flex flex-col gap-4">
      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-medium">Repository</span>
          <Select value={repositoryId} onValueChange={setRepositoryId}>
            <SelectTrigger>
              <SelectValue placeholder="Select a repository" />
            </SelectTrigger>
            <SelectContent>
              {repos.map((repo) => (
                <SelectItem key={repo.id} value={repo.id}>
                  {repo.full_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-medium">Unified diff</span>
          <Textarea
            placeholder={PLACEHOLDER_DIFF}
            value={diff}
            onChange={(event) => setDiff(event.target.value)}
            rows={14}
            disabled={isPending}
          />
        </div>

        <div className="flex items-center justify-between">
          <span className="text-muted-foreground text-xs">
            Runs against the repo&apos;s indexed base branch. Nothing is posted
            to GitHub.
          </span>
          <Button type="submit" disabled={isPending || !repositoryId}>
            {isPending ? <Loader2 className="animate-spin" /> : null}
            Run review
          </Button>
        </div>
      </form>

      {error ? (
        <Alert variant="destructive">
          <AlertTitle>Review failed</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {result ? (
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <p className="text-sm">{result.summary}</p>
            <RiskBadge risk={result.risk_level} />
          </div>
          <FindingsList
            findings={result.findings}
            repoUrl={selectedRepo?.url}
            commitSha={selectedRepo?.last_commit_sha}
          />
        </div>
      ) : null}
    </div>
  );
}
