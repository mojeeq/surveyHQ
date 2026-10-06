import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useState } from "react";

import { api } from "@/lib/api";

import { useToast } from "@/hooks/useToast";

import { formatBytes, relativeTime } from "@/lib/format";

import { readySchedule } from "@/lib/schedule";

import type { Dashboard, DashboardSnapshot, SnapshotSchedule } from "@/lib/types";

import { Card, EmptyState, ErrorNote, Field, Loading, Modal, Toggle } from "@/components/ui";

/** Monday first, matching the server's numbering and most of the world's weeks. */
const DAYS = [
  { value: 0, short: "Mon" },
  { value: 1, short: "Tue" },
  { value: 2, short: "Wed" },
  { value: 3, short: "Thu" },
  { value: 4, short: "Fri" },
  { value: 5, short: "Sat" },
  { value: 6, short: "Sun" },
];

const BLANK: SnapshotSchedule = {
  enabled: false,
  times: ["08:00"],
  days: [],
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  keep: 12,
};

/**
 * Keeping the board as it stood, and the schedule that does it.
 *
 * A saved view remembers which filters were chosen and nothing else, so a
 * board opened through one always shows today's numbers. This is the part
 * that answers "what did we have on the 7th".
 */
export default function Snapshots({
  dashboard,
  canEdit,
  onClose,
}: {
  dashboard: Dashboard;
  canEdit: boolean;
  onClose: () => void;
}) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const key = ["dashboard-snapshots", dashboard.id];

  const list = useQuery({
    queryKey: key,
    queryFn: () =>
      api.get<DashboardSnapshot[]>(`/dashboards/${dashboard.id}/snapshots`),
  });
  const schedule = useQuery({
    queryKey: ["snapshot-schedule", dashboard.id],
    queryFn: () =>
      api.get<SnapshotSchedule>(`/dashboards/${dashboard.id}/snapshot-schedule`),
  });

  const [draft, setDraft] = useState<SnapshotSchedule | null>(null);
  const plan = draft ?? readySchedule(schedule.data, BLANK);
  const edit = (patch: Partial<SnapshotSchedule>) =>
    setDraft({ ...plan, ...patch });

  const save = useMutation({
    mutationFn: (next: SnapshotSchedule) =>
      api.put<SnapshotSchedule>(
        `/dashboards/${dashboard.id}/snapshot-schedule`,
        next,
      ),
    onSuccess: (next) => {
      setDraft(null);
      queryClient.invalidateQueries({ queryKey: ["snapshot-schedule", dashboard.id] });
      toast.push(
        next.enabled ? "The board will be kept on that schedule" : "Schedule off",
        "success",
      );
    },
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  const takeNow = useMutation({
    mutationFn: () =>
      api.post<DashboardSnapshot>(`/dashboards/${dashboard.id}/snapshots`, {}),
    onSuccess: (snapshot) => {
      queryClient.invalidateQueries({ queryKey: key });
      toast.push(`Kept "${snapshot.label}"`, "success");
    },
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  const remove = useMutation({
    mutationFn: (snapshot: DashboardSnapshot) =>
      api.delete(`/dashboards/${dashboard.id}/snapshots/${snapshot.id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: key }),
    onError: (error: Error) => toast.push(error.message, "error"),
  });

  // An <a href> cannot carry the Authorization header, so the file is fetched
  // and shown from an object URL. The tab is opened inside the click rather
  // than after the await: a window opened once the promise settles is no
  // longer part of a user gesture, and Safari blocks it.
  const open = async (snapshot: DashboardSnapshot) => {
    const tab = window.open("", "_blank");
    try {
      const file = await api.getBlob(
        `/dashboards/${dashboard.id}/snapshots/${snapshot.id}.html`,
      );
      const url = URL.createObjectURL(file);
      if (tab) tab.location.href = url;
      else window.location.href = url;
      // Long enough for the tab to have loaded it, rather than never.
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (error) {
      tab?.close();
      toast.push((error as Error).message, "error");
    }
  };

  const toggleDay = (day: number) =>
    edit({
      days: plan.days.includes(day)
        ? plan.days.filter((other) => other !== day)
        : [...plan.days, day].sort((a, b) => a - b),
    });

  return (
    <Modal open title="Keep a copy of this board" onClose={onClose} wide>
      <p className="mb-4 max-w-2xl text-sm text-ink-600 dark:text-dark-600">
        A saved view remembers which filters were chosen, so it always opens on
        today's numbers. A copy is the board as it stood: open the one from last
        Monday and you see last Monday.
      </p>

      {canEdit && (
        <Card className="mb-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Toggle
              checked={plan.enabled}
              onChange={(on) => edit({ enabled: on })}
              label="Keep one automatically"
            />
            <button
              className="btn-secondary btn-sm"
              onClick={() => takeNow.mutate()}
              disabled={takeNow.isPending}
            >
              {takeNow.isPending ? "Keeping…" : "Keep one now"}
            </button>
          </div>

          {plan.enabled && (
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <Field label="At">
                <input
                  type="time"
                  className="input"
                  value={plan.times[0]}
                  onChange={(event) => edit({ times: [event.target.value] })}
                />
              </Field>
              <Field label="Time zone">
                <input
                  className="input"
                  value={plan.timezone}
                  onChange={(event) => edit({ timezone: event.target.value })}
                />
              </Field>
              <div className="sm:col-span-2">
                <p className="mb-1.5 text-sm font-medium text-ink-700 dark:text-dark-700">
                  On
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {DAYS.map((day) => (
                    <button
                      key={day.value}
                      className={`rounded-full border px-3 py-1 text-sm ${
                        plan.days.includes(day.value)
                          ? "border-brand-500 bg-brand-500 text-white"
                          : "border-ink-300 bg-white text-ink-700 hover:bg-ink-50 dark:border-dark-300 dark:bg-dark-50 dark:text-dark-700"
                      }`}
                      onClick={() => toggleDay(day.value)}
                    >
                      {day.short}
                    </button>
                  ))}
                </div>
                <p className="mt-1.5 text-xs text-ink-500 dark:text-dark-500">
                  {plan.days.length === 0
                    ? "Nothing chosen means every day."
                    : `Every ${plan.days.map((d) => DAYS[d].short).join(", ")}.`}
                </p>
              </div>
              <Field
                label="Keep the last"
                hint="Older automatic copies are removed. Ones you take by hand are kept."
              >
                <input
                  type="number"
                  min={1}
                  max={365}
                  className="input"
                  value={plan.keep}
                  onChange={(event) =>
                    edit({ keep: Number(event.target.value) || 1 })
                  }
                />
              </Field>
            </div>
          )}

          {draft && (
            <div className="mt-4 flex items-center gap-2">
              <button
                className="btn-primary btn-sm"
                onClick={() => save.mutate(plan)}
                disabled={save.isPending}
              >
                Save the schedule
              </button>
              <button className="btn-ghost btn-sm" onClick={() => setDraft(null)}>
                Cancel
              </button>
            </div>
          )}
        </Card>
      )}

      {list.isLoading ? (
        <Loading />
      ) : list.error ? (
        <ErrorNote error={list.error} retry={list.refetch} />
      ) : !list.data?.length ? (
        <EmptyState
          icon="◫"
          title="No copies kept yet"
          description="Keep one now, or set a schedule and the board will keep itself."
        />
      ) : (
        <ul className="divide-y divide-ink-200 dark:divide-dark-200">
          {list.data.map((snapshot) => (
            <li
              key={snapshot.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5"
            >
              <button
                className="font-medium text-ink-900 hover:underline dark:text-dark-900"
                onClick={() => open(snapshot)}
              >
                {snapshot.label}
              </button>
              <span className="text-xs text-ink-500 dark:text-dark-500">
                {relativeTime(snapshot.taken_at)} · {formatBytes(snapshot.size_bytes)}
                {snapshot.is_automatic ? "" : " · taken by hand"}
              </span>
              {canEdit && (
                <button
                  className="btn-ghost btn-sm ml-auto text-red-600"
                  onClick={() => {
                    if (confirm(`Delete the copy from ${snapshot.label}?`))
                      remove.mutate(snapshot);
                  }}
                >
                  Delete
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
