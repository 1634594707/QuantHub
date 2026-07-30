import { describe, expect, it } from 'vitest'
import { shouldAdoptEvaluationRun } from './researchRunNavigation'

describe('shouldAdoptEvaluationRun', () => {
  it('adopts the evaluation run when no history record is selected', () => {
    expect(shouldAdoptEvaluationRun('', 'evaluation-run')).toBe(true)
  })

  it('preserves a manually selected history record', () => {
    expect(shouldAdoptEvaluationRun('manual-run', 'evaluation-run')).toBe(false)
  })

  it('does nothing before the evaluation has a run', () => {
    expect(shouldAdoptEvaluationRun('', '')).toBe(false)
  })
})
