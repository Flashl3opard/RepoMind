import { Suspense } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { RiskBadge } from "@/components/risk-badge";
import { StatusBadge } from "@/components/status-badge";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ApiError, listRepoReviews } from "@/lib/api";

export default function RepoReviewsPage({
  params,
}: PageProps<"/repos/[id]/reviews">) {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Reviews</h1>
      <Suspense fallback={<Skeleton className="h-48 w-full" />}>
        <ReviewsTable params={params} />
      </Suspense>
    </div>
  );
}

async function ReviewsTable({
  params,
}: {
  params: PageProps<"/repos/[id]/reviews">["params"];
}) {
  const { id } = await params;

  let reviews;
  try {
    reviews = await listRepoReviews(id);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <ErrorState
        message={
          error instanceof Error ? error.message : "Failed to load reviews."
        }
      />
    );
  }

  if (reviews.length === 0) {
    return (
      <EmptyState
        title="No reviews yet"
        description="Reviews appear here once the GitHub App reviews a PR, or you run one manually from the Playground."
      />
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>PR</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Risk</TableHead>
          <TableHead>Findings</TableHead>
          <TableHead>Source</TableHead>
          <TableHead>Created</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {reviews.map((review) => (
          <TableRow key={review.id}>
            <TableCell>
              <Link
                href={`/reviews/${review.id}`}
                className="font-medium hover:underline"
              >
                {review.pr_number > 0 ? `#${review.pr_number}` : "manual"}
              </Link>
              <div className="text-muted-foreground font-mono text-xs">
                {review.head_sha.slice(0, 10)}
              </div>
            </TableCell>
            <TableCell>
              <StatusBadge status={review.status} />
            </TableCell>
            <TableCell>
              <RiskBadge risk={review.risk_level} />
            </TableCell>
            <TableCell>{review.finding_count}</TableCell>
            <TableCell>
              <Badge variant="outline" className="capitalize">
                {review.source}
              </Badge>
            </TableCell>
            <TableCell className="text-muted-foreground text-sm">
              {new Date(review.created_at).toLocaleString()}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
