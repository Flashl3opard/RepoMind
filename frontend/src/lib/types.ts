// Pure type re-exports from the generated OpenAPI types -- no "server-only" guard
// here, so pure/client-safe modules (severity.ts, components, tests) can import
// these shapes without pulling in api.ts's server-only runtime code.
import type { components } from "./api-types";

type Schemas = components["schemas"];

export type RepoListItem = Schemas["RepoListItem"];
export type RepoStatusResponse = Schemas["RepoStatusResponse"];
export type RepoCreateResponse = Schemas["RepoCreateResponse"];
export type AskResponse = Schemas["AskResponse"];
export type AskDebugInfo = Schemas["AskDebugInfo"];
export type DebugChunkResponse = Schemas["DebugChunkResponse"];
export type CitationResponse = Schemas["CitationResponse"];
export type ReviewResponse = Schemas["ReviewResponse"];
export type FindingResponse = Schemas["FindingResponse"];
export type ReviewRunListItem = Schemas["ReviewRunListItem"];
export type ReviewRunDetail = Schemas["ReviewRunDetail"];
export type RepositoryStatus = Schemas["RepositoryStatus"];
export type ReviewRunStatus = Schemas["ReviewRunStatus"];
