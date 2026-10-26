/**
 * Colouring a script, and what the editor offers as it is typed.
 *
 * The vocabulary here is a small hand-made one in the shape the server sends;
 * the server's own test holds the real one to the engine. What is tested is
 * the reading: which word is a command, which a dataset, which an option, and
 * what belongs at the caret.
 */
import { StringStream } from '@codemirror/language'
import { describe, expect, it } from 'vitest'

import {
  acceptChange,
  completeAt,
  describeAt,
  indexLanguage,
  scriptParser,
  variablesAt,
} from '@/lib/script-language'
import type { ScriptNames, Vocabulary } from '@/lib/script-language'

const vocabulary: Vocabulary = {
  commands: [
    { name: 'use', aliases: [], syntax: 'use <dataset>', summary: 'Load a dataset.', options: [] },
    {
      name: 'save', aliases: [], syntax: 'save as "<name>"', summary: 'Write it out.',
      options: [{ name: 'replace', summary: 'Write over.', takes_argument: false }],
    },
    {
      name: 'merge', aliases: [], syntax: 'merge 1:1 <keys> using <dataset>', summary: 'Add variables.',
      options: [
        { name: 'keep', summary: 'Which rows survive.', takes_argument: true },
        { name: 'nogen', summary: 'No _merge.', takes_argument: false },
      ],
    },
    {
      name: 'collapse', aliases: [], syntax: 'collapse (stat) <variables>', summary: 'One row per group.',
      options: [{ name: 'by', summary: 'Group by.', takes_argument: true }],
    },
    { name: 'gen', aliases: ['g', 'generate'], syntax: 'gen <name> = <expression>', summary: 'Make a variable.', options: [] },
    { name: 'replace', aliases: [], syntax: 'replace <name> = <expression>', summary: 'Change values.', options: [] },
    {
      name: 'egen', aliases: [], syntax: 'egen <name> = fn()', summary: 'Whole columns.',
      options: [{ name: 'by', summary: 'Within groups.', takes_argument: true }],
    },
    { name: 'label', aliases: ['la'], syntax: 'label variable <name> "<text>"', summary: 'Name things.', options: [] },
    { name: 'rename', aliases: ['ren'], syntax: 'rename <old> <new>', summary: 'Rename.', options: [] },
    { name: 'drop', aliases: [], syntax: 'drop <variables>', summary: 'Remove.', options: [] },
    { name: 'local', aliases: [], syntax: 'local <name> <text>', summary: 'Name text.', options: [] },
    { name: 'by', aliases: [], syntax: 'by <variables>: <command>', summary: 'In groups.', options: [] },
    { name: 'bysort', aliases: ['bys'], syntax: 'bysort <variables>: <command>', summary: 'Sort, then in groups.', options: [] },
    { name: 'keep', aliases: [], syntax: 'keep <variables>', summary: 'Keep.', options: [] },
    { name: 'duplicates', aliases: [], syntax: 'duplicates drop', summary: 'Repeats.', options: [] },
    { name: 'reshape', aliases: [], syntax: 'reshape long', summary: 'Long or wide.', options: [] },
    { name: 'foreach', aliases: [], syntax: 'foreach v in a b {', summary: 'Loop.', options: [] },
    { name: 'forvalues', aliases: [], syntax: 'forvalues i = 1/5 {', summary: 'Count.', options: [] },
    { name: 'assert', aliases: [], syntax: 'assert <expression>', summary: 'Check.', options: [] },
    { name: 'recode', aliases: [], syntax: 'recode <variables> (rule)', summary: 'By rules.', options: [] },
    { name: 'encode', aliases: [], syntax: 'encode <variable>, generate()', summary: 'Number text.', options: [] },
  ],
  functions: [
    { name: 'round', syntax: 'round(x)', summary: 'Round it.' },
    { name: 'inlist', syntax: 'inlist(x, a, b)', summary: 'One of these.' },
  ],
  egen: [{ name: 'total', summary: 'The total.', rowwise: false }],
  collapse: [{ name: 'sum', summary: 'The total.' }, { name: 'mean', summary: 'The mean.' }],
  label_kinds: [
    { name: 'variable', summary: 'Label a variable.' },
    { name: 'define', summary: 'Make a set.' },
    { name: 'values', summary: 'Apply a set.' },
  ],
  merge_shapes: ['1:1', 'm:1', '1:m'],
  merge_keep: [{ name: 'master', summary: '' }, { name: 'using', summary: '' }, { name: 'match', summary: '' }],
  subcommands: {
    duplicates: [{ name: 'report', summary: '' }, { name: 'tag', summary: '' }, { name: 'drop', summary: '' }],
    reshape: [{ name: 'long', summary: '' }, { name: 'wide', summary: '' }],
  },
  loop_words: ['in', 'of', 'varlist', 'newlist', 'local', 'global', 'numlist'].map((name) => ({ name, summary: '' })),
  row_names: [{ name: '_n', summary: 'This row.' }, { name: '_N', summary: 'How many.' }],
  by_able: ['assert', 'drop', 'egen', 'gen', 'keep', 'replace'],
}

