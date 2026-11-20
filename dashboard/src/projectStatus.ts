export const PROJECT_STATUSES = ['planned', 'active', 'completed', 'cancelled'] as const

export type ProjectStatus = typeof PROJECT_STATUSES[number]
export type VisibleProjectStatus = Exclude<ProjectStatus, 'planned'>

/** Planned is retained only when reading older records; the product now treats it as active. */
export function visibleProjectStatus(status: ProjectStatus): VisibleProjectStatus {
  return status === 'planned' ? 'active' : status
}
