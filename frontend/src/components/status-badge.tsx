import { Badge } from "@/components/ui/badge";
import type { RepositoryStatus, ReviewRunStatus } from "@/lib/types";

type AnyStatus = RepositoryStatus | ReviewRunStatus | string;

const VARIANT_BY_STATUS: Record<
  string,
  "default" | "secondary" | "destructive" | "warning" | "success"
> = {
  pending: "secondary",
  queued: "secondary",
  cloning: "warning",
  parsing: "warning",
  embedding: "warning",
  running: "warning",
  completed: "success",
  done: "success",
  failed: "destructive",
  skipped: "secondary",
};

const LABEL_BY_STATUS: Record<string, string> = {
  pending: "Pending",
  queued: "Queued",
  cloning: "Cloning",
  parsing: "Parsing",
  embedding: "Embedding",
  running: "Running",
  completed: "Complete",
  done: "Done",
  failed: "Failed",
  skipped: "Skipped",
};

export function StatusBadge({ status }: { status: AnyStatus }) {
  const variant = VARIANT_BY_STATUS[status] ?? "default";
  const label = LABEL_BY_STATUS[status] ?? status;
  return <Badge variant={variant}>{label}</Badge>;
}
