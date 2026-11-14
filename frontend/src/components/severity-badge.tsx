import { Badge } from "@/components/ui/badge";

const VARIANT_BY_SEVERITY: Record<
  string,
  "destructive" | "warning" | "secondary"
> = {
  error: "destructive",
  warning: "warning",
  info: "secondary",
};

export function SeverityBadge({ severity }: { severity: string }) {
  const variant = VARIANT_BY_SEVERITY[severity] ?? "secondary";
  return (
    <Badge variant={variant} className="uppercase">
      {severity}
    </Badge>
  );
}
