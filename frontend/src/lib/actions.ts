"use server";

import { revalidatePath } from "next/cache";

import {
  askRepository,
  createRepository,
  getRepository,
  reviewRepository,
  type AskResponse,
  type RepoCreateResponse,
  type RepoStatusResponse,
  type ReviewResponse,
} from "@/lib/api";

export interface ActionResult<T> {
  ok: boolean;
  data?: T;
  error?: string;
}

export async function createRepoAction(
  url: string,
): Promise<ActionResult<RepoCreateResponse>> {
  if (!url.trim()) return { ok: false, error: "A repository URL is required." };
  try {
    const data = await createRepository(url.trim());
    revalidatePath("/");
    return { ok: true, data };
  } catch (error) {
    return { ok: false, error: errorMessage(error) };
  }
}

/** Called repeatedly by the client-side poller on /repos/[id] until the repo is
 * complete or failed. Review endpoints never post to GitHub, so results here are
 * always safe to display immediately -- there's no separate "dry run" concept for
 * the manual API, only for the GitHub App's webhook-driven posting. */
export async function getRepoStatusAction(
  id: string,
): Promise<ActionResult<RepoStatusResponse>> {
  try {
    const data = await getRepository(id);
    return { ok: true, data };
  } catch (error) {
    return { ok: false, error: errorMessage(error) };
  }
}

export async function askAction(
  repositoryId: string,
  question: string,
  debug: boolean,
): Promise<ActionResult<AskResponse>> {
  if (!question.trim()) return { ok: false, error: "Ask a question first." };
  try {
    const data = await askRepository(repositoryId, question.trim(), debug);
    return { ok: true, data };
  } catch (error) {
    return { ok: false, error: errorMessage(error) };
  }
}

export async function runReviewAction(
  repositoryId: string,
  diff: string,
): Promise<ActionResult<ReviewResponse>> {
  if (!diff.trim()) return { ok: false, error: "Paste a unified diff first." };
  try {
    const data = await reviewRepository(repositoryId, { diff });
    return { ok: true, data };
  } catch (error) {
    return { ok: false, error: errorMessage(error) };
  }
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Unexpected error talking to the backend.";
}
