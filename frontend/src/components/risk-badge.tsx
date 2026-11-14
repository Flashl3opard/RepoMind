import { Badge } from "@/components/ui/badge";

const VARIANT_BY_RISK: Record<string, "destructive" | "warning" | "success"> = {
  high: "destructive",
  medium: "warning",
  low: "success",
};

export function RiskBadge({ risk }: { risk: string | null }) {
  if (!risk) return <Badge variant="secondary">Unknown</Badge>;
  const variant = VARIANT_BY_RISK[risk] ?? "secondary";
  return (
    <Badge variant={variant} className="capitalize">
      {risk} risk
    </Badge>
  );
}
