"""Export ARCOS damage records to data/processed/damage_records.csv, tagged by weather event.

Event windows were matched against the Open-Meteo archive (see PLAN.md, section 3).
Run:  .venv/Scripts/python scripts/export_damage.py
"""
import sys,struct,collections,csv,datetime as dt
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
src=Path(sys.argv[1]) if len(sys.argv)>1 else next(p for p in [ROOT/'data/extracted/Data1/arcos_prod_damage_09_28_Clip.dbf',ROOT/'data/raw/Data1/arcos_prod_damage_09_28_Clip.dbf'] if p.exists())
b=open(src,'rb').read(); n,hl,rl=struct.unpack('<IHH',b[4:12]); fl=[];i=32
while b[i]!=0x0D: fl.append((b[i:i+11].split(b'\0')[0].decode(),b[i+16])); i+=32
rs=[]
for r in range(n):
    s=hl+r*rl+1;o=0;d={}
    for nm,ln in fl: d[nm]=b[s+o:s+o+ln].decode('latin1').strip(); o+=ln
    rs.append(d)
D=lambda s: dt.date(int(s[:4]),int(s[4:6]),int(s[6:])) if len(s)==8 else None
minor={'20250305','20250306','20250316','20250317','20250513','20250517','20250531','20251020','20251219'}
def tag(t):
    if '20240926'<=t<='20240930': return 'helene_2024'
    if '20250212'<=t<='20250215': return 'feb_2025_ice'
    if '20250216'<=t<='20250218': return 'feb_2025_wind'
    if t in minor: return 'minor_wind_2025'
    named={('20240109','20240110'):'wind_rain_2024_01',('20240411','20240412'):'storms_2024_04',('20240526','20240527'):'storms_2024_05',
      ('20240808','20240809'):'debby_remnants_2024_08',('20241001','20241002'):'helene_late_reports',('20241122','20241123'):'wind_2024_11',
      ('20250105','20250107'):'winter_storm_2025_01'}
    for (a,z),nm in named.items():
        if a<=t<=z: return nm
    return 'background'
out=[]
for k,r in enumerate(rs,1):
    rep,fix=D(r['Report_Tim']),D(r['Repaired_D'])
    days=(fix-rep).days if rep and fix else ''
    out.append({'record':k,'event':tag(r['Report_Tim']),'report_date':rep,'repaired':r['Repaired'],'repaired_date':fix or '',
      'repair_days':days,'repair_days_flag':'paperwork?' if days!='' and days>14 else '',
      'substation':r['Substation'],'circuit':r['Circuit'],'asset_type':r['Asset_Type'] or '(blank)','damage':r['Inform_Wor'],
      'access_issue':r['Access_Iss'],'special_equipment':r['Special_Eq'],'photos':int(float(r['Media'] or 0)),
      'latitude':round(float(r['Latitude']),5),'longitude':round(float(r['Longitude']),5)})
p=sys.argv[2] if len(sys.argv)>2 else ROOT/'data/processed/damage_records.csv'
with open(p,'w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(out[0])); w.writeheader(); w.writerows(out)
print('wrote',len(out))
ev=sorted({o['event'] for o in out},key=lambda e:-sum(o['event']==e for o in out))
for e in ev:
    g=[o for o in out if o['event']==e]; rd=sorted(o['repair_days'] for o in g if o['repair_days']!='' and o['repair_days']<=14)
    print(f"{e:16} n={len(g):4} dates {min(o['report_date'] for o in g)}..{max(o['report_date'] for o in g)} access={sum(o['access_issue']=='Yes' for o in g):3} notRepaired={sum(o['repaired']=='No' for o in g):2} median_repair_d={rd[len(rd)//2] if rd else '-'}  {dict(collections.Counter(o['asset_type'] for o in g).most_common(6))}")
bg=[o for o in out if o['event']=='background']
print('background by year:',dict(sorted(collections.Counter(o['report_date'].year for o in bg).items())))
print('background top dates:',collections.Counter(str(o['report_date']) for o in bg).most_common(8))
print('special equipment:',collections.Counter(o['special_equipment'] or 'none' for o in out).most_common())
print('circuits:',len({o['circuit'] for o in out}),'substations:',len({o['substation'] for o in out}))
