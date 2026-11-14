import { describe, expect, it } from "vitest";
import { buildGithubBlobUrl, parseGithubOwnerRepo } from "./github";

describe("parseGithubOwnerRepo", () => {
  it("parses a plain https URL", () => {
    expect(parseGithubOwnerRepo("https://github.com/owner/repo")).toBe(
      "owner/repo",
    );
  });

  it("parses an https URL with .git suffix", () => {
    expect(parseGithubOwnerRepo("https://github.com/owner/repo.git")).toBe(
      "owner/repo",
    );
  });

  it("parses an ssh URL", () => {
    expect(parseGithubOwnerRepo("git@github.com:owner/repo")).toBe(
      "owner/repo",
    );
  });

  it("returns null for a non-github URL", () => {
    expect(parseGithubOwnerRepo("https://gitlab.com/owner/repo")).toBeNull();
  });

  it("returns null for a local path", () => {
    expect(parseGithubOwnerRepo("/tmp/some/local/repo")).toBeNull();
  });
});

describe("buildGithubBlobUrl", () => {
  it("builds a URL with no line anchor when no lines given", () => {
    const url = buildGithubBlobUrl({
      repoUrl: "https://github.com/owner/repo",
      commitSha: "abc123",
      filePath: "src/main.py",
    });
    expect(url).toBe("https://github.com/owner/repo/blob/abc123/src/main.py");
  });

  it("builds a single-line anchor when start equals end", () => {
    const url = buildGithubBlobUrl({
      repoUrl: "https://github.com/owner/repo",
      commitSha: "abc123",
      filePath: "src/main.py",
      startLine: 10,
      endLine: 10,
    });
    expect(url).toBe(
      "https://github.com/owner/repo/blob/abc123/src/main.py#L10",
    );
  });

  it("builds a single-line anchor when only startLine is given", () => {
    const url = buildGithubBlobUrl({
      repoUrl: "https://github.com/owner/repo",
      commitSha: "abc123",
      filePath: "src/main.py",
      startLine: 10,
    });
    expect(url).toBe(
      "https://github.com/owner/repo/blob/abc123/src/main.py#L10",
    );
  });

  it("builds a range anchor when start and end differ", () => {
    const url = buildGithubBlobUrl({
      repoUrl: "https://github.com/owner/repo",
      commitSha: "abc123",
      filePath: "src/main.py",
      startLine: 10,
      endLine: 24,
    });
    expect(url).toBe(
      "https://github.com/owner/repo/blob/abc123/src/main.py#L10-L24",
    );
  });

  it("strips a leading slash from the file path", () => {
    const url = buildGithubBlobUrl({
      repoUrl: "https://github.com/owner/repo",
      commitSha: "abc123",
      filePath: "/src/main.py",
      startLine: 1,
    });
    expect(url).toBe(
      "https://github.com/owner/repo/blob/abc123/src/main.py#L1",
    );
  });

  it("returns null for a non-github repo URL", () => {
    const url = buildGithubBlobUrl({
      repoUrl: "/tmp/local/repo",
      commitSha: "abc123",
      filePath: "src/main.py",
    });
    expect(url).toBeNull();
  });

  it("handles a .git suffix on the repo URL", () => {
    const url = buildGithubBlobUrl({
      repoUrl: "https://github.com/owner/repo.git",
      commitSha: "deadbeef",
      filePath: "a.py",
      startLine: 5,
      endLine: 7,
    });
    expect(url).toBe("https://github.com/owner/repo/blob/deadbeef/a.py#L5-L7");
  });
});
