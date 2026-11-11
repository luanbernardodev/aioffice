import numpy as np, pandas as pd
from grid_nq import load, signals, sma, rsi
from grid_wr import bt2
b=load('h1'); sig,A=signals(b)
o,h,l,c,sp=(b[k].values.astype(np.float64) for k in ('open','high','low','close','sp'))
XS={'none':np.zeros(len(c),np.bool_)}
C=[('RSIREV_r5_25_s200|long',2.0,0,0.75,1.5,1.5),('RSIREV_r5_25_s200|long',3.0,0,0.75,1.5,1.5),('RSIREV_r5_25_s200|long',4.0,0,0.75,1.5,1.5),('RSI2_5_s100|long',3.0,0,0,1.5,1.5)]
for s,sl,tp,be,at,tr in C:
    for m in (1,2):
        p,ei=bt2(o,h,l,c,sp*m,A,sig[s],XS['none'],sl,tp,be,at,tr)
        if m==2: print('   custo x2: PF',round(p[p>0].sum()/-p[p<0].sum(),2),'WR',round((p>0).mean()*100)); continue
        eq=np.cumsum(p); t=pd.Series(p,index=b.index[ei])
        print(f'== {s} SL{sl} BE{be} TRAIL após {at}ATR dist {tr}ATR')
        print('  n',len(p),'WR%',round((p>0).mean()*100),'PF',round(p[p>0].sum()/-p[p<0].sum(),2),'net',round(p.sum()),'DD',round((np.maximum.accumulate(np.maximum(eq,0))-eq).max()),
              '| ganho médio',round(p[p>0].mean()),'perda média',round(p[p<0].mean()),'pior',round(p.min()),'| WF3',[round(z.sum()) for z in np.array_split(p,3)])
        mm=t.groupby(t.index.strftime('%y-%m')).sum(); print('  meses +',(mm>0).sum(),'/',len(mm), ' maior seq. perdas', max(len(x) for x in ''.join('L' if v<0 else 'W' for v in p).split('W')))
