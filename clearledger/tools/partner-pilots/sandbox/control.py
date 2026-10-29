#!/usr/bin/env python3
"""Реальное управление через admin HTTP владельцем; без control routes или ORM."""
import argparse
import asyncio
import json
import ssl
from urllib.parse import urlsplit
from runtime import PRIVATE, write_json


async def main():
    import httpx
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['revoke','operations-narrow','documents-member-revoke','rental-grant-revoke'])
    parser.add_argument('--client',choices=['references','monitoring','documents','portal'])
    parser.add_argument('--kind',choices=['grant','installation','credential'],default='installation')
    args=parser.parse_args()
    state=json.loads((PRIVATE/'owner-state.json').read_text())
    origin=urlsplit(state['origin'])
    if origin.scheme!='https' or origin.hostname!='127.0.0.1' or not origin.port or origin.username or origin.query or origin.fragment:
        raise RuntimeError('Owner control requires the exact loopback issuer')
    if state.get('adminMembershipRevoked'):
        raise RuntimeError('Final owner membership revocation already completed')
    if args.action=='rental-grant-revoke': args.client,args.kind='references','grant'
    if args.action=='revoke' and not args.client: parser.error('--client is required for revoke')
    fixture=state['fixture']
    async with httpx.AsyncClient(base_url=state['origin'],verify=ssl.create_default_context(cafile=state['caPath']),trust_env=False) as client:
        owner=fixture['owner']
        login=await client.post('/api/auth/login',json={k:owner[k] for k in ('email','password')})
        if login.status_code!=200: raise RuntimeError('Owner login failed')
        headers={'Authorization':'Bearer '+login.json()['access_token']}
        if args.action=='operations-narrow':
            row=state['clients']['monitoring']
            empty={'mode':'EMPTY','ids':[]}
            response=await client.post('/api/developer/clients/'+row['clientId']+'/installations',headers=headers,json={
                'companyId':fixture['companyId'],'scopes':row['scopes'],'locationIds':fixture['objects'][:1],
                'resourceScopes':{'objects':{'mode':'SET','ids':fixture['objects'][:1]},
                    'equipment':{'mode':'SET','ids':fixture['equipment'][:1]},
                    'counterparties':empty,'contracts':empty,'documents':empty}})
            if response.status_code!=201: raise RuntimeError('Actual installation narrowing failed')
        elif args.action=='documents-member-revoke':
            # Последняя admin-операция: субъект delegated OAuth и owner здесь один.
            response=await client.delete('/api/users/'+owner['userId']+'/companies/'+fixture['companyId'],headers=headers)
            if response.status_code!=204: raise RuntimeError('Actual membership revocation failed')
            state['adminMembershipRevoked']=True
        else:
            row=state['clients'][args.client]
            root='/api/developer/'
            paths={'installation':root+'installations/'+row['installationId']}
            if 'grantId' in row: paths['grant']=root+'grants/'+row['grantId']
            if 'credentialId' in row: paths['credential']=root+'clients/'+row['clientId']+'/credentials/'+row['credentialId']
            if args.kind not in paths: parser.error('No recorded identifier for this kind')
            response=await client.delete(paths[args.kind],headers=headers)
            if response.status_code!=200 or response.json().get('revoked') is not True:
                raise RuntimeError('Actual admin API did not confirm revocation')
    state.setdefault('completedControls',[]).append(args.action)
    write_json(PRIVATE/'owner-state.json',state)
    print('OWNER_CONTROL_COMPLETE '+args.action)

if __name__=='__main__': asyncio.run(main())
