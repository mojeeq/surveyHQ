/**
 * Ready-made grounds for the board itself.
 *
 * A background used to mean uploading a picture. Most boards do not want a
 * photograph behind their numbers - they want the surface to stop being flat
 * white without becoming something a reader has to look past - and finding a
 * picture that manages that is a job nobody asked for. These are that surface,
 * chosen rather than found.
 *
 * Every one is CSS: gradients and repeating gradients, no files. That matters
 * beyond the download size. The exported HTML carries its appearance as a
 * stylesheet, so a ground written this way travels in a file that can be
 * emailed, prints without a trip to a server for an image, and stays sharp at
 * any zoom on any screen. A picture is none of those things.
 *
 * `tint` is the flat colour under the pattern: what shows where the pattern
 * does not reach, and what the platform reads to decide whether the text over
 * it should be light or dark. Choosing a ground sets both it and the pattern.
 *
 * The same table lives in `backend/app/services/export_backgrounds.py`, which
 * dresses the exported file. A test fails if the two drift apart.
 */
export interface Ground {
  id: string
  label: string
  note: string
  /** The flat colour under the pattern, stored as `background_color`. */
  tint: string
  /** The CSS `background-image` value laid over that colour. */
  layers: string
  /** `background-size`, where the pattern needs a cell to repeat in. */
  size?: string
  /**
   * Whether the pattern is drawn in nothing but translucent ink, so the
   * colour under it still shows. A texture is; a ground whose whole point is
   * its own colour is not, and a board choosing one of those takes its tint.
   */
  tintable?: true
}

export const BACKGROUNDS: Ground[] = [
  {
    id: 'mist',
    label: 'Mist',
    note: 'A pale wash, barely there. The safest ground under a busy board.',
    tint: '#f4f6f9',
    layers: 'linear-gradient(180deg, rgba(255,255,255,0.55) 0%, rgba(0,0,0,0.03) 100%)',
    tintable: true,
  },
  {
    id: 'paper-grain',
    label: 'Paper',
    note: 'Off-white with a faint weave, for a board that will be printed.',
    tint: '#f7f5f0',
    layers:
      'repeating-linear-gradient(45deg, rgba(120,110,90,0.04) 0 2px, rgba(0,0,0,0) 2px 6px), ' +
      'repeating-linear-gradient(-45deg, rgba(120,110,90,0.03) 0 2px, rgba(0,0,0,0) 2px 6px), ' +
      'linear-gradient(180deg, rgba(255,255,255,0.45) 0%, rgba(90,70,40,0.05) 100%)',
    tintable: true,
  },
  {
    id: 'graph',
    label: 'Graph paper',
    note: 'Fine squared lines, which reads as working paper rather than decoration.',
    tint: '#fbfcfd',
    layers:
      'linear-gradient(rgba(70,100,140,0.10) 1px, rgba(0,0,0,0) 1px), ' +
      'linear-gradient(90deg, rgba(70,100,140,0.10) 1px, rgba(0,0,0,0) 1px), ' +
      'linear-gradient(180deg, rgba(255,255,255,0.5) 0%, rgba(0,0,0,0.02) 100%)',
    size: '24px 24px, 24px 24px, auto',
    tintable: true,
  },
  {
    id: 'dots',
    label: 'Dots',
    note: 'A light dot grid. Enough texture to lift the cards off the ground.',
    tint: '#f6f7f9',
    layers:
      'radial-gradient(rgba(60,80,110,0.16) 1px, rgba(0,0,0,0) 1.5px), ' +
      'linear-gradient(180deg, rgba(255,255,255,0.5) 0%, rgba(0,0,0,0.03) 100%)',
    size: '16px 16px, auto',
    tintable: true,
  },
  {
    id: 'sand',
    label: 'Sand',
    note: 'Warm and light, for a board that goes into a printed report.',
    tint: '#f6efe3',
    layers: 'linear-gradient(160deg, #fbf6ec 0%, #efe3cf 100%)',
  },
  {
    id: 'dawn',
    label: 'Dawn',
    note: 'A warm light sweep, pale enough to read a chart against.',
    tint: '#fdf1e7',
    layers: 'linear-gradient(160deg, #fff6ee 0%, #fbe3d2 55%, #f3dcd6 100%)',
  },
  {
    id: 'arctic',
    label: 'Arctic',
    note: 'Cold and very light, which suits a board with a lot of blue in it.',
    tint: '#eef4fb',
    layers: 'linear-gradient(160deg, #f8fbff 0%, #e4eef9 100%)',
  },
  {
    id: 'blueprint',
    label: 'Blueprint',
    note: 'White squares on deep blue. A dark ground that still reads as paper.',
    tint: '#0f2b4a',
    layers:
      'linear-gradient(rgba(255,255,255,0.08) 1px, rgba(0,0,0,0) 1px), ' +
      'linear-gradient(90deg, rgba(255,255,255,0.08) 1px, rgba(0,0,0,0) 1px), ' +
      'linear-gradient(160deg, #123355 0%, #0b2138 100%)',
    size: '26px 26px, 26px 26px, auto',
  },
  {
    id: 'sea',
    label: 'Sea',
    note: 'Deep teal, for a wall screen in a room with the lights on.',
    tint: '#0b2f36',
    layers: 'linear-gradient(160deg, #11404a 0%, #082227 100%)',
  },
  {
    id: 'moss',
    label: 'Moss',
    note: 'Dark green, which charts in warm colours sit well on.',
    tint: '#0f241b',
    layers: 'linear-gradient(160deg, #163528 0%, #0a1a13 100%)',
  },
  {
    id: 'carbon',
    label: 'Carbon',
    note: 'Near black with a fine weave, for a screen left on overnight.',
    tint: '#111418',
    layers:
      'repeating-linear-gradient(45deg, rgba(255,255,255,0.025) 0 2px, rgba(0,0,0,0) 2px 7px), ' +
      'linear-gradient(160deg, rgba(255,255,255,0.05) 0%, rgba(0,0,0,0.28) 100%)',
    tintable: true,
  },
  {
    id: 'plum',
    label: 'Plum',
    note: 'Dark purple: warmer than black, and nobody argues about it.',
    tint: '#241427',
    layers: 'linear-gradient(160deg, #33203a 0%, #190e1c 100%)',
  },
]

/** One ground by id, where it is still a ground this version offers. */
export function ground(id?: string): Ground | undefined {
  return id ? BACKGROUNDS.find((one) => one.id === id) : undefined
}
