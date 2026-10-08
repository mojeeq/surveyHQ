import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useDialog } from "@/hooks/useDialog";
import { useToast } from "@/hooks/useToast";

export default function DatasetVersions({
  datasetId,
  version,
}: {
  datasetId: string;
  version: number;
}) {
  const client = useQueryClient();
  const toast = useToast();
  const ask = useDialog();
  const versions = useQuery({
    queryKey: ["dataset-versions", datasetId, version],
    queryFn: () =>
      api.get<{ version: number; rows: number; columns: number }[]>(
        `/datasets/${datasetId}/versions`,
      ),
  });
  const restore = useMutation({
    mutationFn: (v: number) =>
      api.post(`/datasets/${datasetId}/versions/${v}/restore`),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: ["dataset", datasetId] });
      client.invalidateQueries({ queryKey: ["datasets"] });
      toast.push("Dataset version restored", "success");
    },
    onError: (error: Error) => toast.push(error.message, "error"),
  });
  if (!versions.data?.length) return null;
  return (
    <details className="my-4 rounded-card border p-3">
      <summary className="cursor-pointer font-medium">
        Previous dataset versions
      </summary>
      <p className="my-2 text-sm">
        Restoring creates a new current version and rebuilds dependent merges.
      </p>
      {versions.data.map((v) => (
        <div
          key={v.version}
          className="flex items-center justify-between py-1 text-sm"
        >
          <span>
            Version {v.version} · {v.rows.toLocaleString()} rows · {v.columns}{" "}
            variables
          </span>
          <button
            className="btn-secondary btn-sm"
            disabled={restore.isPending}
            onClick={async () => {
              const sure = await ask.confirm({
                title: `Restore version ${v.version}?`,
                message: "The current version is kept as well, so nothing is lost.",
                confirmLabel: "Restore",
              });
              if (sure) restore.mutate(v.version);
            }}
          >
            Restore version {v.version}
          </button>
        </div>
      ))}
    </details>
  );
}
