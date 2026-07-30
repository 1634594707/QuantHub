export function shouldAdoptEvaluationRun(
  requestedRunId: string,
  evaluationRunId: string,
): boolean {
  return Boolean(evaluationRunId && !requestedRunId)
}
