import { useState } from "react";
import { api } from "@/lib/api";
import type { ArchiveImport } from "@/lib/types";
import { Modal } from "@/components/ui";

export interface Review {
  review: true;
  job_id: string;
  warnings: string[];
  changes: {
    name: string;
    before_rows: number;
    after_rows: number;
    duplicate_rows: number;
    added_variables: string[];
    removed_variables: string[];
    changed_variables: string[];
    affected_indicators: string[];
    warnings: string[];
  }[];
}

export default function ImportReview({
  review,
  onAccepted,
  onClose,
}: {
  review: Review;
  onAccepted: (result: ArchiveImport) => void;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function accept() {
    setBusy(true);
    try {
      onAccepted(
        await api.post<ArchiveImport>(
          `/datasets/reviews/${review.job_id}/accept`,
        ),
      );
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function discard() {
    setBusy(true);
    try {
      await api.delete(`/datasets/reviews/${review.job_id}`);
      onClose();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open
      title="Review import changes"
      onClose={() => {
        if (!busy) void discard();
      }}
      footer={
        <>
          <button className="btn-secondary" disabled={busy} onClick={discard}>
            Discard import
          </button>
          <button className="btn-primary" disabled={busy} onClick={accept}>
            {busy ? "Working…" : "Accept import"}
          </button>
        </>
      }
    >
      <p className="mb-4 text-sm">
        Check these changes before updating your datasets. Existing charts keep
        using the current data until you accept.
      </p>
      {error && (
        <p role="alert" className="text-red-700">
          {error}
        </p>
      )}
      {review.changes.map((change, index) => (
        <section key={index} className="mb-4 rounded-card border p-3">
          <h3 className="font-semibold">{change.name}</h3>
          <p>
            Rows: {change.before_rows.toLocaleString()} →{" "}
            {change.after_rows.toLocaleString()}
          </p>
          <dl className="mt-2 text-sm">
            <dt>Added variables</dt>
            <dd>{change.added_variables.join(", ") || "None"}</dd>
            <dt>Removed variables</dt>
            <dd>{change.removed_variables.join(", ") || "None"}</dd>
            <dt>Changed types or labels</dt>
            <dd>{change.changed_variables.join(", ") || "None"}</dd>
            <dt>Duplicate complete rows</dt>
            <dd>{change.duplicate_rows}</dd>
            <dt>Affected indicators</dt>
            <dd>{change.affected_indicators.join(", ") || "None"}</dd>
          </dl>
          {change.warnings.map((warning, i) => (
            <p className="mt-2 text-sm text-amber-700" key={i}>
              {warning}
            </p>
          ))}
        </section>
      ))}
      {review.warnings.map((warning, i) => (
        <p className="text-sm text-amber-700" key={i}>
          {warning}
        </p>
      ))}
    </Modal>
  );
}
