/**
 * The settings of a likely-duplicates check: which fields to compare and how,
 * what to compare within, how alike counts, and what tells the records apart.
 *
 * Rows rather than a multi-select, because each field carries its own way of
 * being compared - a name by spelling, an age within a year - and the rows are
 * where that is said. A variable chosen in a row is given the comparison its
 * type suggests (lib/likely-duplicates), which the row can then change.
 */
import { Field } from '@/components/ui'
import {
  COMPARE_METHODS,
  DEFAULT_SIMILARITY,
  describe,
  guessField,
  type DuplicateBlock,
  type DuplicateField,
  type LikelyDuplicatesConfig,
} from '@/lib/likely-duplicates'
import type { Variable } from '@/lib/types'

export default function LikelyDuplicatesFields({
  variables,
  config,
  onChange,
}: {
  variables: Variable[]
  config: LikelyDuplicatesConfig
  onChange: (next: LikelyDuplicatesConfig) => void
}) {
  // Two empty rows to start: one field alone is the exact duplicate check.
  const fields: DuplicateField[] = config.fields?.length
    ? config.fields
    : [
        { variable: '', compare: 'text', weight: 2 },
        { variable: '', compare: 'number', tolerance: 1, weight: 1 },
      ]
  const blocks = config.block ?? []
  const set = (patch: Partial<LikelyDuplicatesConfig>) => onChange({ ...config, fields, ...patch })

  const setField = (index: number, patch: Partial<DuplicateField>) =>
    set({ fields: fields.map((field, i) => (i === index ? { ...field, ...patch } : field)) })

  const chooseVariable = (index: number, name: string) => {
    const variable = variables.find((one) => one.name === name)
    setField(index, variable ? guessField(variable) : { variable: '' })
  }

  const setBlock = (index: number, patch: Partial<DuplicateBlock>) =>
    set({ block: blocks.map((block, i) => (i === index ? { ...block, ...patch } : block)) })

  const options = (
    <>
      <option value="">Choose a variable…</option>
      {variables.map((v) => (
        <option key={v.name} value={v.name}>
          {v.label ? `${v.name} - ${v.label}` : v.name}
        </option>
      ))}
    </>
  )

  return (
    <>
      <Field
        label="Compare these fields"
        hint="Each pair of records gets a similarity from these: the weighted average over the fields both records have. A blank is left out rather than counted as a difference."
      >
        <div className="space-y-2">
          {fields.map((field, index) => {
            const method = COMPARE_METHODS.find((one) => one.value === field.compare)
            return (
              <div key={index} className="space-y-1.5">
              <div className="flex flex-wrap items-center gap-2">
                <select
                  className="input w-56"
                  aria-label={`Field ${index + 1}`}
                  value={field.variable}
                  onChange={(event) => chooseVariable(index, event.target.value)}
                >
                  {options}
                </select>
                <select
                  className="input w-44"
                  aria-label={`How field ${index + 1} is compared`}
                  title={method?.hint}
                  value={field.compare}
                  onChange={(event) =>
                    setField(index, { compare: event.target.value as DuplicateField['compare'] })
                  }
                >
                  {COMPARE_METHODS.map((one) => (
                    <option key={one.value} value={one.value} title={one.hint}>
                      {one.label}
                    </option>
                  ))}
                </select>
                {method?.tolerance && (
                  <label className="flex items-center gap-1.5 text-xs text-ink-500">
                    ±
                    <input
                      className="input w-20"
                      type="number"
                      min={0}
                      aria-label={`Tolerance of field ${index + 1}`}
                      value={field.tolerance ?? 0}
                      onChange={(event) =>
                        setField(index, { tolerance: Math.max(0, Number(event.target.value) || 0) })
                      }
                    />
                    {method.tolerance === 'days' ? 'days' : ''}
                  </label>
                )}
                <label className="flex items-center gap-1.5 text-xs text-ink-500" title="How much this field counts towards the similarity">
                  weight
                  <select
                    className="input w-16"
                    aria-label={`Weight of field ${index + 1}`}
                    value={field.weight ?? 1}
                    onChange={(event) => setField(index, { weight: Number(event.target.value) })}
                  >
                    {[1, 2, 3, 4, 5].map((weight) => (
                      <option key={weight} value={weight}>
                        {weight}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="button"
                  className="btn-ghost btn-sm text-red-600"
                  aria-label={`Remove field ${index + 1}`}
                  disabled={fields.length <= 2}
                  onClick={() => set({ fields: fields.filter((_, i) => i !== index) })}
                >
                  ✕
                </button>
              </div>
              {field.compare === 'text' && field.variable && (
                <div className="flex flex-wrap items-center gap-2 pl-4">
                {/* A name kept in parts is joined before it is compared, so a
                    first name and a surname typed into each other's boxes
                    still read as one name. */}
                {(field.also ?? []).map((part, partIndex) => (
                    <span key={partIndex} className="flex items-center gap-1 text-xs text-ink-500">
                      +
                      <select
                        className="input w-44"
                        aria-label={`Field ${index + 1}, part ${partIndex + 2}`}
                        value={part}
                        onChange={(event) =>
                          setField(index, {
                            also: (field.also ?? []).map((one, i) =>
                              i === partIndex ? event.target.value : one,
                            ),
                          })
                        }
                      >
                        {options}
                      </select>
                      <button
                        type="button"
                        className="btn-ghost btn-sm"
                        aria-label={`Remove part ${partIndex + 2} of field ${index + 1}`}
                        onClick={() =>
                          setField(index, { also: (field.also ?? []).filter((_, i) => i !== partIndex) })
                        }
                      >
                        ✕
                      </button>
                    </span>
                  ))}
                {(field.also ?? []).length < 3 && (
                  <button
                    type="button"
                    className="btn-ghost btn-sm"
                    title="Join another variable to this one before comparing - a surname to a first name"
                    onClick={() => setField(index, { also: [...(field.also ?? []), ''] })}
                  >
                    + name part
                  </button>
                )}
                </div>
              )}
              </div>
            )
          })}
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={() => set({ fields: [...fields, { variable: '', compare: 'exact', weight: 1 }] })}
          >
            + Add a field
          </button>
        </div>
      </Field>

      <Field
        label="Only compare records with the same (optional)"
        hint="Comparing every record with every other is slow on a large dataset - a census is billions of pairs. Comparing within an enumeration area, a household or the first letter of a surname keeps it quick; a duplicate across two groups is then not looked for."
      >
        <div className="space-y-2">
          {blocks.map((block, index) => (
            <div key={index} className="flex flex-wrap items-center gap-2">
              <select
                className="input w-44"
                aria-label={`Compare within, ${index + 1}`}
                value={block.how}
                onChange={(event) =>
                  setBlock(index, { how: event.target.value as DuplicateBlock['how'] })
                }
              >
                <option value="same">same value of</option>
                <option value="first_letter">same first letter of</option>
              </select>
              <select
                className="input w-56"
                aria-label={`Variable to compare within, ${index + 1}`}
                value={block.variable}
                onChange={(event) => setBlock(index, { variable: event.target.value })}
              >
                {options}
              </select>
              <button
                type="button"
                className="btn-ghost btn-sm text-red-600"
                aria-label={`Remove grouping ${index + 1}`}
                onClick={() => set({ block: blocks.filter((_, i) => i !== index) })}
              >
                ✕
              </button>
            </div>
          ))}
          <button
            type="button"
            className="btn-ghost btn-sm"
            onClick={() => set({ block: [...blocks, { variable: '', how: 'same' }] })}
          >
            + Compare only within a group
          </button>
        </div>
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="How alike counts as a likely duplicate (%)"
          hint="90 finds a name spelled differently with the same age. Lower finds more, and more that are not."
        >
          <input
            className="input"
            type="number"
            min={50}
            max={100}
            aria-label="How alike counts as a likely duplicate"
            value={Math.round((config.min_similarity ?? DEFAULT_SIMILARITY) * 100)}
            onChange={(event) =>
              set({
                min_similarity: Math.min(1, Math.max(0.5, (Number(event.target.value) || 90) / 100)),
              })
            }
          />
        </Field>
        <Field
          label="Show to tell the records apart"
          hint="An interview key, a person's line number: listed beside each pair."
        >
          <select
            className="input"
            multiple
            size={4}
            aria-label="Variables that identify a record"
            value={config.id_variables ?? []}
            onChange={(event) =>
              set({
                id_variables: Array.from(event.target.selectedOptions).map((option) => option.value),
              })
            }
          >
            {variables.map((v) => (
              <option key={v.name} value={v.name}>
                {v.name}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <p className="mb-4 -mt-1 text-xs text-ink-500" role="status">
        {describe({ ...config, fields })}
      </p>
    </>
  )
}
