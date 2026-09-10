import { listSpFolders, listSharePointSites, listSharePointDrives } from './api.js'

const SITE = 'release-site:'

// Sites and libraries are navigation rows, never release destinations. Only real
// folders returned by Graph can be selected and persisted as drive/item pairs.
export async function listReleaseMicrosoftFolders(parent = 'root') {
  if (parent.startsWith(SITE)) {
    const response = await listSharePointDrives(parent.slice(SITE.length))
    return { folders: (response.drives || []).map(drive => ({
      id: `${drive.id}/root`, name: drive.name, selectable: false,
    })) }
  }
  if (parent !== 'root') return listSpFolders(parent)
  const [personal, sites] = await Promise.allSettled([listSpFolders('root'), listSharePointSites()])
  const folders = [
    ...(sites.status === 'fulfilled' ? (sites.value.sites || []).map(site => ({
      id: `${SITE}${site.id}`, name: `SharePoint · ${site.name}`, selectable: false,
    })) : []),
    ...(personal.status === 'fulfilled' ? (personal.value.folders || []) : []),
  ]
  if (!folders.length && (personal.status === 'rejected' || sites.status === 'rejected')) {
    const error = sites.status === 'rejected' ? sites.reason : personal.reason
    throw new Error(`${error?.status ? `${error.status}: ` : ''}${error?.message || 'Microsoft folders could not be loaded.'}`)
  }
  return { folders }
}
