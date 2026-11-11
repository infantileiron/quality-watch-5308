import math,statistics

def baseline_statistics(values):
 if len(values)<5:raise ValueError('基线至少5次单值观测')
 if any(not math.isfinite(v) for v in values):raise ValueError('基线含非有限数')
 mu=statistics.mean(values);sigma=statistics.stdev(values)
 if sigma<=1e-12:raise ValueError('基线样本标准差为0或过小，不能校准控制界限')
 return mu,sigma

def ewma_series(rows,mu,sigma,smoothing=.2,width=3):
 if not math.isfinite(mu) or not math.isfinite(sigma) or sigma<=0 or not math.isfinite(smoothing) or not 0<smoothing<=1 or not math.isfinite(width) or width<=0:raise ValueError('基线或EWMA参数无效')
 if not rows:raise ValueError('监控区间没有观测')
 z=mu;result=[]
 for t,row in enumerate(rows,1):
  value=row['value']
  if not math.isfinite(value):raise ValueError('监控数据含非有限值')
  z=smoothing*value+(1-smoothing)*z
  spread=width*sigma*math.sqrt(smoothing/(2-smoothing)*(1-(1-smoothing)**(2*t)))
  lower,upper=mu-spread,mu+spread
  result.append({**row,'t':t,'ewma':z,'center':mu,'lcl':lower,'ucl':upper,'out_of_control':z<lower or z>upper})
 return result
