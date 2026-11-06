/**
 * Is this colour dark enough to need light text on it?
 *
 * Lived in DashboardAppearance, which the shell cannot import without pulling
 * the whole dashboard editor into the first chunk anybody loads. The sidebar
 * asks the same question of its own colour, so the answer moved here and that
 * module re-exports it for the callers it already had.
 */
export function isDark(color?: string): boolean {
  const hex = (color ?? '').replace('#', '')
  if (hex.length !== 6) return false
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16))
  // Rec. 709 luma: the eye takes green as much brighter than blue at the same
  // number, so averaging the channels would call #0000ff light.
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 < 0.5
}
