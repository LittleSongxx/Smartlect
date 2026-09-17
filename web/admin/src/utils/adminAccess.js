import { TRIAL_MENU_PATHS } from '@/constants/trial'

export const ADMIN_PERMISSION = Object.freeze({
  AI_EVALUATE: 'ai:evaluate',
  AI_PILOT: 'ai:pilot',
  ANALYTICS_READ: 'analytics:read',
  ANALYTICS_EXPORT: 'analytics:export',
  AUDIT_READ: 'audit:read',
  ADMIN_TRIAL: 'admin:trial',
})

export function normalizeAdminPrincipal(value) {
  const principal = value && typeof value === 'object' ? value : {}
  return {
    ...principal,
    roles: Array.isArray(principal.roles) ? principal.roles : [],
    permissions: Array.isArray(principal.permissions) ? principal.permissions : [],
  }
}

export function hasAdminPermission(principal, permission) {
  return normalizeAdminPrincipal(principal).permissions.includes(permission)
}

export function hasAnyAdminPermission(principal, permissions) {
  const granted = new Set(normalizeAdminPrincipal(principal).permissions)
  return permissions.some((permission) => granted.has(permission))
}

export function isTrialAdmin(principal) {
  const current = normalizeAdminPrincipal(principal)
  return current.roles.includes('TRIAL_OPERATOR') || current.permissions.includes(ADMIN_PERMISSION.ADMIN_TRIAL)
}

export function filterTrialMenu(items) {
  return items
    .map((item) => {
      if (item.children) {
        const children = item.children.filter((child) => TRIAL_MENU_PATHS.has(child.path))
        return children.length ? { ...item, children } : null
      }
      return TRIAL_MENU_PATHS.has(item.path) ? item : null
    })
    .filter(Boolean)
}
