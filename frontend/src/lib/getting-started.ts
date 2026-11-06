/**
 * The getting-started list on the Overview: what a new install needs first.
 *
 * The server says which steps are done, judged from what exists rather than
 * from anybody having clicked through them; the words and where each leads
 * are here. A step the server does not send - inviting the team, to anyone
 * but an administrator - is simply not on the list.
 */

export interface StepState {
  key: string
  done: boolean
}

export interface Step extends StepState {
  title: string
  detail: string
  to: string
}

const STEPS: Record<string, Omit<Step, 'key' | 'done'>> = {
  project: {
    title: 'Create a project',
    detail: 'One for each survey or round: its data, scripts, dashboards and people in one place.',
    to: '/projects',
  },
  data: {
    title: 'Bring in your data',
    detail: 'Upload a Stata, SPSS, Excel or CSV file, or connect a Survey Solutions server.',
    to: '/datasets',
  },
  quality: {
    title: 'Check its quality',
    detail: 'Accept the checks recommended for your data: duplicate keys, short interviews, missing GPS.',
    to: '/quality',
  },
  indicator: {
    title: 'Track a number',
    detail: 'An indicator follows one figure - interviews completed, a response rate - against its target.',
    to: '/indicators',
  },
  dashboard: {
    title: 'Build a dashboard',
    detail: 'Charts, tables and indicators on one page, to read on screen or share.',
    to: '/dashboards',
  },
  team: {
    title: 'Invite your team',
    detail: 'Give field managers, analysts and viewers accounts of their own.',
    to: '/admin',
  },
}

/** The steps the server sent, worded, in its order; any it names that this
 *  page has no words for are left out rather than shown as a bare key. */
export function gettingStarted(states: StepState[]): Step[] {
  return states.flatMap((state) => (STEPS[state.key] ? [{ ...state, ...STEPS[state.key] }] : []))
}

/** Whether the list has anything to say: something left to do, and not put away. */
export function showGettingStarted(steps: Step[], hidden: boolean | null | undefined): boolean {
  return !hidden && steps.some((step) => !step.done)
}

/** The step to do next: the first not yet done. */
export function nextStep(steps: Step[]): Step | undefined {
  return steps.find((step) => !step.done)
}
