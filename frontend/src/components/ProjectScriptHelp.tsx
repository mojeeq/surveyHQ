/*
 * What the command language can be asked to do, beside the box you ask it in.
 *
 * The reference lives in the user guide and always did, but a reference you
 * have to leave the page to read is one nobody reads: the whole point of the
 * box is that you are mid-thought. Every line here is clickable and lands in
 * the script, so the pane teaches by doing rather than by being read.
 *
 * It is generated from nothing - the lists are written out by hand against the
 * engine's own tables (COLLAPSE_STATS, EGEN_AGGREGATES, EGEN_ROWWISE,
 * FUNCTIONS and SPECIAL in app/services/stata*.py). A generated pane would be
 * honest about the verbs and say nothing useful about when to reach for them.
 */

import { useState } from 'react'

type Example = {
  /** The line, exactly as it would be typed. */
  line: string
  /** Why somebody reaches for it, in one clause. */
  note: string
}

type Section = {
  title: string
  blurb?: string
  examples: Example[]
}

const SECTIONS: Section[] = [
  {
    title: 'Reading and writing',
    blurb:
      'Nothing on disk changes until a save, so a script that stops halfway leaves the project as it was.',
    examples: [
      { line: 'use people', note: 'Load a copy of one of the project’s datasets' },
      { line: 'save as "Adults by province"', note: 'Write what is in memory out as a new dataset' },
      { line: 'save, replace', note: 'Write back over the dataset this was loaded from' },
    ],
  },
  {
    title: 'New variables',
    blurb:
      'A comparison is a number, as in Stata: age >= 18 gives 1 and 0, so summing it counts people. A missing age stays missing rather than becoming zero.',
    examples: [
      { line: 'gen adult = age >= 18', note: 'A new variable from an expression' },
      { line: 'replace adult = 0 if age == .', note: 'Change one, on the rows that match' },
      { line: 'gen band = cond(age < 15, 1, cond(age < 65, 2, 3))', note: 'Nested conditions' },
      { line: 'egen hh_size = count(person_id), by(hhid)', note: 'An aggregate written back onto every row of the group' },
      { line: 'egen assets = rowtotal(tv fridge car)', note: 'Across the variables of one row' },
      { line: 'destring age income, replace', note: 'Text that holds numbers, made into numbers' },
      { line: 'destring income, replace ignore(",$") force', note: 'Strip characters first; anything still not a number becomes missing' },
    ],
  },
  {
    title: 'Cleaning',
    blurb:
      'recode takes the first rule a value fits, as in Stata, and leaves a value no rule fits as it was. An assert that fails stops the script on its line, before anything wrong is saved.',
    examples: [
      { line: 'recode q5 (1 2 = 1 "Agree") (3 = 0 "Neutral") (4 5 = -1 "Disagree"), gen(view)', note: 'Old values into new by rules, labelled as it goes' },
      { line: 'recode age (min/14 = 1) (15/64 = 2) (65/max = 3), gen(age_band)', note: 'Ranges into bands' },
      { line: 'recode income (-99 -98 = .)', note: 'Don’t-know codes made missing, in place' },
      { line: 'duplicates report interview__key', note: 'How many rows repeat a key' },
      { line: 'duplicates tag hhid line, gen(dup)', note: 'Mark the repeats rather than dropping them' },
      { line: 'duplicates drop interview__key, force', note: 'Keep the first of each; force says the rest may go' },
      { line: 'assert age >= 0 & age <= 120', note: 'Stop here unless this holds on every row' },
      { line: 'encode province, gen(province_code)', note: 'Text as numbered codes, labelled with the text' },
      { line: 'decode q1, gen(q1_text)', note: 'A labelled code as its label’s text' },
      { line: 'tostring hhid, replace', note: 'Numbers as text: 3, not 3.0' },
      { line: 'sort hhid line', note: 'The rows in order' },
      { line: 'gsort province -income', note: 'Largest first, with a minus' },
      { line: 'order hhid line, first', note: 'Columns to the front' },
    ],
  },
  {
    title: 'Within groups',
    blurb:
      'A by prefix runs gen, replace, egen, keep, drop or assert inside each group: _n counts the rows from one in every group and _N is how many it has. bysort sorts by the groups first, and the bracketed part orders the rows inside them.',
    examples: [
      { line: 'bysort hhid: gen members = _N', note: 'How many rows each household has' },
      { line: 'bysort hhid (age): gen eldest = _n == _N', note: '1 on the oldest member, by the bracketed order' },
      { line: 'bysort hhid (line): keep if _n == 1', note: 'One row per household: its first' },
      { line: 'by hhid: gen previous = visit[_n-1]', note: 'The row before’s value, in the same group' },
    ],
  },
  {
    title: 'Loops',
    blurb:
      'The lines between the { and the } run once for each item, with the loop’s name standing for it. A loop’s list is read when the loop is reached, so a varlist sees what the lines above it made.',
    examples: [
      { line: 'foreach v of varlist q1-q5 {\n    replace `v\' = . if `v\' == -99\n}', note: 'Once for each variable, as `v\'' },
      { line: 'forvalues i = 1/4 {\n    gen visit`i\' = visit == `i\'\n}', note: 'Once for each number' },
      { line: 'foreach x in water power road {\n    label variable has_`x\' "Has `x\'"\n}', note: 'Once for each word' },
    ],
  },
  {
    title: 'Looking at the data',
    blurb: 'These change nothing. Their answer is in the output beside the script.',
    examples: [
      { line: 'count if age >= 18', note: 'How many rows meet a condition' },
      { line: 'summarize age income', note: 'Count, mean, spread, smallest and largest' },
      { line: 'tabulate province', note: 'How often each value appears' },
      { line: 'tab province sex', note: 'A cross-table of two' },
    ],
  },
  {
    title: 'Naming a condition',
    blurb:
      'A long recode says the same thing over and over, and changing it means finding every copy - which is how a cascade comes to disagree with itself. Name it once and the name is replaced by its text before the command is parsed, so a macro can hold a condition, a variable list, an operator or the command itself. A mistyped name is refused rather than quietly standing for nothing, which is what Stata does and how a do-file returns a wrong answer with no error in it.',
    examples: [
      { line: 'local wap ilo_wap == 1', note: 'Name a piece of script text for this run' },
      { line: 'replace emp = 3 if !inlist(emp, 1, 2) & `wap\'', note: 'Use it by name, written back with a backtick and an apostrophe' },
      { line: 'local employed `working\' | `helping\'', note: 'A macro written in terms of ones already defined' },
      { line: 'global round 2026', note: 'The other namespace, used as $round or ${round}' },
    ],
  },
  {
    title: 'Names and labels',
    blurb: 'These change what charts and dropdowns read, not the data underneath.',
    examples: [
      { line: 'rename q1 water_source', note: 'Carried to everything built on the old name' },
      { line: 'label variable adult "Aged 18 or over"', note: 'The question wording a chart shows' },
      { line: 'label define yesno 1 "Yes" 0 "No"', note: 'Define a value set' },
      { line: 'label values q1 yesno', note: 'Point a variable at one' },
      { line: 'drop q14 q15 q16', note: 'Variables you do not need' },
      { line: 'keep if age >= 15', note: 'Rows, with a condition' },
    ],
  },
  {
    title: 'Putting datasets together',
    blurb:
      'merge keeps everything by default and says which is which in _merge: 1 for rows only this side had, 2 for the other side, 3 for matched. Write the shape down and it is held to it - a 1:1 that meets a repeated key is refused rather than quietly multiplying rows.',
    examples: [
      { line: 'merge m:1 hhid using households, keep(match)', note: 'Join on a key, keeping only matched rows' },
      { line: 'merge 1:1 interview__key using paradata, nogen', note: 'One to one, without the _merge column' },
      { line: 'merge m:1 hhid using households, keepusing(province wealth)', note: 'Bring across only some variables' },
      { line: 'append using "Round 2"', note: 'Stack another dataset’s rows underneath, matched by name' },
    ],
  },
  {
    title: 'Summarising and reshaping',
    blurb:
      'These replace what is in memory rather than adding to it, exactly as in Stata: a person-level file becomes a province-level one. Give the result a name of its own with save as.',
    examples: [
      { line: 'collapse (mean) wage (sum) hours, by(province)', note: 'One row per group' },
      { line: 'collapse (count) person_id (sum) adult, by(hhid)', note: 'Counts and totals per household' },
      { line: 'contract province sex', note: 'How many rows each combination has, counted into _freq' },
      { line: 'reshape long inc, i(hhid) j(year)', note: 'inc2019 inc2020 into rows of inc, one per year' },
      { line: 'reshape wide inc, i(hhid) j(year)', note: 'And back into columns' },
    ],
  },
]

