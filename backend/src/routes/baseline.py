from fastapi import APIRouter,Depends
from src.controllers import baseline as controller
from src.schemas.entities import BaselineInput
from src.services.auth import current,editor
router=APIRouter(prefix='/baselines',tags=['baselines'])
@router.get('')
def list_items(user=Depends(current)):return controller.list_items()
@router.post('',status_code=201)
def create(data:BaselineInput,user=Depends(editor)):return controller.create(data)
