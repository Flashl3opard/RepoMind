import { Suspense } from "react";

import { DiffPlaygroundForm } from "@/components/diff-playground-form";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, listRepos } from "@/lib/api";

export default function PlaygroundPage() {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold">Playground</h1>
        <p className="text-muted-foreground text-sm">
          Paste a unified diff, pick an ingested repo, and run the reviewer
          against its indexed base branch. Nothing is posted to GitHub.
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-64 w-full" />}>
        <PlaygroundForm />
      </Suspense>
    </div>
  );
}

async function PlaygroundForm() {
  let repos;
  try {
    repos = await listRepos();
  } catch (error) {
    return (
      <ErrorState
        message={
          error instanceof ApiError
            ? `Backend returned ${error.status}.`
            : "Could not reach the backend."
        }
      />
    );
  }

  const completedRepos = repos
    .filter((repo) => repo.status === "completed")
    .map((repo) => ({
      id: repo.id,
      full_name: repo.full_name,
      url: repo.url,
      last_commit_sha: repo.commit_sha,
    }));

  if (completedRepos.length === 0) {
    return (
      <EmptyState
        title="No ingested repositories yet"
        description="Add a repository from the Repos page and wait for ingestion to complete before using the playground."
      />
    );
  }

  return <DiffPlaygroundForm repos={completedRepos} />;
}