/** The vocabulary, as the engine actually defines it. */
const VOCABULARY: { label: string; items: string }[] = [
  {
    label: 'collapse statistics',
    items: 'mean, sum, count, max, min, median, p50, sd, first, last',
  },
  {
    label: 'egen, down a column',
    items: 'total, sum, mean, count, min, max, median, sd - with by()',
  },
  {
    label: 'egen, across a row',
    items: 'rowtotal, rowmean, rowmiss, rownonmiss, rowmax, rowmin',
  },
  {
    label: 'in expressions',
    items:
      'abs, ceil, exp, floor, int, ln, log, log10, round, sqrt, max, min, mod, length, lower, upper, trim, substr, year, month, day',
  },
  {
    label: 'same thing, Stata spelling',
    items: 'strlen, strlower, strupper, strtrim',
  },
  {
    label: 'and these',
    items: 'missing(x), mi(x), inlist(x, 1, 2), inrange(x, 0, 9), cond(c, a, b), string(x), real(s)',
  },
  {
    label: 'counting rows',
    items: '_n, _N, x[_n-1], x[_n+1], x[1], x[_N]',
  },
]

/** The reference, as the editor's side panel draws it. Without `onInsert` -
 *  a script the reader may not change - the lines are shown and not offered,
 *  since a click that put text in a box they cannot save is a click that
 *  promises something. */
