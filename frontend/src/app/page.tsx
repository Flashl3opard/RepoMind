import { Suspense } from "react";

import { AddRepoForm } from "@/components/add-repo-form";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { RepoRow } from "@/components/repo-row";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, listRepos } from "@/lib/api";

export default function ReposPage() {
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Add a repository</CardTitle>
        </CardHeader>
        <CardContent>
          <AddRepoForm />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Repositories</CardTitle>
        </CardHeader>
        <CardContent>
          <Suspense fallback={<ReposTableSkeleton />}>
            <ReposTable />
          </Suspense>
        </CardContent>
      </Card>
    </div>
  );
}

function ReposTableSkeleton() {
  return (
    <div className="flex flex-col gap-2">
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-8 w-full" />
      <Skeleton className="h-8 w-full" />
    </div>
  );
}

async function ReposTable() {
  let repos;
  try {
    repos = await listRepos();
  } catch (error) {
    const message =
      error instanceof ApiError
        ? `Backend returned ${error.status}.`
        : "Could not reach the backend. Is BACKEND_URL correct and the server running?";
    return <ErrorState message={message} />;
  }

  if (repos.length === 0) {
    return (
      <EmptyState
        title="No repositories yet"
        description="Add a public GitHub repository URL above to start ingesting it."
      />
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Repository</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Commit</TableHead>
          <TableHead>Files</TableHead>
          <TableHead>Chunks</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {repos.map((repo) => (
          <RepoRow key={repo.id} repo={repo} />
        ))}
      </TableBody>
    </Table>
  );
}
