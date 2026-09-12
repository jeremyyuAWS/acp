import { isVisible, canOperate, hasCapability } from './access.js'

// Embedded publishing retains the Release tab's own permissions.
export function deliveryAccess(access, historical = false) {
  return {
    visible: isVisible(access, 'publish'),
    readOnly: historical || !canOperate(access, 'publish') || !hasCapability(access, 'release.publish'),
  }
}
