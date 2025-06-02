from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

class PDFResult(BaseModel):
    filename: str
    id_fluxus: Optional[str] = None
    barcode: Optional[str] = None
    barcode_source: Optional[str] = "texto"
    cnpj: Optional[str] = None
    fornecedor: Optional[str] = None
    valor: Optional[str] = None
    vencimento: Optional[str] = None
    idpgto: Optional[str] = None
    status: str = "Processado"
    error: Optional[str] = None

class ProcessingResponse(BaseModel):
    success: bool
    message: str
    results: List[PDFResult] = []

class SendRequest(BaseModel):
    id_fluxus: str
    barcode: str
    idpgto: Optional[str] = None
    cnpj: Optional[str] = None
    barcode_source: Optional[str] = "texto"

class SendResponse(BaseModel):
    success: bool
    message: str
    logs: List[str] = []