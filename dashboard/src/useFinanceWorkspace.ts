import { useCallback, useRef, useState } from 'react'

import {
  createDebt,
  createProject,
  createTransaction,
  deleteDebt,
  deleteProject,
  deleteTransaction,
  isFinanceWorkspace,
  resetFinanceWorkspace,
  seedFinanceWorkspace,
  updateDebt,
  updateProject,
  updateTransaction,
  type DebtInput,
  type FinanceWorkspace,
  type ProjectInput,
  type TransactionInput,
} from './financeWorkspace'

const STORAGE_KEY = 'hollawall-finance-demo-v3'

function persistSeed() {
  const seeded = seedFinanceWorkspace()
  localStorage.setItem(STORAGE_KEY, JSON.stringify(seeded))
  return seeded
}

function loadWorkspace() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return persistSeed()
    const parsed: unknown = JSON.parse(raw)
    return isFinanceWorkspace(parsed) ? parsed : persistSeed()
  } catch {
    return persistSeed()
  }
}

export function useFinanceWorkspace() {
  const [workspace, setWorkspaceState] = useState<FinanceWorkspace>(loadWorkspace)
  const workspaceRef = useRef(workspace)
  const setWorkspace = useCallback((updater: (current: FinanceWorkspace) => FinanceWorkspace) => {
    const next = updater(workspaceRef.current)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    workspaceRef.current = next
    setWorkspaceState(next)
  }, [])

  return {
    workspace,
    addProject: (input: ProjectInput) => setWorkspace((current) => createProject(current, input)),
    editProject: (id: string, input: ProjectInput) => setWorkspace((current) => updateProject(current, id, input)),
    removeProject: (id: string) => setWorkspace((current) => deleteProject(current, id)),
    addTransaction: (input: TransactionInput) => setWorkspace((current) => createTransaction(current, input)),
    editTransaction: (id: string, input: TransactionInput) => setWorkspace((current) => updateTransaction(current, id, input)),
    removeTransaction: (id: string) => setWorkspace((current) => deleteTransaction(current, id)),
    addDebt: (input: DebtInput) => setWorkspace((current) => createDebt(current, input)),
    editDebt: (id: string, input: DebtInput) => setWorkspace((current) => updateDebt(current, id, input)),
    removeDebt: (id: string) => setWorkspace((current) => deleteDebt(current, id)),
    reset: () => setWorkspace((current) => resetFinanceWorkspace(current)),
  }
}
