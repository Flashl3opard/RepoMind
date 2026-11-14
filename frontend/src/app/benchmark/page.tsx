import { Fragment, Suspense } from "react";

import { BenchmarkChart } from "@/components/benchmark-chart";
import { EmptyState } from "@/components/empty-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getBenchmarkLatest } from "@/lib/api";

export default function BenchmarkPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96 w-full" />}>
      <BenchmarkContent />
    </Suspense>
  );
}

async function BenchmarkContent() {
  const results = await getBenchmarkLatest();

  if (!results) {
    return (
      <EmptyState
        title="No benchmark results yet"
        description="Run the context-mode ablation from the backend to generate results."
        action={
          <pre className="bg-muted mt-2 rounded-md p-3 text-left text-xs">
            {"cd backend\n" +
              "uv run python -m evals.bench.generate --repo /path/to/repo --seed 0 --max-cases 20\n" +
              "uv run python -m evals.bench.run --repo /path/to/repo --cases-dir evals/bench/cases/<repo-name>"}
          </pre>
        }
      />
    );
  }

  const modes = Object.keys(results.summary);
  const mutationTypes = Array.from(
    new Set(
      modes.flatMap((mode) =>
        Object.keys(results.summary[mode].by_mutation_type),
      ),
    ),
  );

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Benchmark</h1>
        <p className="text-muted-foreground text-sm">
          Context-mode ablation, generated{" "}
          {new Date(formatGeneratedAt(results.generated_at)).toLocaleString()}.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recall vs. false-positive rate by context mode</CardTitle>
        </CardHeader>
        <CardContent>
          <BenchmarkChart summary={results.summary} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>By mutation type</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Mutation type</TableHead>
                {modes.map((mode) => (
                  <TableHead key={mode} colSpan={2}>
                    {mode}
                  </TableHead>
                ))}
              </TableRow>
              <TableRow>
                <TableHead />
                {modes.map((mode) => (
                  <Fragment key={mode}>
                    <TableHead className="text-xs">recall</TableHead>
                    <TableHead className="text-xs">FP rate</TableHead>
                  </Fragment>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {mutationTypes.map((mutationType) => (
                <TableRow key={mutationType}>
                  <TableCell className="font-mono text-xs">
                    {mutationType}
                  </TableCell>
                  {modes.map((mode) => {
                    const stats =
                      results.summary[mode].by_mutation_type[mutationType];
                    return (
                      <Fragment key={mode}>
                        <TableCell>{formatPercent(stats?.recall)}</TableCell>
                        <TableCell>
                          {formatPercent(stats?.false_positive_rate)}
                        </TableCell>
                      </Fragment>
                    );
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Alert>
        <AlertTitle>How to read this</AlertTitle>
        <AlertDescription>
          <p>
            <strong>diff_only</strong> is a structural lower bound: the reviewer
            sees only the diff and the changed symbols, with no callers,
            callees, or tests surfaced from the index -- the breaking_change
            verify gate requires real caller evidence, which never appears in
            this mode, so breaking-change recall is expected to be near zero
            here. It exists to measure how much cross-file context actually buys
            you, not as a baseline a real deployment should run with.
          </p>
          {!modes.includes("naive") ? (
            <p>
              A <strong>naive</strong> mode (plain retrieval without graph
              expansion, the fairer apples-to-apples baseline against{" "}
              <strong>full</strong>) isn&apos;t implemented in the backend yet
              -- only <code>full</code> and <code>diff_only</code> exist as{" "}
              <code>REVIEW_CONTEXT_MODE</code> values today. This chart shows
              what&apos;s actually available.
            </p>
          ) : null}
        </AlertDescription>
      </Alert>
    </div>
  );
}

function formatPercent(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(0)}%`;
}

function formatGeneratedAt(generatedAt: string): string {
  // generatedAt looks like "20260114T153000Z" (the results filename's stem).
  const match = generatedAt.match(
    /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/,
  );
  if (!match) return generatedAt;
  const [, year, month, day, hour, minute, second] = match;
  return `${year}-${month}-${day}T${hour}:${minute}:${second}Z`;
}
