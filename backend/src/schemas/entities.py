from pydantic import BaseModel,Field,ConfigDict
from typing import Literal
class InputModel(BaseModel):
 model_config=ConfigDict(allow_inf_nan=False)
class LoginInput(InputModel):
 email:str
 password:str
class DatasetInput(InputModel):
 name:str=Field(min_length=2,max_length=100)
 source:str=Field(default='shaft_diameter_202611.csv',max_length=100)
 csv_text:str=Field(min_length=20,max_length=1000000)
class RenameDataset(InputModel):
 name:str=Field(min_length=2,max_length=100)
class BaselineInput(InputModel):
 name:str=Field(min_length=2,max_length=100)
 dataset_id:str
 machine:str=Field(min_length=1,max_length=40)
 start:int=Field(default=1,ge=1)
 end:int=Field(default=60,ge=1)
class ControlStudyInput(InputModel):
 name:str=Field(min_length=2,max_length=100)
 baseline_id:str
 monitoring_start:int=Field(default=61,ge=1)
 monitoring_end:int=Field(default=200,ge=1)
 smoothing:float=Field(default=.2,gt=0,le=1)
 control_width:float=Field(default=3,gt=0,le=6)
 lsl:float=19.95
 usl:float=20.05
class RunInput(InputModel):
 study_id:str
class ReviewInput(InputModel):
 run_id:str
 comment:str=Field(min_length=5,max_length=2000)
class DecisionInput(InputModel):
 status:Literal['approved','rejected']
 comment:str=Field(min_length=5,max_length=2000)
class ReportInput(InputModel):
 run_id:str
 review_id:str
 title:str=Field(min_length=2,max_length=100)
