import { useEffect, useRef, useState } from "react";

import { createPortal } from "react-dom";

import "react-grid-layout/css/styles.css";

import "react-resizable/css/styles.css";

/** One line on a widget's menu. */
export type MenuItem = {
  label: string;
  onClick: () => void;
  /** A tick down the left, for the choice that is already in force. */
  checked?: boolean;
  danger?: boolean;
};

/**
 * Everything you can do to a widget, behind one button.
 *
 * These used to sit side by side in the title bar - copy, expand, which page,
 * edit, remove - and on a narrow tile they left the title a few characters
 * wide. A menu costs one more click on things nobody does twice a minute and
 * gives the title the bar back.
 *
 * The menu is portalled to the body and placed from the button's own position.
 * A widget sits inside a card that clips what overflows it, and inside a grid
 * that has been given a transform, so a panel positioned any other way is
 * either cut off at the card's edge or fixed to the wrong thing entirely.
 */
export function WidgetMenu({
  groups,
  label,
  always,
  onOpen,
}: {
  /** Items in bands, drawn with a rule between them. Empty bands are dropped. */
  groups: MenuItem[][];
  label: string;
  /** Show the button without hovering, e.g. while the board is being arranged. */
  always?: boolean;
  /**
   * Called as the menu opens, to settle anything the items depend on.
   *
   * What a widget can be copied as is read off what it actually drew, and a
   * chart's canvas appears a moment after the data does - so a check made
   * when the data arrived found nothing, and the copy line was missing from
   * the menu for the life of the page. Asking at the moment of opening is
   * both later and cheaper than watching for it.
   */
  onOpen?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [at, setAt] = useState<{ top: number; right: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const bands = groups.filter((band) => band.length > 0);

  // Anywhere else, and the next key, closes it. Both are what a menu is
  // expected to do, and neither is worth a click on a "cancel".
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      const target = event.target as Node;
      // The menu itself counts as inside. Listening in the capture phase means
      // this runs before anything the menu could do to stop it, so testing the
      // button alone closed the menu on the way down and the item under the
      // pointer was gone before its click arrived: every entry did nothing.
      if (button.current?.contains(target) || panel.current?.contains(target))
        return;
      setOpen(false);
    };
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    // Captured, so a click on the page behind closes the menu instead of
    // reaching whatever was under the pointer.
    document.addEventListener("mousedown", away, true);
    document.addEventListener("keydown", key);
    window.addEventListener("resize", () => setOpen(false), { once: true });
    return () => {
      document.removeEventListener("mousedown", away, true);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  const show = () => {
    const box = button.current?.getBoundingClientRect();
    if (box)
      setAt({
        top: box.bottom + 4,
        right: Math.max(8, window.innerWidth - box.right),
      });
    if (!open) onOpen?.();
    setOpen((was) => !was);
  };

  if (!bands.length) return null;

  return (
    <>
      <button
        ref={button}
        className={`btn-ghost btn-sm shrink-0 px-1.5 text-ink-500 transition-opacity ${
          always || open
            ? "opacity-100"
            : "opacity-0 focus:opacity-100 group-hover:opacity-100"
        }`}
        onClick={show}
        title={`Options for ${label}`}
        aria-label={`Options for ${label}`}
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {/* Three dots, drawn rather than typed: the character for them is
            missing from enough fonts to come out as a box. */}
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          aria-hidden="true"
          fill="currentColor"
        >
          <circle cx="3" cy="8" r="1.5" />
          <circle cx="8" cy="8" r="1.5" />
          <circle cx="13" cy="8" r="1.5" />
        </svg>
      </button>
      {open &&
        at &&
        createPortal(
          <div
            ref={panel}
            className="fixed z-50 min-w-[11rem] overflow-hidden rounded-card border border-ink-200 bg-white py-1 shadow-lg"
            style={{ top: at.top, right: at.right }}
            role="menu"
          >
            {bands.map((band, index) => (
              <div
                key={index}
                className={index ? "mt-1 border-t border-ink-100 pt-1" : ""}
              >
                {band.map((item) => (
                  <button
                    key={item.label}
                    role="menuitem"
                    className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-ink-50 ${
                      item.danger ? "text-red-600" : "text-ink-700"
                    }`}
                    onClick={() => {
                      setOpen(false);
                      item.onClick();
                    }}
                  >
                    <span className="w-3 shrink-0 text-ink-400">
                      {item.checked ? "\u2713" : ""}
                    </span>
                    {item.label}
                  </button>
                ))}
              </div>
            ))}
          </div>,
          document.body,
        )}
    </>
  );
}
