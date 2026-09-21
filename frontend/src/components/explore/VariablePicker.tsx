import { useEffect, useMemo, useRef, useState } from "react";

import { optionLabel } from "@/components/explore/shared";

import type { Variable } from "@/lib/types";

/**
 * Choose a variable by typing its name.
 *
 * A dropdown is fine for eleven provinces and useless for four hundred
 * questions: finding `h07_highest_grade` meant scrolling a list that had every
 * roster column in it, in export order, with no way to jump. So this filters
 * as you type, over the variable's name and its question wording both - the
 * name is what a person remembers from the questionnaire, the wording is what
 * they remember from the field.
 *
 * It stays a plain input until it is opened, so it reads as the rest of the
 * form and can be tabbed through the same way. The list is keyboard-driven
 * because picking one variable is rarely the only thing somebody is doing:
 * arrows move, Enter takes, Escape gives up and puts back what was there.
 */
export function VariablePicker({
  variables,
  value,
  onChange,
  label,
  /** Offered at the top, for the pickers where choosing nothing is a choice. */
  emptyOption,
  disabled,
  title,
  className = "",
}: {
  variables: Variable[];
  value: string;
  onChange: (next: string) => void;
  label: string;
  emptyOption?: string;
  disabled?: boolean;
  /** Hover text, for saying why a disabled picker is disabled. */
  title?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [active, setActive] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);

  const chosen = variables.find((v) => v.name === value);
  // What the input shows when it is not being typed into: the full label, so a
  // closed picker says as much as the old dropdown did.
  const settled = chosen ? optionLabel(chosen) : emptyOption ? emptyOption : "";

  const matches = useMemo(() => {
    const needle = typed.trim().toLowerCase();
    const all = needle
      ? variables.filter(
          (v) =>
            v.name.toLowerCase().includes(needle) ||
            (v.label ?? "").toLowerCase().includes(needle),
        )
      : variables;
    // Capped because a dataset can hold thousands and nobody reads past the
    // first screen; typing one more letter is faster than scrolling anyway.
    return all.slice(0, 200);
  }, [variables, typed]);

  // Anywhere else closes it, and what was chosen stays chosen.
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);

  // Keep the highlighted row in view while the arrows walk past the fold.
  useEffect(() => {
    if (!open) return;
    list.current?.children[active]?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  const take = (name: string) => {
    onChange(name);
    setTyped("");
    setOpen(false);
    input.current?.blur();
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      const step = event.key === "ArrowDown" ? 1 : -1;
      const count = rows.length;
      if (count) setActive((at) => (at + step + count) % count);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      const picked = rows[active];
      if (picked) take(picked.name);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setTyped("");
      setOpen(false);
      input.current?.blur();
    }
  };

  // "No rows" is offered while browsing, not while searching: it matches every
  // search, so leaving it in meant a search for something absent still showed
  // a row and never said it had found nothing.
  const offerEmpty = Boolean(emptyOption) && !typed.trim();
  const rows: { key: string; name: string; text: string }[] = [
    ...(offerEmpty ? [{ key: "__none", name: "", text: emptyOption! }] : []),
    ...matches.map((v) => ({ key: v.name, name: v.name, text: optionLabel(v) })),
  ];

  return (
    <div ref={box} className={`relative ${className}`}>
      <input
        ref={input}
        className="input"
        role="combobox"
        aria-expanded={open}
        aria-controls={`${label}-options`}
        aria-label={label}
        aria-autocomplete="list"
        autoComplete="off"
        spellCheck={false}
        disabled={disabled}
        title={title}
        // Typing replaces what is shown; leaving without choosing puts it back.
        value={open ? typed : settled}
        placeholder={settled || "Type to search"}
        onChange={(event) => {
          setTyped(event.target.value);
          setActive(0);
          setOpen(true);
        }}
        onFocus={() => {
          setTyped("");
          setActive(0);
          setOpen(true);
        }}
        onKeyDown={onKeyDown}
      />
      {open && (
        <ul
          ref={list}
          id={`${label}-options`}
          role="listbox"
          className="absolute z-30 mt-1 max-h-64 w-full overflow-auto rounded-card border border-ink-200 bg-white py-1 shadow-lg dark:border-dark-300 dark:bg-dark-100"
        >
          {!rows.length && (
            <li className="px-3 py-2 text-sm text-ink-400">
              No variable matches "{typed}"
            </li>
          )}
          {rows.map((row, index) => (
            <li key={row.key} role="option" aria-selected={row.name === value}>
              <button
                type="button"
                className={`flex w-full items-start px-3 py-1.5 text-left text-sm ${
                  index === active
                    ? "bg-brand-50 text-brand-900 dark:bg-dark-200"
                    : "text-ink-700 dark:text-dark-700"
                }`}
                // The pointer moves the highlight, so the mouse and the arrows
                // do not end up disagreeing about which row Enter would take.
                onMouseEnter={() => setActive(index)}
                // mousedown, not click: the input's blur would close the list
                // out from under a click and nothing would be chosen.
                onMouseDown={(event) => {
                  event.preventDefault();
                  take(row.name);
                }}
              >
                {row.text}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
