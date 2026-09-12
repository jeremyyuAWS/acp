import { expect, it } from 'vitest'
import { deliveryAccess } from './deliveryAccess.js'
it('hides inline Release when the role hides Release', () => {
  expect(deliveryAccess({tabs:{remediate:'operate',publish:'hidden'},capabilities:['release.publish']})).toEqual({visible:false,readOnly:true})
})
it.each([
  [{tabs:{publish:'view'},capabilities:['release.publish']},false],
  [{tabs:{publish:'operate'},capabilities:[]},false],
  [{tabs:{publish:'operate'},capabilities:['release.publish']},true],
])('retains Release view, capability, and historical restrictions', (access,historical) => {
  expect(deliveryAccess(access,historical)).toEqual({visible:true,readOnly:true})
})
it('allows an authorized live release from Remediate', () => {
  expect(deliveryAccess({tabs:{publish:'operate'},capabilities:['release.publish']})).toEqual({visible:true,readOnly:false})
})
