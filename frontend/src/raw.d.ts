/**
 * A file imported for its text rather than for what it does.
 *
 * Vite serves `?raw` as a string, and a couple of tests read a source file
 * that way to pin something the file's own output cannot show - an order
 * between two components in a view too heavy to render under a test runner.
 * Declared here rather than by pulling in vite/client, which would bring the
 * whole ambient surface along with it.
 */
declare module '*?raw' {
  const text: string
  export default text
}
