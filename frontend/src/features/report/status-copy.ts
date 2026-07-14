import type { components } from "@/lib/api/schema";

export type JobStatus = components["schemas"]["JobStatus"];

export function isTerminalStatus(status: JobStatus): boolean {
  return status === "done" || status === "failed";
}