export function ScriptHelp({ onInsert }: { onInsert?: (line: string) => void }) {
  // Open on the first section: a pane that starts entirely shut looks like a
  // heading, and the reason it exists is that people did not know what to type.
  const [open, setOpen] = useState<string | null>(SECTIONS[0].title)

  return (
    <div>
      <p className="mb-2 text-xs text-ink-500 dark:text-dark-600">
        {onInsert
          ? 'Click a line to put it in the script, where the cursor is.'
          : 'What the command language can do.'}
      </p>
      <div className="space-y-1">
        {SECTIONS.map((section) => {
          const showing = open === section.title
          return (
            <div
              key={section.title}
              className="rounded-card border border-ink-200 dark:border-dark-300"
            >
              <button
                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm font-medium text-ink-800 hover:bg-ink-50 dark:text-dark-800 dark:hover:bg-dark-100"
                onClick={() => setOpen(showing ? null : section.title)}
                aria-expanded={showing}
              >
                <span>{section.title}</span>
                <span aria-hidden className="text-xs text-ink-400">
                  {showing ? '−' : '+'}
                </span>
              </button>
              {showing && (
                <div className="border-t border-ink-200 px-3 py-2 dark:border-dark-300">
                  {section.blurb && (
                    <p className="mb-2 text-xs leading-relaxed text-ink-500 dark:text-dark-600">
                      {section.blurb}
                    </p>
                  )}
                  <ul className="space-y-1.5">
                    {section.examples.map((example) => (
                      <li key={example.line}>
                        {onInsert ? (
                          <button
                            className="w-full rounded px-2 py-1 text-left hover:bg-brand-50 dark:hover:bg-dark-100"
                            onClick={() => onInsert(example.line)}
                            title="Put this line in the script"
                          >
                            <ExampleLine example={example} />
                          </button>
                        ) : (
                          <div className="px-2 py-1">
                            <ExampleLine example={example} />
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="mt-3 border-t border-ink-200 pt-3 dark:border-dark-300">
        <p className="mb-1.5 text-xs font-medium text-ink-700 dark:text-dark-700">
          Words it knows
        </p>
        <dl className="space-y-1">
          {VOCABULARY.map((group) => (
            <div key={group.label} className="text-xs leading-relaxed">
              <dt className="inline text-ink-500 dark:text-dark-600">{group.label}: </dt>
              <dd className="inline font-mono text-ink-700 dark:text-dark-700">{group.items}</dd>
            </div>
          ))}
        </dl>
      </div>

      <p className="mt-3 text-xs text-ink-500 dark:text-dark-600">
        <code>*</code> and <code>//</code> start a comment, <code>///</code>{' '}
        continues a line. Lines run top to bottom and stop at the first error;
        what ran before it stays applied. The full reference, including what
        merge does with a missing key, is under <strong>Help</strong>.
      </p>
    </div>
  )
}

function ExampleLine({ example }: { example: Example }) {
  return (
    <>
      <code className="block whitespace-pre-wrap font-mono text-xs text-ink-800 dark:text-dark-800">
        {example.line}
      </code>
      <span className="text-xs text-ink-500 dark:text-dark-600">{example.note}</span>
    </>
  )
}
