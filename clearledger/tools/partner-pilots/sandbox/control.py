#!/usr/bin/env python3
"""Owner-only actual admin HTTP revocation; no control route or ORM access."""
import argparse
import asyncio
import json
import ssl
from runtime import PRIVATE


async def main():
    import httpx
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['revoke'])
    parser.add_argument('--client',required=True,choices=['references','monitoring','documents','portal'])
    parser.add_argument('--kind',choices=['grant','installation','credential'],default='installation')
    args=parser.parse_args()
    state=json.loads((PRIVATE/'owner-state.json').read_text())
    row=state['clients'][args.client]
    root='/api/developer/'
    paths={'installation':root+'installations/'+row['installationId']}
    if 'grantId' in row: paths['grant']=root+'grants/'+row['grantId']
    if 'credentialId' in row: paths['credential']=root+'clients/'+row['clientId']+'/credentials/'+row['credentialId']
    if args.kind not in paths: parser.error('No recorded identifier for this kind')
    async with httpx.AsyncClient(base_url=state['origin'],verify=ssl.create_default_context(cafile=state['caPath']),trust_env=False) as client:
        owner=state['fixture']['owner']
        login=await client.post('/api/auth/login',json={k:owner[k] for k in ('email','password')})
        if login.status_code!=200: raise RuntimeError('Owner login failed')
        response=await client.delete(paths[args.kind],headers={'Authorization':'Bearer '+login.json()['access_token']})
        if response.status_code!=200 or response.json().get('revoked') is not True:
            raise RuntimeError('Actual admin API did not confirm revocation')
    print('REVOKED '+args.client+' '+args.kind)

if __name__=='__main__': asyncio.run(main())