const names: ScriptNames = {
  datasets: [
    {
      name: 'people', slug: 'people', rows: 1200,
      variables: [
        { name: 'hhid', label: 'Household', type: 'numeric' },
        { name: 'age', label: 'Age in years', type: 'numeric' },
      ],
    },
    {
      name: 'Household roster', slug: 'household-roster', rows: 300,
      variables: [
        { name: 'hhid', label: 'Household', type: 'numeric' },
        { name: 'province', label: 'Province', type: 'categorical' },
      ],
    },
  ],
}

const index = indexLanguage(vocabulary, names)

/** Each line's tokens, as [text, token] pairs, the way the editor reads them. */
function tokens(text: string): [string, string | null][][] {
  const parser = scriptParser(index)
  const state = parser.startState!(2)
  return text.split('\n').map((line) => {
    const out: [string, string | null][] = []
    const stream = new StringStream(line, 4, 2)
    while (!stream.eol()) {
      const style = parser.token(stream, state)
      const piece = line.slice(stream.start, stream.pos)
      if (piece.trim()) out.push([piece, style])
      stream.start = stream.pos
    }
    return out
  })
}

/** What is offered with the caret at the `|`. */
function offered(text: string): string[] {
  const pos = text.indexOf('|')
  const doc = text.replace('|', '')
  return completeAt(doc, pos, index)?.options.map((one) => one.label) ?? []
}

describe('colouring', () => {
  it('reads a command, a dataset, a function and its operands', () => {
    const [use, gen] = tokens('use people\ngen older = round(age) >= 18 if hhid != .')
    expect(use).toEqual([['use', 'keyword'], ['people', 'typeName']])
    expect(gen).toEqual([
      ['gen', 'keyword'], ['older', 'variableName'], ['=', 'operator'],
      ['round', 'variableName.function'], ['(', 'punctuation'], ['age', 'variableName'],
      [')', 'punctuation'], ['>=', 'operator'], ['18', 'number'], ['if', 'keyword'],
      ['hhid', 'variableName'], ['!=', 'operator'], ['.', 'atom'],
    ])
  })

  it('marks a word that is not a command as the mistake it is', () => {
    expect(tokens('generat x = 1')[0][0]).toEqual(['generat', 'invalid'])
  })

  it('takes every spelling of a command', () => {
    expect(tokens('g x = 1')[0][0]).toEqual(['g', 'keyword'])
  })

  it('reads comments as the engine does', () => {
    const [star, trailing, inQuotes] = tokens(
      '* the whole line\nuse people // and the rest\ngen site = "https://example.org"',
    )
    expect(star).toEqual([['* the whole line', 'comment']])
    expect(trailing.at(-1)).toEqual(['// and the rest', 'comment'])
    expect(inQuotes.at(-1)).toEqual(['"https://example.org"', 'string'])
  })

  it('carries a command across ///, so the next line is not a command', () => {
    const [, second] = tokens('gen total = age + ///\n    hhid')
    expect(second).toEqual([['hhid', 'variableName']])
  })

  it('reads options after the comma, and what merge and collapse take', () => {
    const [merge, collapse] = tokens(
      'merge m:1 hhid using "Household roster", keep(match) nogen\ncollapse (sum) age, by(province)',
    )
    expect(merge).toContainEqual(['m:1', 'atom'])
    expect(merge).toContainEqual(['using', 'keyword'])
    expect(merge).toContainEqual(['"Household roster"', 'typeName'])
    expect(merge).toContainEqual(['keep', 'propertyName'])
    expect(merge).toContainEqual(['match', 'atom'])
    expect(merge).toContainEqual(['nogen', 'propertyName'])
    expect(collapse).toContainEqual(['sum', 'atom'])
    expect(collapse).toContainEqual(['by', 'propertyName'])
  })

  it('reads what follows a by prefix as a command of its own', () => {
    const [line] = tokens('bysort hhid (age): gen first = _n == 1 & age[_n-1] != .')
    expect(line.slice(0, 3)).toEqual([['bysort', 'keyword'], ['hhid', 'variableName'], ['(', 'punctuation']])
    expect(line).toContainEqual(['gen', 'keyword'])
    expect(line).toContainEqual(['_n', 'atom'])
  })

  it('reads a loop\'s first line, and the form after duplicates and reshape', () => {
    const [loop, duplicates, reshape] = tokens(
      'foreach v of varlist age hhid {\nduplicates drop hhid\nreshape long inc, i(hhid) j(year)',
    )
    expect(loop.slice(0, 4)).toEqual([
      ['foreach', 'keyword'], ['v', 'macroName'], ['of', 'keyword'], ['varlist', 'keyword'],
    ])
    expect(duplicates[1]).toEqual(['drop', 'keyword'])
    expect(reshape[1]).toEqual(['long', 'keyword'])
  })

  it('reads macros', () => {
    expect(tokens('drop if `adult\' & $wave')[0]).toEqual([
      ['drop', 'keyword'], ['if', 'keyword'], ["`adult'", 'macroName'], ['&', 'operator'], ['$wave', 'macroName'],
    ])
  })
})

