import csv,io,math
from dataclasses import asdict
from src.models.entities import MeasurementDataset
from src.utils import repository as repo
from src.utils.identity import new_id,now

def summary(item):return {k:v for k,v in item.items() if k!='rows'}|{'row_count':len(item['rows']),'machines':sorted({r['machine'] for r in item['rows']})}
def list_datasets():return [summary(x) for x in repo.all_rows('datasets')]
def detail(id):return repo.get('datasets',id)
def rename(id,data):
 item=repo.get('datasets',id);item['name']=data.name;repo.put('datasets',item);return summary(item)
def create(data):
 reader=csv.DictReader(io.StringIO(data.csv_text.lstrip('\ufeff')))
 if not {'sample_id','machine','sequence','value'}.issubset(reader.fieldnames or []):raise ValueError('CSV需要sample_id,machine,sequence,value列；value单位mm')
 rows=[];ids=set();keys=set()
 for n,r in enumerate(reader,2):
  if n>5001:raise ValueError('最多5000次单值观测')
  try:
   seq=int(r['sequence']);value=float(r['value']);machine=r['machine'].strip();key=(machine,seq)
   if not math.isfinite(value) or not 0<value<=1000000 or seq<1 or not r['machine'].strip() or not r['sample_id'].strip() or r['sample_id'] in ids or key in keys:raise ValueError()
  except (TypeError,ValueError):raise ValueError(f'第{n}行样本编号/机台序号/尺寸无效或重复')
  ids.add(r['sample_id']);keys.add(key);rows.append({'sample_id':r['sample_id'],'machine':machine,'sequence':seq,'value':value})
 if len(rows)<5:raise ValueError('至少5次单值观测')
 item=MeasurementDataset(new_id('ds'),data.name,data.source,rows,now());repo.put('datasets',item);return summary(asdict(item))
