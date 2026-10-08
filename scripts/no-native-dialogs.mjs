/**
 * Fails if the frontend calls the browser's own dialogs.
 *
 * window.alert, window.confirm and window.prompt cannot be styled, announce
 * the server's address above the question, and block the thread. The platform
 * has its own in @/hooks/useDialog, which look like the rest of it and can do
 * things these cannot - a red button on a destructive confirm, a prompt that
 * rejects a duplicate name without discarding what was typed.
 *
 * Run from `prelint`, so CI catches a new one.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const SRC = fileURLToPath(new URL('../frontend/src', import.meta.url))

/** The hook itself has none; the escaping tests carry alert() inside strings. */
const EXEMPT = [/hooks\/useDialog\.tsx$/, /__tests__\//]

// A bare call or an explicit window. one. `ask.confirm(` has a dot and a word
// character before it, so it does not match.
const NATIVE = /(?<![.\w])(?:window\s*\.\s*)?(alert|confirm|prompt)\s*\(/g

const files = []
const walk = (dir) => {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) walk(path)
    else if (/\.(ts|tsx)$/.test(path)) files.push(path)
  }
}
walk(SRC)

const found = []
for (const path of files) {
  if (EXEMPT.some((rule) => rule.test(path))) continue
  const lines = readFileSync(path, 'utf8').split('\n')
  lines.forEach((line, i) => {
    for (const match of line.matchAll(NATIVE)) {
      found.push(`${path.slice(SRC.length + 1)}:${i + 1}  ${match[0]}  ${line.trim()}`)
    }
  })
}

if (found.length) {
  console.error('\nNative browser dialogs found. Use useDialog() instead:\n')
  for (const hit of found) console.error('  ' + hit)
  console.error('\n  const ask = useDialog()')
  console.error('  if (await ask.confirm({ title: ..., tone: "danger" })) remove()\n')
  process.exit(1)
}
console.log(`no native dialogs in ${files.length} files`)
