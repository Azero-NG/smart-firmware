#!/usr/bin/env python3
from __future__ import annotations
import argparse, asyncio, json
from aioesphomeapi import APIClient

async def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',required=True)
    parser.add_argument('--service')
    parser.add_argument('--data',default='{}')
    args=parser.parse_args()
    client=APIClient(args.host,6053,password=None,noise_psk=None)
    await client.connect(login=True)
    info, _, services = await client.device_info_and_list_entities()
    print(json.dumps({'name':info.name,'mac':info.mac_address,'esphome_version':getattr(info,'esphome_version',None),'services':[{'name':s.name,'key':s.key,'args':[a.name for a in s.args]} for s in services]},sort_keys=True))
    if not args.service:
        await client.disconnect()
        return 0
    service=next((s for s in services if s.name==args.service),None)
    if service is None:
        await client.disconnect()
        raise SystemExit(f'service not found: {args.service}')
    data=json.loads(args.data)
    await client.execute_service(service,data)
    print(json.dumps({'event':'executed','service':service.name,'data':data},sort_keys=True))
    await asyncio.sleep(0.25)
    try:
        await client.disconnect()
    except Exception:
        pass
    return 0

if __name__=='__main__':
    raise SystemExit(asyncio.run(main()))
