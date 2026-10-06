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
    <div className="mb-4 overflow-hidden rounded-card border border-brand-200 bg-white dark:border-brand-500/30 dark:bg-dark-50">
      {/* A rail rather than a wash across the whole strip. A tinted bar the
          width of the page reads as a browser warning; this reads as a
          property of the dashboard, which is what it is. */}
      <div className="border-l-4 border-brand-500 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-brand-700 dark:text-brand-400">
            Public link
          </p>
          <div className="flex items-center gap-1">
            <button className="btn-ghost btn-sm" onClick={() => copy(url)}>
              Copy
            </button>
            <a
              className="btn-ghost btn-sm"
              href={url}
              target="_blank"
              rel="noreferrer"
            >
              Open
            </a>
          </div>
        </div>

        {/* The address is what somebody came to this bar for, so it is the
            largest thing in it rather than a footnote after the sentence
            explaining it. Selectable on its own line: a token wraps badly
            inside a paragraph, and half a token pasted is no link at all. */}
        <p className="mt-1.5 select-all break-all font-mono text-sm text-ink-900 dark:text-dark-900">
          {url}
        </p>
        <p className="mt-1 max-w-2xl text-xs text-ink-500 dark:text-dark-500">
          Anyone holding this link can view the dashboard without signing in.
          It is unguessable, so it is safe to send to one person and unsafe to
          publish anywhere you would not publish the data.
        </p>

        {dashboard.public_hostname && (
          <div className="mt-3 border-t border-ink-200 pt-3 dark:border-dark-200">
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-ink-500 dark:text-dark-500">
                Also answers on
              </p>
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
            <a
              className="mt-1.5 inline-block break-all font-mono text-sm text-brand-700 hover:underline dark:text-brand-400"
              href={`https://${dashboard.public_hostname}`}
              target="_blank"
              rel="noreferrer"
            >
              {dashboard.public_hostname}
            </a>
            <p className="mt-1 max-w-2xl text-xs text-ink-500 dark:text-dark-500">
              A name is meant to be typed from memory, so unlike the link above
              it is not a secret: anyone who guesses it reaches this dashboard.
            </p>
          </div>
        )}

        {canEdit && !dashboard.public_hostname && domain && !naming && (
          <button
            className="btn-ghost btn-sm mt-2 -ml-2"
            onClick={() => setNaming(true)}
          >
            Give it a memorable name…
          </button>
        )}

        {canEdit && naming && domain && (
          <div className="mt-3 border-t border-ink-200 pt-3 dark:border-dark-200">
            <div className="flex flex-wrap items-center gap-1.5">
              <input
                className="input w-56 py-1 text-sm"
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
              <span className="font-mono text-sm text-ink-600 dark:text-dark-600">
                .{domain}
              </span>
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
            <p className="mt-1.5 text-xs text-ink-500 dark:text-dark-500">
              A name is meant to be typed from memory, so it is not a secret the
              way the link above is: anyone who guesses it reaches this
              dashboard.
            </p>
          </div>
        )}
      </div>
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
