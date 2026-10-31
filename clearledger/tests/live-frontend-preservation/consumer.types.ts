import type { SiteDetail } from '../../src/services/sitesService'

type PreservedPassport = Pick<SiteDetail, 'dismantleLocationIds' | 'decommissionedOn'>
const persisted: PreservedPassport = { dismantleLocationIds: ['legacy-string-location'], decommissionedOn: '2030-01-02' }
const cleared: PreservedPassport = { dismantleLocationIds: [], decommissionedOn: null }
void [persisted, cleared]
// @ts-expect-error Location identifiers remain strings, including historical non-UUID IDs.
const invalidIds: PreservedPassport = { dismantleLocationIds: [12], decommissionedOn: null }
// @ts-expect-error Explicit nullable clear must remain expressible; numbers are not dates.
const invalidDate: PreservedPassport = { dismantleLocationIds: [], decommissionedOn: 20300102 }
void [invalidIds, invalidDate]