describe('what is offered', () => {
  it('offers commands at the start of a line, and their other spellings', () => {
    expect(offered('ge|')).toEqual(expect.arrayContaining(['gen', 'generate']))
    expect(offered('use people\n|')).toContain('merge')
  })

  it('offers the project\'s datasets after use and using, quoting a name with a space', () => {
    expect(offered('use |')).toEqual(['people', 'Household roster'])
    const after = completeAt('use ', 4, index)
    expect(after?.options.find((one) => one.label === 'Household roster')?.insert).toBe('"Household roster"')
    expect(offered('use people\nmerge 1:1 hhid using |')).toContain('people')
  })

  it('finishes a quoted dataset name with its closing quote', () => {
    const doc = 'use "Hou'
    const answer = completeAt(doc, doc.length, index)
    expect(answer?.from).toBe(5)
    expect(answer?.options.find((one) => one.label === 'Household roster')?.insert).toBe('Household roster"')
  })

  it('uses the closing quote the editor already typed rather than adding another', () => {
    // `use "Hou|"`: the editor closed the quote when it was opened.
    const doc = 'use "Hou"'
    const answer = completeAt(doc, 8, index)
    const roster = answer!.options.find((one) => one.label === 'Household roster')!
    const change = acceptChange(doc, answer!.from, 8, roster)
    const after = doc.slice(0, change.from) + change.insert + doc.slice(change.to)
    expect(after).toBe('use "Household roster"')
    expect(change.caret).toBe(after.length)
    // With no closing quote there, it is added.
    const open = acceptChange('use "Hou', 5, 8, roster)
    expect('use "'.slice(0, open.from) + open.insert).toBe('use "Household roster"')
  })

  it('offers the variables in memory, from the dataset loaded above', () => {
    expect(offered('use people\ndrop |')).toEqual(['if', 'hhid', 'age'])
    expect(offered('use "Household roster"\nreplace |')).toEqual(['hhid', 'province'])
  })

  it('follows what the script does to the variables', () => {
    const doc = 'use people\ngen adult = age >= 18\nrename age years\nmerge m:1 hhid using "Household roster"\ndrop |'
    expect(offered(doc)).toEqual(expect.arrayContaining(['adult', 'years', 'province', '_merge']))
    expect(offered(doc)).not.toContain('age')
  })

  it('offers what a collapse left', () => {
    expect(offered('use people\ncollapse (mean) age, by(hhid)\ndrop |')).toEqual(['if', 'hhid', 'age'])
  })

  it('offers functions where an expression is being written', () => {
    expect(offered('use people\ngen x = |')).toEqual(expect.arrayContaining(['age', 'round', 'inlist']))
    expect(offered('use people\ndrop |')).not.toContain('round')
  })

  it('offers nothing for a name being made', () => {
    expect(offered('use people\ngen |')).toEqual([])
    expect(offered('use people\negen |')).toEqual([])
  })

  it('offers a command\'s options after the comma, with brackets where they take some', () => {
    expect(offered('use people\nmerge 1:1 hhid using people, |')).toEqual(['keep', 'nogen'])
    const answer = completeAt('use people\ncollapse (sum) age, ', 31, index)
    expect(answer?.options[0]).toMatchObject({ label: 'by', insert: 'by()', caretBack: 1 })
  })

  it('offers what fits inside the brackets', () => {
    expect(offered('use people\nmerge 1:1 hhid using people, keep(|')).toEqual(['master', 'using', 'match'])
    expect(offered('use people\ncollapse (|')).toEqual(['sum', 'mean'])
    expect(offered('use people\ncollapse (sum) age, by(|')).toEqual(['hhid', 'age'])
    expect(offered('use people\negen n = |')).toEqual(['total'])
  })

  it('offers the merged-in dataset\'s variables inside keepusing()', () => {
    // merge checks keepusing() against the other dataset, not the one in memory.
    expect(offered('use people\nmerge m:1 hhid using "Household roster", keepusing(|')).toEqual([
      'hhid', 'province',
    ])
    expect(offered('use people\nmerge m:1 hhid using nowhere, keepusing(|')).toEqual([])
  })

  it('offers merge\'s shapes and label\'s kinds', () => {
    expect(offered('use people\nmerge |')).toEqual(['1:1', 'm:1', '1:m'])
    expect(offered('use people\nlabel |')).toEqual(['variable', 'define', 'values'])
  })

  it('offers the commands a by prefix can run, and what fits after it', () => {
    const after = offered('use people\nbysort hhid: |')
    expect(after).toContain('gen')
    expect(after).not.toContain('merge')
    expect(offered('use people\nby hhid: gen n = |')).toEqual(expect.arrayContaining(['_n', '_N', 'age']))
  })

  it('offers the forms of duplicates and reshape, and a loop\'s words', () => {
    expect(offered('use people\nduplicates |')).toEqual(['report', 'tag', 'drop'])
    expect(offered('use people\nreshape |')).toEqual(['long', 'wide'])
    expect(offered('use people\nforeach v |')).toEqual(['in', 'of'])
    expect(offered('use people\nforeach v of |')).toEqual(['varlist', 'newlist', 'local', 'global', 'numlist'])
    expect(offered('use people\nforeach v of varlist |')).toContain('age')
    expect(offered('use people\nforeach v in |')).toEqual([])
  })

  it('offers a loop\'s name as a local inside it', () => {
    expect(offered('foreach v in a b {\n  gen `|')).toContain('v')
  })

  it('follows what by-prefixed and new commands make', () => {
    const known = (text: string) => variablesAt(text, text.length, index)?.map((one) => one.name) ?? []
    expect(known('use people\nbysort hhid: gen n = _n\n')).toContain('n')
    expect(known('use people\nrecode age (0/17 = 0), gen(adult)\n')).toContain('adult')
    expect(known('use "Household roster"\nencode province, gen(pcode)\n')).toContain('pcode')
  })

  it('offers macros defined above', () => {
    expect(offered('local adult age >= 18\nuse people\ndrop if `|')).toEqual(['adult'])
  })

  it('offers nothing in a comment or a plain string', () => {
    expect(offered('* use |')).toEqual([])
    expect(offered('use people // drop |')).toEqual([])
    expect(offered('use people\nlabel variable age "Age |')).toEqual([])
  })

  it('offers every variable in the project before anything is loaded', () => {
    expect(variablesAt('drop ', 5, index)).toBeNull()
    expect(offered('drop |')).toEqual(['if', 'hhid', 'age', 'province'])
  })
})

