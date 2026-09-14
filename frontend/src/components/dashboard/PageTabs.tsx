import "react-grid-layout/css/styles.css";

import "react-resizable/css/styles.css";

/**
 * The state of a dataset's data quality checks.
 *
 * Failing checks are listed first and in full; passing ones are a count. A
 * panel that lists thirty green rows buries the one red one, which is the only
 * row anybody opened the dashboard to see.
 */
/**
 * Pages across a dashboard.
 *
 * Hidden entirely until there is more than one, so a dashboard that does not
 * use pages does not grow a tab strip saying "Page 1". Adding the second page
 * has to name the first as well, since an unnamed page cannot be labelled.
 */
export function PageTabs({
  pages,
  active,
  count,
  canEdit,
  widgetsOnPage,
  onDark,
  band,
  color,
  onSelect,
  onChange,
  onMove,
  onRemove,
}: {
  pages: { name?: string }[];
  active: number;
  count: number;
  canEdit: boolean;
  widgetsOnPage: number;
  /** Set when whatever is behind the tabs is dark enough to swallow ink text. */
  onDark: boolean;
  /** A colour to lay behind the strip, for a background that swallows it. */
  band?: string;
  /** The tab text, chosen rather than worked out from what is behind it. */
  color?: string;
  onSelect: (index: number) => void;
  onChange: (pages: { name: string }[]) => void;
  onMove: (from: number, to: number) => void;
  onRemove: (index: number) => void;
}) {
  const named = Array.from({ length: count }, (_, index) => ({
    name: pages[index]?.name || `Page ${index + 1}`,
  }));

  /** Two tabs reading the same word cannot be told apart. */
  const taken = (name: string, except = -1) =>
    named.some(
      (page, i) =>
        i !== except && page.name.toLowerCase() === name.toLowerCase(),
    );

  const addPage = () => {
    const name = prompt("Name for the new page")?.trim();
    if (!name) return;
    if (taken(name)) {
      alert(`This dashboard already has a page called "${name}".`);
      return;
    }
    onChange([...named, { name }]);
    onSelect(count);
  };

  const renamePage = (index: number) => {
    const name = prompt("Rename this page", named[index].name)?.trim();
    if (!name || name === named[index].name) return;
    if (taken(name, index)) {
      alert(`This dashboard already has a page called "${name}".`);
      return;
    }
    onChange(named.map((page, i) => (i === index ? { name } : page)));
  };

  const removePage = (index: number) => {
    if (widgetsOnPage > 0) {
      alert("Move or remove this page\u2019s widgets before deleting it.");
      return;
    }
    if (!confirm(`Delete the page "${named[index].name}"?`)) return;
    // Deleted on the server, which renumbers the pages after it along with
    // their widgets. Filtering the list here would leave those widgets on
    // whichever page ended up at their old number.
    onRemove(index);
    onSelect(Math.max(0, index - 1));
  };

  if (count <= 1 && !canEdit) return null;

  return (
    // Two groups, not one run of buttons. The tabs wrap among themselves and
    // the page controls stay together at the end: mixed into one wrapping row,
    // a twelfth tab came to rest between "Rename" and "Delete page", where it
    // reads as one of the controls rather than as a page.
    <div
      className={`mb-4 flex flex-wrap items-end justify-between gap-x-2 border-b ${
        onDark ? "border-white/25" : "border-ink-200"
      } ${band ? "rounded-t-lg px-2" : ""}`}
      style={band ? { backgroundColor: band } : undefined}
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-1">
        {(count > 1 || canEdit) &&
          named.map((page, index) => (
            <button
              key={index}
              onClick={() => onSelect(index)}
              onDoubleClick={() => canEdit && renamePage(index)}
              title={
                canEdit
                  ? "Double-click to rename, or use the Rename button"
                  : undefined
              }
              className={`whitespace-nowrap border-b-2 px-3.5 py-2.5 text-sm font-medium transition-colors ${
                active === index
                  ? onDark
                    ? "border-white text-white"
                    : "border-brand-600 text-brand-700"
                  : onDark
                    ? "border-transparent text-white/70 hover:text-white"
                    : "border-transparent text-ink-500 hover:text-ink-800"
              }`}
              // A chosen colour wins over the light-or-dark guess. The page that
              // is open keeps its underline in that colour too, so which page you
              // are on does not stop being visible when the ink changes.
              style={
                color
                  ? {
                      color,
                      borderBottomColor:
                        active === index ? color : "transparent",
                      opacity: active === index ? 1 : 0.75,
                    }
                  : undefined
              }
            >
              {page.name}
            </button>
          ))}
      </div>
      {canEdit && (
        <div className="flex shrink-0 flex-wrap items-center gap-x-1 py-1">
          <button
            className={`btn-ghost btn-sm ${onDark ? "text-white/80" : "text-ink-500"}`}
            style={color ? { color, opacity: 0.8 } : undefined}
            onClick={addPage}
          >
            + Page
          </button>
          {/* Renaming used to be a double-click on the tab and nothing said so,
              which is no way to find a feature. */}
          <button
            className={`btn-ghost btn-sm ${onDark ? "text-white/80" : "text-ink-500"}`}
            style={color ? { color, opacity: 0.8 } : undefined}
            onClick={() => renamePage(active)}
          >
            Rename
          </button>
          {count > 1 && (
            <>
              <button
                className={`btn-ghost btn-sm ${onDark ? "text-white/80" : "text-ink-500"}`}
                style={color ? { color, opacity: 0.8 } : undefined}
                onClick={() => onMove(active, active - 1)}
                disabled={active === 0}
                title="Move this page earlier"
              >
                ◀
              </button>
              <button
                className={`btn-ghost btn-sm ${onDark ? "text-white/80" : "text-ink-500"}`}
                style={color ? { color, opacity: 0.8 } : undefined}
                onClick={() => onMove(active, active + 1)}
                disabled={active === count - 1}
                title="Move this page later"
              >
                ▶
              </button>
              <button
                className="btn-ghost btn-sm text-red-600"
                onClick={() => removePage(active)}
              >
                Delete page
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
