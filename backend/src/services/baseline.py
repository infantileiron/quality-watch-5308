from src.models.entities import BaselineWindow
from src.utils import repository as repo
from src.utils.identity import new_id,now
from src.services.ewma import baseline_statistics

def list_baselines():return repo.all_rows('baselines')
def create(data):
 if data.start>data.end:raise ValueError('基线起始序号不能大于结束序号')
 dataset=repo.get('datasets',data.dataset_id)
 rows=sorted([r for r in dataset['rows'] if r['machine']==data.machine and data.start<=r['sequence']<=data.end],key=lambda r:r['sequence'])
 values=[r['value'] for r in rows];mu,sigma=baseline_statistics(values)
 return repo.put('baselines',BaselineWindow(new_id('baseline'),data.name,data.dataset_id,data.machine,data.start,data.end,values,mu,sigma,now()))