describe('what a word is', () => {
  const at = (text: string) => {
    const pos = text.indexOf('|')
    return describeAt(text.replace('|', ''), pos, index)
  }

  it('describes commands, functions, options, datasets and variables', () => {
    expect(at('me|rge 1:1 hhid using people')?.title).toBe('merge 1:1 <keys> using <dataset>')
    expect(at('gen x = ro|und(age)')?.body).toBe('Round it.')
    expect(at('merge 1:1 hhid using people, no|gen')?.body).toBe('No _merge.')
    expect(at('use peo|ple')?.body).toContain('1,200 rows')
    expect(at('drop a|ge')?.body).toContain('Age in years')
  })

  it('describes _n, a by-prefixed command and a form of reshape', () => {
    const doc = 'use people\nbysort hhid: gen n = _n\nreshape long inc, i(hhid) j(year)'
    expect(describeAt(doc, doc.indexOf('_n') + 1, index)?.title).toBe('_n')
    expect(describeAt(doc, doc.indexOf('gen') + 1, index)?.title).toBe('gen <name> = <expression>')
    expect(describeAt(doc, doc.indexOf('long') + 1, index)?.title).toBe('reshape long')
  })

  it('says nothing about a comment', () => {
    expect(at('* me|rge')).toBeNull()
  })
})
