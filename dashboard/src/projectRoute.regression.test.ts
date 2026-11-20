import { describe, expect, it } from 'vitest'
import { projectDocumentRoute, readProjectDocumentRoute, type ProjectDetailTab } from './projectDocuments'

describe('Project deep link preservation', () => {
  it.each<ProjectDetailTab>(['overview', 'transactions', 'debts', 'profitability', 'presensi', 'documents', 'audit'])('preserves %s across reload', (tab) => {
    const route = { projectId: 'controlled-project', tab }
    expect(readProjectDocumentRoute(projectDocumentRoute(route))).toMatchObject(route)
  })
  it('falls back safely for unknown tabs', () => {
    expect(readProjectDocumentRoute('#projects?project=controlled-project&tab=unknown').tab).toBe('transactions')
  })
})
