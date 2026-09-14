import { api } from "./api";
import type { Job } from "./types";

/** A queued operation survives navigation; its result remains in Background jobs. */
export async function waitForJob<T>(initial: Job): Promise<T> {
  let job = initial;
  const deadline = Date.now() + 2 * 60 * 60 * 1000;
  while (Date.now() < deadline) {
    if (job.status === "success") return job.result as T;
    if (job.status === "failed" || job.status === "cancelled")
      throw new Error(job.error || "Operation failed");
    await new Promise((resolve) => setTimeout(resolve, 1000));
    job = await api.get<Job>(`/system/jobs/${job.id}`);
  }
  throw new Error(
    "This operation is still queued or running. See Background jobs for its result.",
  );
}
