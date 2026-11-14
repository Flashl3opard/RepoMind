// Pure helpers for building GitHub blob URLs pinned to a specific commit, with a
// line-range anchor (#L10-L24, or #L10 for a single line). No I/O.

export interface GithubBlobUrlOptions {
  /** e.g. "https://github.com/owner/repo" or "https://github.com/owner/repo.git" */
  repoUrl: string;
  commitSha: string;
  filePath: string;
  startLine?: number;
  endLine?: number;
}

/** Extracts "owner/repo" from a GitHub HTTPS/SSH clone URL, or null if it doesn't look like one. */
export function parseGithubOwnerRepo(repoUrl: string): string | null {
  const cleaned = repoUrl.trim().replace(/\.git$/, "");
  const httpsMatch = cleaned.match(
    /^https?:\/\/github\.com\/([^/]+)\/([^/]+)\/?$/,
  );
  if (httpsMatch) return `${httpsMatch[1]}/${httpsMatch[2]}`;
  const sshMatch = cleaned.match(/^git@github\.com:([^/]+)\/([^/]+)$/);
  if (sshMatch) return `${sshMatch[1]}/${sshMatch[2]}`;
  return null;
}

/**
 * Builds a GitHub blob URL pinned to `commitSha`, with a line-range anchor.
 * Returns null if `repoUrl` isn't a recognizable github.com URL (e.g. a bare local
 * path used in tests/dev) -- callers should render plain text instead of a link.
 */
export function buildGithubBlobUrl(
  options: GithubBlobUrlOptions,
): string | null {
  const ownerRepo = parseGithubOwnerRepo(options.repoUrl);
  if (!ownerRepo) return null;

  const path = options.filePath.replace(/^\/+/, "");
  const base = `https://github.com/${ownerRepo}/blob/${options.commitSha}/${path}`;

  if (options.startLine == null) return base;

  const anchor =
    options.endLine != null && options.endLine !== options.startLine
      ? `#L${options.startLine}-L${options.endLine}`
      : `#L${options.startLine}`;

  return `${base}${anchor}`;
}
