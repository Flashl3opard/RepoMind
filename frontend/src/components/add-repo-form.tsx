"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createRepoAction } from "@/lib/actions";

export function AddRepoForm() {
  const [url, setUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const router = useRouter();

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    startTransition(async () => {
      const result = await createRepoAction(url);
      if (!result.ok) {
        setError(result.error ?? "Failed to add repository.");
        return;
      }
      setUrl("");
      router.refresh();
    });
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <div className="flex items-end gap-2">
        <div className="flex flex-1 flex-col gap-1.5">
          <Label htmlFor="repo-url">Repository URL</Label>
          <Input
            id="repo-url"
            placeholder="https://github.com/owner/repo"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            disabled={isPending}
            required
          />
        </div>
        <Button type="submit" disabled={isPending}>
          {isPending ? <Loader2 className="animate-spin" /> : null}
          Add repository
        </Button>
      </div>
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
    </form>
  );
}
