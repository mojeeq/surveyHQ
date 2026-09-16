import { type CSSProperties } from "react";

import "react-grid-layout/css/styles.css";

import "react-resizable/css/styles.css";

import type { Appearance, Dashboard, Widget } from "@/lib/types";

import { isDark, titleFontStack } from "@/components/DashboardAppearance";

export const COLUMNS = 12;

/** text-sm, the size a widget title is when none is chosen. */
export const DEFAULT_TITLE_SIZE = 14;

/** What a chart's text measures before anybody changes it; see BASE_TEXT. */
export const DEFAULT_CHART_TEXT = 12;

/** The data quality panel's base size. A finding is read, not scanned past. */
export const DEFAULT_PANEL_TEXT = 15;

/** What the size slider sits at before anybody moves it. */
export const panelDefault = (kind: string) =>
  kind === "quality" ? DEFAULT_PANEL_TEXT : DEFAULT_CHART_TEXT;

export const ROW_HEIGHT = 74;

// Breathing room inside the canvas, so a widget dragged to the far right stops
// short of the edge instead of butting against it.
export const CANVAS_PADDING = 16;

export const appearanceOf = (dashboard: Dashboard | undefined): Appearance =>
  (dashboard?.appearance ?? {}) as Appearance;

/** The styling one widget carries of its own, over the dashboard's. */
export interface WidgetStyle {
  /** A sentence under the widget saying what the reader is looking at. */
  caption?: string;
  background?: string;
  /** 0-1. Falls back to the dashboard's when this widget sets none. */
  opacity?: number;
  font_family?: string;
  font_color?: string;
  /** The widget title's own size in pixels, over the card's. */
  title_size?: number;
  /** The widget title's own typeface, named by id from lib/fonts. */
  title_font?: string;
  /** Where the title sits in its bar. Left unless asked otherwise. */
  title_align?: "left" | "center" | "right";
  /** How far the card is lifted off the background: none, soft or strong. */
  shadow?: "none" | "soft" | "strong";
  /** The colour this widget's chart leads with. */
  series_color?: string;
  /**
   * Print the value on each mark of this widget's chart.
   *
   * Set here as well as on the saved chart, because whether the numbers belong
   * on the bars is a question about the tile they are read in, not about the
   * query: the same chart wants them on a quarter-width tile on a wall and off
   * on a crowded page.
   */
  show_values?: boolean;
  /** How big the text on this widget's chart is, in pixels. */
  chart_font_size?: number;
}

/**
 * The face of one widget's title.
 *
 * The colour is set here rather than left to inherit from the card: the
 * heading carries a text colour of its own, and an inherited one never gets
 * past it - which is why choosing a text colour used to change the axes and
 * leave the title alone.
 */
export function titleStyle(style: WidgetStyle): CSSProperties | undefined {
  const stack = titleFontStack(style.title_font);
  const css: CSSProperties = {
    ...(style.title_size
      ? { fontSize: `${style.title_size}px`, lineHeight: 1.25 }
      : {}),
    ...(stack ? { fontFamily: stack } : {}),
    ...(widgetInk(style) ? { color: widgetInk(style) } : {}),
  };
  return Object.keys(css).length ? css : undefined;
}

export const styleOf = (widget: Widget): WidgetStyle =>
  (widget.config ?? {}) as WidgetStyle;

/** Text light enough to read on a widget dark enough to need it. */
export const ON_DARK = "#e8ecf2";

/**
 * The colour this widget's text should be, or nothing to leave it alone.
 *
 * A colour somebody chose always wins. Where they chose none but gave the
 * widget a dark background, the answer is not "the default": the default is
 * near-black, and a black widget with near-black labels is a black rectangle.
 * Choosing a background should not oblige anybody to go and choose a text
 * colour to go with it.
 */
export function widgetInk(style: WidgetStyle): string | undefined {
  if (style.font_color) return style.font_color;
  return isDark(style.background) ? ON_DARK : undefined;
}

/**
 * The class that makes a widget's text agree with its own background.
 *
 * widgetInk() sets the card's colour, but the text inside carries its own
 * `text-ink-500` and the like, and those win - so a slate tile ends up with
 * near-black labels on it. This is what the CSS in index.css hangs off: it
 * repairs the muted greys, the hairlines and the pale surfaces underneath.
 *
 * Only from a background somebody actually chose. A widget that took the
 * dashboard's own paper is left alone, because that is the case the app's own
 * light and dark modes already handle.
 */
export function widgetTone(style: WidgetStyle): string {
  if (!style.background) return "";
  return isDark(style.background) ? "on-dark" : "on-light";
}

/** The card colour for one widget, at its own transparency or the dashboard's.
 *
 *  A widget colour and the see-through setting are two different wishes, and
 *  doing one should not cancel the other - so the colour is the one chosen and
 *  the alpha is whichever applies. Transparency used to be the dashboard's
 *  alone, which made one widget impossible to lift off a busy background
 *  without lifting all of them.
 */
/**
 * How far a widget is lifted off the dashboard behind it.
 *
 * Written out rather than left to Tailwind's shadow classes because these have
 * to go into an inline style beside the card's own colour, and because a
 * dashboard on a coloured or photographic background needs a shadow with more
 * weight in it than a shadow designed for white paper.
 */
export const SHADOWS: Record<string, string> = {
  none: "none",
  soft: "0 1px 2px rgba(15,23,42,.06), 0 4px 12px rgba(15,23,42,.08)",
  strong: "0 2px 4px rgba(15,23,42,.10), 0 12px 28px rgba(15,23,42,.18)",
};

export function cardStyle(
  widget: Widget,
  dashboardOpacity: number,
): CSSProperties | undefined {
  const style = styleOf(widget);
  const own = style.opacity;
  const opacity = own === undefined || own === null ? dashboardOpacity : own;
  const text: CSSProperties = {
    ...(style.font_family ? { fontFamily: style.font_family } : {}),
    ...(widgetInk(style) ? { color: widgetInk(style) } : {}),
    ...(style.shadow && SHADOWS[style.shadow]
      ? { boxShadow: SHADOWS[style.shadow] }
      : {}),
  };
  const chosen = style.background;
  if (!chosen) {
    return opacity < 1
      ? { backgroundColor: `rgba(255,255,255,${opacity})`, ...text }
      : Object.keys(text).length
        ? text
        : undefined;
  }
  const hex = chosen.replace("#", "");
  if (hex.length !== 6) return { backgroundColor: chosen, ...text };
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return { backgroundColor: `rgba(${r},${g},${b},${opacity})`, ...text };
}
