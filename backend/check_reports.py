import json, urllib.request, time
B='http://127.0.0.1:8000/api/v1'
def req(p, data=None, tok=None):
    r=urllib.request.Request(B+p, data=json.dumps(data).encode() if data is not None else None,
        headers={'Content-Type':'application/json', **({'Authorization':'Bearer '+tok} if tok else {})})
    return json.load(urllib.request.urlopen(r, timeout=120))
tok=req('/auth/login',{'email':'aoi-verify@example.com','password':'verify-password-123'})['access_token']
cs=[c for c in req('/catchments',tok=tok) if '(village AOI)' in c['name']]
deadline=time.time()+900
while time.time()<deadline:
    done=0
    for c in cs:
        h=req(f'/catchments/{c["id"]}/water-reports/history',tok=tok)
        if h: done+=1
    if done==len(cs): break
    time.sleep(20)
print(f'{done}/{len(cs)} catchments have a completed report\n')
for c in sorted(cs,key=lambda x:x['name']):
    h=req(f'/catchments/{c["id"]}/water-reports/history',tok=tok)
    if not h:
        print(f'{c["name"]:<36} area={c["area_ha"]:>8.1f} ha  -> NO REPORT'); continue
    r=h[0]; wb=r['water_balance']; rs=r['recharge_stress']
    print(f'{c["name"]:<36} area={c["area_ha"]:>8.1f} ha')
    print(f'   rainfall {wb.get("rainfall_mm")} mm | ET {wb.get("et_mm")} mm | runoff {wb.get("runoff_mm")} mm | dS {wb.get("storage_change_mm")} mm ({wb["storage_change_band"]})')
    print(f'   completeness {wb["data_completeness"]}% | flags {wb["resolution_flags"]}')
    print(f'   stress {rs["stress_score"]}/100 ({rs["stress_band"]}) | rain_ratio {rs.get("rainfall_anomaly_ratio")} | VCI {rs.get("vci")} | SW pct {rs.get("surface_water_trend")}')
    print(f'   confidence {rs["raw_inputs"].get("confidence")}')
