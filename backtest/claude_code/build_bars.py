import pandas as pd, numpy as np, glob, sys
out=[]
for f in sorted(glob.glob('/mnt/user-data/uploads/BTCUSD_*.csv')):
    df=pd.read_csv(f,sep='\t',usecols=[0,1,2,3],names=['d','t','bid','ask'],header=0,dtype={'d':str,'t':str,'bid':'float64','ask':'float64'})
    df['ts']=pd.to_datetime(df.d+' '+df.t,format='%Y.%m.%d %H:%M:%S.%f')
    df=df[['ts','bid','ask']].ffill().dropna()
    df=df.set_index('ts')
    m=df.bid.resample('1min').ohlc()
    m['spread']=(df.ask-df.bid).resample('1min').mean()
    m['ticks']=df.bid.resample('1min').count()
    m=m.dropna(subset=['open'])
    out.append(m); print(f, len(df), len(m), flush=True)
    del df
m1=pd.concat(out); m1=m1[~m1.index.duplicated()]
m1.to_parquet('/home/claude/bt/m1.parquet'); print(m1.describe())
