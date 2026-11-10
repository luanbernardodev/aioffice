import numpy as np, pandas as pd
from engine import *; from run_grid import signals
CANDS=[('1h','RSIREV_r7_25/75_ma100',1.5,3,0,0),('4h','FIB_48_0.786',1.5,3,0,0),('4h','RSIREV_r7_30/70_ma200',None,None,None,None)]
d=pd.read_parquet('results.parquet')
for tf,s,sl,tr,act,tp in CANDS:
    if sl is None:
        r=d[(d.tf==tf)&(d.strat==s)].sort_values('pf_is',ascending=False).iloc[0]; sl,tr,act,tp=r.sl,r.trail,r.act,r.tp
    b=load(tf); sig,A=signals(b)
    o,h,l,c,sp=(b[k].values.astype(np.float64) for k in ('open','high','low','close','spread'))
    for mult in (1.0,1.5):
        p,ei,xi,sd=bt(o,h,l,c,sp*mult,A,sig[s],sl,tr,act,tp,0)
        t=pd.DataFrame({'pnl':p,'side':sd,'ent':b.index[ei],'ex':b.index[xi]})
        hold=(t.ex-t.ent).dt.total_seconds()/3600
        if mult==1.0:
            print(f'=== {tf} {s} SL{sl} TRAIL{tr} ACT{act} TP{tp}')
            print(' trades',len(t),'net pts',round(p.sum()),'=> US$ @0.01 lot:',round(p.sum()*0.01,2),' PF',round(p[p>0].sum()/-p[p<0].sum(),2),' win%',round((p>0).mean()*100))
            print(' long:',int((sd==1).sum()),round(p[sd==1].sum()),' short:',int((sd==-1).sum()),round(p[sd==-1].sum()),' hold med h:',round(hold.median(),1),'max h:',round(hold.max()))
            eq=np.cumsum(p); print(' maxDD pts',round((np.maximum.accumulate(np.maximum(eq,0))-eq).max()), ' maior perda',round(p.min()),' maior ganho',round(p.max()))
            print(' mensal pts:',t.groupby(t.ex.dt.to_period('M')).pnl.sum().round(0).astype(int).to_dict())
        else: print(' stress spread x1.5 -> net',round(p.sum()),'PF',round(p[p>0].sum()/-p[p<0].sum(),2))
