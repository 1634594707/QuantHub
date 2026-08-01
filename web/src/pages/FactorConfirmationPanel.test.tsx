import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api/client'
import { FactorConfirmationPanel } from './FactorConfirmationPanel'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('FactorConfirmationPanel', () => {
  it('requires an explicit irreversible acknowledgement before opening the locked set', async () => {
    const plan = {
      id: 'plan-locked-alpha',
      title: '锁定样本研究计划',
      target_market: 'a_shares',
      budget: {
        maximum_candidates: 20,
        maximum_compute_units: 1000,
        maximum_llm_tokens: 100000,
        maximum_confirmation_set_openings: 1,
        maximum_round_candidates: 100,
        maximum_formula_complexity: 30,
        maximum_duplicate_rate: 0.25,
        stop_conditions: {},
        data_split: {
          discovery: { start: '2020-01-01', end: '2021-12-31', data_fingerprint: 'a'.repeat(64) },
          rolling_validation: { start: '2022-01-10', end: '2024-12-31', data_fingerprint: 'b'.repeat(64) },
          locked_confirmation: { start: '2025-01-10', end: '2025-12-31', data_fingerprint: 'c'.repeat(64) },
          purge_periods: 5,
          embargo_periods: 2,
        },
      },
      usage: {
        candidates: 1,
        compute_units: 5,
        llm_tokens: 0,
        confirmation_set_openings: 0,
        confirmation_set_openings_reserved: 1,
        experiments: 1,
      },
      created_at: 1_785_400_000,
    }
    const experiment = {
      id: 'experiment-success-1',
      research_plan_id: plan.id,
      hypothesis: '滚动窗口保持方向一致',
      source: 'human',
      parent_experiment_id: null,
      factor_definition_id: 'definition-1',
      candidate_validation_id: 'validation-1',
      factor_key: 'dsl_momentum',
      factor_version: '1.0.0',
      factor_family: 'momentum',
      target_market: 'a_shares',
      data_start: '2020-01-01',
      data_end: '2024-12-31',
      parameter_grid: {},
      parameter_combinations: 1,
      estimated_compute_units: 5,
      model: {},
      prompt: {},
      proposal: { applicable_regimes: [], invalidation_conditions: [], falsification_tests: [], ai_trace: {} },
      pre_registration: {
        primary_metric: 'rank_ic_mean',
        secondary_metrics: [],
        pass_criteria: { minimum_rank_ic: 0.03 },
        maximum_candidates: 1,
        maximum_llm_tokens: 0,
        confirmation_set_openings: 1,
      },
      attempt_number: 1,
      status: 'succeeded',
      created_at: 1_785_400_100,
    }
    vi.spyOn(api, 'factorResearchPlans').mockResolvedValue({ ok: true, count: 1, plans: [plan] } as never)
    vi.spyOn(api, 'factorExperiments').mockResolvedValue({
      ok: true, count: 1, cumulative_attempts: 1, experiments: [experiment],
    } as never)
    vi.spyOn(api, 'factorConfirmationSet').mockResolvedValue({ ok: true, opened: false, opening: null })
    const open = vi.spyOn(api, 'openFactorConfirmationSet').mockResolvedValue({
      ok: true,
      opened: true,
      opening: {
        id: 'opening-1',
        research_plan_id: plan.id,
        experiment_id: experiment.id,
        confirmation_data_fingerprint: 'c'.repeat(64),
        opened_by: 'researcher-a',
        irreversible_ack: true,
        created_at: 1_785_400_200,
      },
      idempotent_replay: false,
      further_experiments_blocked: true,
    })

    render(<FactorConfirmationPanel />)

    expect(await screen.findByText('签署一次性开启合同')).toBeTruthy()
    const openButton = await screen.findByRole('button', { name: '不可逆地开启确认集' }) as HTMLButtonElement
    expect(openButton.disabled).toBe(true)

    fireEvent.change(screen.getByDisplayValue('local-researcher'), { target: { value: 'researcher-a' } })
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.change(screen.getByPlaceholderText(plan.id), { target: { value: plan.id } })
    expect(openButton.disabled).toBe(false)
    fireEvent.click(openButton)

    await waitFor(() => expect(open).toHaveBeenCalledWith(plan.id, {
      experiment_id: experiment.id,
      confirmation_data_fingerprint: 'c'.repeat(64),
      opened_by: 'researcher-a',
      irreversible_ack: true,
    }))
    expect(await screen.findByText('确认集已开启，计划已冻结')).toBeTruthy()
    expect(screen.getByText('opening-1')).toBeTruthy()
  })
})
