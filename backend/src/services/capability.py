import math,statistics

def capability(values,lsl,usl,sigma):
 if not values or any(not math.isfinite(v) for v in values) or not all(math.isfinite(x) for x in (lsl,usl,sigma)) or lsl>=usl or sigma<=0:raise ValueError('规格上下限、样本或基线sigma无效')
 mean=statistics.mean(values);outside=sum(v<lsl or v>usl for v in values)
 return {'mean':mean,'sigma_used':sigma,'cp':(usl-lsl)/(6*sigma),'cpk':min(usl-mean,mean-lsl)/(3*sigma),'below_lsl':sum(v<lsl for v in values),'above_usl':sum(v>usl for v in values),'outside_count':outside,'sample_count':len(values),'outside_rate':outside/len(values),'observed_sd':statistics.stdev(values) if len(values)>1 else None,'lsl':lsl,'usl':usl}
