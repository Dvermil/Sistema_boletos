import os
import tempfile
import shutil
from typing import List
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Form
from fastapi.responses import JSONResponse
import aiofiles
from concurrent.futures import ThreadPoolExecutor, as_completed

from ...core.config import settings
from ...models.schemas import PDFResult, ProcessingResponse, SendRequest, SendResponse
from ...processing.pdf_processor import process_pdf
from ...processing.soap_service import enviar_dados_soap

router = APIRouter()

# Executor para processamento paralelo
executor = ThreadPoolExecutor(max_workers=settings.MAX_WORKERS)

@router.post("/upload/", response_model=ProcessingResponse)
async def upload_pdfs(files: List[UploadFile] = File(...)):
    """Recebe arquivos PDF para processamento."""
    if not files:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "Nenhum arquivo enviado", "results": []}
        )
    
    results = []
    processed_files = []
    
    # Processar arquivos em paralelo
    future_to_file = {}
    
    for file in files:
        if not file.filename.lower().endswith('.pdf'):
            results.append(PDFResult(
                filename=file.filename,
                status="Erro",
                error="Formato inválido. Apenas PDFs são aceitos."
            ))
            continue
            
        # Criar arquivo temporário
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        try:
            # Ler e salvar o arquivo
            content = await file.read()
            temp_file.write(content)
            temp_file.close()
            
            # Adicionar à lista para processamento paralelo
            future = executor.submit(process_pdf, content, file.filename)
            future_to_file[future] = file.filename
            processed_files.append(temp_file.name)
        except Exception as e:
            results.append(PDFResult(
                filename=file.filename,
                status="Erro",
                error=f"Erro ao processar arquivo: {str(e)}"
            ))
    
    # Coletar resultados
    for future in as_completed(future_to_file):
        filename = future_to_file[future]
        try:
            result = future.result()
            # Converter para o modelo PDFResult
            pdf_result = PDFResult(
                filename=filename,
                id_fluxus=result.get("id_fluxus"),
                barcode=result.get("barcode"),
                barcode_source=result.get("barcode_source", "texto"),
                cnpj=result.get("cnpj"),
                fornecedor=result.get("fornecedor"),
                valor=result.get("valor"),
                vencimento=result.get("vencimento"),
                idpgto=result.get("idpgto"),
                status=result.get("status", "Processado"),
                error=result.get("error")
            )
            results.append(pdf_result)
        except Exception as e:
            results.append(PDFResult(
                filename=filename,
                status="Erro",
                error=f"Erro no processamento: {str(e)}"
            ))
    
    # Limpar arquivos temporários
    for temp_path in processed_files:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    
    return ProcessingResponse(
        success=True,
        message=f"Processados {len(results)} arquivos",
        results=results
    )

@router.post("/send/", response_model=SendResponse)
async def send_data(data: SendRequest):
    """Envia dados para o sistema via SOAP."""
    if not data.id_fluxus or not data.barcode:
        return JSONResponse(
            status_code=400,
            content={
                "success": False, 
                "message": "ID.Fluxus e código de barras são obrigatórios",
                "logs": []
            }
        )
    
    success, message, logs = enviar_dados_soap(
        data.id_fluxus,
        data.barcode,
        data.idpgto,
        data.cnpj,
        data.barcode_source
    )
    
    return SendResponse(
        success=success,
        message=message,
        logs=logs
    )

@router.post("/batch-send/", response_model=List[SendResponse])
async def batch_send(items: List[SendRequest]):
    """Envia múltiplos documentos em batch."""
    results = []
    
    for item in items:
        success, message, logs = enviar_dados_soap(
            item.id_fluxus,
            item.barcode,
            item.idpgto,
            item.cnpj,
            item.barcode_source
        )
        
        results.append(SendResponse(
            success=success,
            message=message,
            logs=logs
        ))
    
    return results