from src.models.entities import ControlStudy
from src.utils import repository as repo
from src.utils.identity import new_id,now

def list_studies():return repo.all_rows('studies')
def create(data):
 baseline=repo.get('baselines',data.baseline_id)
 if data.lsl>=data.usl:raise ValueError('规格下限必须小于上限')
 if data.monitoring_start<=baseline['end']:raise ValueError('监控区间必须严格位于锁定基线之后，防止基线泄漏')
 if data.monitoring_start>data.monitoring_end:raise ValueError('监控起始序号不能大于结束序号')
 return repo.put('studies',ControlStudy(new_id('study'),data.name,data.baseline_id,data.monitoring_start,data.monitoring_end,data.smoothing,data.control_width,data.lsl,data.usl,now()))
