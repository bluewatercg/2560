from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.common import ApiResponse
from app.services.strategy2560_service import Strategy2560Service

router = APIRouter(prefix='/api/data-quality', tags=['data-quality'])

@router.get('/summary', response_model=ApiResponse)
def summary(db: Session = Depends(get_db)):
    return ApiResponse(data=Strategy2560Service(db).data_quality_summary())
