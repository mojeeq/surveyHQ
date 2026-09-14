import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
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
            onClick={() => {
              if (
                window.confirm(
                  `Restore version ${v.version}? The current version will also be retained.`,
                )
              )
                restore.mutate(v.version);
            }}
          >
            Restore version {v.version}
          </button>
        </div>
      ))}
    </details>
  );
}
