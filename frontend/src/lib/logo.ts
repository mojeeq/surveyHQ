/**
 * Clearing the plain background a logo was saved on.
 *
 * A coat of arms or an organisation's mark often arrives as a PNG with a solid
 * black or white square behind it - exported from a document, or saved by a
 * tool that dropped the transparency - and on a coloured masthead that square
 * is the first thing anybody sees. Uploading it as it is was the only choice.
 *
 * This clears the colour the picture's corners share, starting from its edges
 * and spreading inward only through that colour, so the parts of the emblem
 * that happen to be the same colour - a black outline, the dark of a shield -
 * are kept: they are not reachable from the edge without crossing the emblem.
 */

/** The pixels of a picture, as a canvas hands them over. */
export interface Pixels {
  data: Uint8ClampedArray
  width: number
  height: number
}

/**
 * Make the plain colour round a picture's edges transparent, in place.
 *
 * Returns how many pixels it cleared: nothing when the corners do not share a
 * colour, which is a picture with no plain background to clear, or when they
 * are already transparent. A pixel close to the colour is cleared outright;
 * one nearer the limit keeps some of its opacity, which is what keeps the
 * emblem's anti-aliased edge soft rather than cut out with scissors.
 */
export function clearBackground(image: Pixels, tolerance = 48): number {
  const { data, width, height } = image
  if (!width || !height) return 0
  const at = (x: number, y: number) => (y * width + x) * 4
  const corners = [at(0, 0), at(width - 1, 0), at(0, height - 1), at(width - 1, height - 1)]
  const [r, g, b, a] = [data[corners[0]], data[corners[0] + 1], data[corners[0] + 2], data[corners[0] + 3]]
  if (a < 16) return 0
  const distance = (index: number) =>
    Math.sqrt((data[index] - r) ** 2 + (data[index + 1] - g) ** 2 + (data[index + 2] - b) ** 2)
  if (corners.some((index) => distance(index) > tolerance || data[index + 3] < 16)) return 0

  const seen = new Uint8Array(width * height)
  const stack: number[] = []
  const visit = (x: number, y: number) => {
    const pixel = y * width + x
    if (seen[pixel]) return
    seen[pixel] = 1
    stack.push(pixel)
  }
  for (let x = 0; x < width; x++) {
    visit(x, 0)
    visit(x, height - 1)
  }
  for (let y = 0; y < height; y++) {
    visit(0, y)
    visit(width - 1, y)
  }

  const solid = tolerance * 0.5
  let cleared = 0
  while (stack.length) {
    const pixel = stack.pop() as number
    const index = pixel * 4
    const away = distance(index)
    if (away > tolerance) continue
    data[index + 3] =
      away <= solid ? 0 : Math.round((data[index + 3] * (away - solid)) / (tolerance - solid))
    cleared++
    const x = pixel % width
    const y = (pixel - x) / width
    if (x > 0) visit(x - 1, y)
    if (x < width - 1) visit(x + 1, y)
    if (y > 0) visit(x, y - 1)
    if (y < height - 1) visit(x, y + 1)
  }
  return cleared
}

/** No side of a logo needs more than this: it is drawn at most 200px tall. */
const LARGEST = 1200

/**
 * The file with its plain background made transparent, as a PNG, and how much
 * was cleared. The file comes back as it was when there was nothing to clear.
 */
export async function withoutBackground(file: File): Promise<{ file: File; cleared: number }> {
  const bitmap = await createImageBitmap(file)
  const scale = Math.min(1, LARGEST / Math.max(bitmap.width, bitmap.height))
  const width = Math.max(1, Math.round(bitmap.width * scale))
  const height = Math.max(1, Math.round(bitmap.height * scale))
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  if (!context) return { file, cleared: 0 }
  context.drawImage(bitmap, 0, 0, width, height)
  bitmap.close()
  const image = context.getImageData(0, 0, width, height)
  const cleared = clearBackground(image)
  if (!cleared) return { file, cleared: 0 }
  context.putImageData(image, 0, 0)
  const blob = await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob(
      (made) => (made ? resolve(made) : reject(new Error('The logo could not be redrawn'))),
      'image/png',
    ),
  )
  const name = `${file.name.replace(/\.[^.]+$/, '') || 'logo'}.png`
  return { file: new File([blob], name, { type: 'image/png' }), cleared }
}
