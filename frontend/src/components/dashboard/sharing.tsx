import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useState } from "react";

import "react-grid-layout/css/styles.css";

import "react-resizable/css/styles.css";

import { api, shareGrants } from "@/lib/api";

import { copyText } from "@/lib/clipboard";

import { useToast } from "@/hooks/useToast";

import type { Dashboard } from "@/lib/types";

import { Card, Field } from "@/components/ui";

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

  const url = `${location.origin}/shared/${dashboard.public_token}`;

  const copy = async (text: string) => {
    if (await copyText(text)) {
      toast.push("Link copied to your clipboard", "success");
      return;
    }
    // A browser that refuses every way of copying is not worth an error
    // banner: the address is on screen to be selected.
    toast.push("Copy the link from the box", "info");
  };

  return (
    // One row, no panel. A share link is a property of the dashboard, like the
    // "Data as of" line below it - not an announcement that needs a tinted box
    // and a coloured rail to be noticed.
    <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-ink-200 pb-2.5 text-sm dark:border-dark-200">
      <span className="text-ink-500 dark:text-dark-500">Public link</span>
      <a
        className="break-all font-mono text-xs text-ink-900 hover:underline dark:text-dark-900"
        href={url}
        target="_blank"
        rel="noreferrer"
      >
        {url}
      </a>
      <button
        className="btn-ghost btn-sm -my-1"
        onClick={() => copy(url)}
      >
        Copy
      </button>
      <span className="text-xs text-ink-400 dark:text-dark-400">
        Anyone holding it can view the dashboard, so treat it like the data.
      </span>

      {dashboard.public_hostname && (
        <>
          <span className="basis-full" />
          <span className="text-ink-500 dark:text-dark-500">Also at</span>
          <a
            className="break-all font-mono text-xs text-ink-900 hover:underline dark:text-dark-900"
            href={`https://${dashboard.public_hostname}`}
            target="_blank"
            rel="noreferrer"
          >
            {dashboard.public_hostname}
          </a>
          <span className="text-xs text-ink-400 dark:text-dark-400">
            Guessable, unlike the link above.
          </span>
          {canEdit && (
            <button
              className="btn-ghost btn-sm -my-1 text-red-600"
              onClick={() => save.mutate("")}
              disabled={save.isPending}
            >
              Remove
            </button>
          )}
        </>
      )}

      {canEdit && !dashboard.public_hostname && domain && !naming && (
        <button className="btn-ghost btn-sm -my-1" onClick={() => setNaming(true)}>
          Give it a name…
        </button>
      )}

      {canEdit && naming && domain && (
        <>
          <span className="basis-full" />
          <input
            className="input w-56 py-1 text-sm"
            placeholder="labour-force"
            value={label}
            autoFocus
            onChange={(event) => setLabel(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && label.trim()) save.mutate(label.trim());
              if (event.key === "Escape") setNaming(false);
            }}
          />
          <span className="font-mono text-xs text-ink-600 dark:text-dark-600">
            .{domain}
          </span>
          <button
            className="btn-primary btn-sm -my-1"
            onClick={() => save.mutate(label.trim())}
            disabled={!label.trim() || save.isPending}
          >
            Assign
          </button>
          <button className="btn-ghost btn-sm -my-1" onClick={() => setNaming(false)}>
            Cancel
          </button>
        </>
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
