import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useState } from "react";

import "react-grid-layout/css/styles.css";

import "react-resizable/css/styles.css";

import { api, shareGrants } from "@/lib/api";

import { useToast } from "@/hooks/useToast";

import type { Dashboard } from "@/lib/types";

import { Badge, Card, Field } from "@/components/ui";

/** The public link, and the name it can also answer on.
 *
 *  A token URL is unguessable, which is what makes it safe to paste to one
 *  person. A hostname is the opposite by design - it is meant to be typed from
 *  memory - so the two sit together here and the difference is stated rather
 *  than left to be discovered.
 */
export function PublicLinkBar({
  dashboard,
  canEdit,
}: {
  dashboard: Dashboard;
  canEdit: boolean;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [naming, setNaming] = useState(false);
  const [label, setLabel] = useState("");

  const info = useQuery({
    queryKey: ["platform-info"],
    queryFn: () => api.get<{ dashboard_domain: string }>("/system/info"),
    staleTime: 5 * 60 * 1000,
  });
  const domain = info.data?.dashboard_domain ?? "";

  const save = useMutation({
    mutationFn: (hostname: string) =>
      api.put<Dashboard>(`/dashboards/${dashboard.id}/hostname`, { hostname }),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["dashboard", dashboard.id] });
      setNaming(false);
      setLabel("");
      toast.push(
        updated.public_hostname
          ? `This dashboard now answers on ${updated.public_hostname}`
          : "The name was removed",
        "success",
      );
    },
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  return (
    <div className="mb-4 rounded-card border border-brand-200 bg-brand-50 px-4 py-2.5 text-sm text-brand-800">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="info" icon="⇗">
          Public
        </Badge>
        <span>Anyone with this link can view the dashboard:</span>
        <code className="rounded bg-white px-2 py-0.5 text-xs">
          {location.origin}/shared/{dashboard.public_token}
        </code>
      </div>

      {dashboard.public_hostname && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span>It also answers on:</span>
          <a
            className="rounded bg-white px-2 py-0.5 font-mono text-xs"
            href={`https://${dashboard.public_hostname}`}
            target="_blank"
            rel="noreferrer"
          >
            {dashboard.public_hostname}
          </a>
          {canEdit && (
            <button
              className="btn-ghost btn-sm text-red-600"
              onClick={() => save.mutate("")}
              disabled={save.isPending}
            >
              Remove the name
            </button>
          )}
        </div>
      )}

      {canEdit && !dashboard.public_hostname && domain && !naming && (
        <button
          className="btn-ghost btn-sm mt-1"
          onClick={() => setNaming(true)}
        >
          Give it a name…
        </button>
      )}

      {canEdit && naming && domain && (
        <div className="mt-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <input
              className="input w-56 py-1 text-xs"
              placeholder="labour-force"
              value={label}
              autoFocus
              onChange={(event) => setLabel(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && label.trim())
                  save.mutate(label.trim());
                if (event.key === "Escape") setNaming(false);
              }}
            />
            <span className="font-mono text-xs">.{domain}</span>
            <button
              className="btn-primary btn-sm"
              onClick={() => save.mutate(label.trim())}
              disabled={!label.trim() || save.isPending}
            >
              Assign
            </button>
            <button
              className="btn-ghost btn-sm"
              onClick={() => setNaming(false)}
            >
              Cancel
            </button>
          </div>
          <p className="mt-1.5 text-xs text-brand-800/80">
            A name is meant to be typed from memory, so it is not a secret the
            way the link above is: anyone who guesses it reaches this dashboard.
          </p>
        </div>
      )}
    </div>
  );
}

/**
 * The door in front of a password-protected shared link.
 *
 * The password is traded once for a grant that the other routes accept, rather
 * than sent with every request: the hash behind it is deliberately slow, and a
 * dashboard on an office wall refreshing every minute would otherwise spend
 * its life being hashed.
 */
export function SharePasswordPrompt({
  token,
  onUnlocked,
}: {
  token: string;
  onUnlocked: () => void;
}) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { grant } = await api.post<{ grant: string }>(
        `/public/dashboards/${token}/unlock`,
        { password },
      );
      shareGrants.set(token, grant);
      onUnlocked();
    } catch (caught) {
      setError((caught as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-sm py-16">
      <Card>
        <h1 className="text-base font-semibold text-ink-800">
          This dashboard is protected
        </h1>
        <p className="mt-1 text-sm text-ink-600">
          Enter the password you were given with the link.
        </p>
        <form className="mt-4" onSubmit={submit}>
          <Field label="Password">
            <input
              className="input"
              type="password"
              autoFocus
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </Field>
          {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
          <button
            className="btn-primary w-full"
            type="submit"
            disabled={busy || !password}
          >
            {busy ? "Checking…" : "Open dashboard"}
          </button>
        </form>
      </Card>
    </div>
  );
}
