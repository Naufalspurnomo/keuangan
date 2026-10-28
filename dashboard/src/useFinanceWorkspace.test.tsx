import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'

import { useFinanceWorkspace } from './useFinanceWorkspace'
import type { ProjectInput } from './financeWorkspace'

const project = (name: string): ProjectInput => ({
  name,
  company: 'Holla',
  status: 'active',
  started_on: '2026-10-01',
  completed_on: null,
  client: '',
  contract_value: null,
  notes: '',
})

describe('useFinanceWorkspace', () => {
  beforeEach(() => localStorage.clear())

  it('serializes two mutations issued in the same React tick without losing either', () => {
    const { result } = renderHook(() => useFinanceWorkspace())
    const initial = result.current.workspace.projects.length
    act(() => {
      result.current.addProject(project('Mutasi Cepat A'))
      result.current.addProject(project('Mutasi Cepat B'))
    })
    expect(result.current.workspace.projects).toHaveLength(initial + 2)
    expect(result.current.workspace.projects.slice(-2).map((item) => item.name)).toEqual(['Mutasi Cepat A', 'Mutasi Cepat B'])
    expect(result.current.workspace.audit.map((event) => event.action)).toEqual(['create', 'create'])
  })
})
