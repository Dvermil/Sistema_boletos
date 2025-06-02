"""
Módulo para classes de exceção customizadas do projeto Leitor Claro.
"""
from typing import Optional

class PDFProcessingError(Exception):
    """Classe base para exceções relacionadas ao processamento de PDFs."""
    def __init__(self, message: str, original_exception: Optional[Exception] = None, filename: Optional[str] = None):
        super().__init__(message)
        self.original_exception = original_exception
        self.filename = filename
        self.message = message

    def __str__(self) -> str:
        if self.filename:
            return f"{self.filename}: {self.message}"
        return self.message

class PDFTextExtractionError(PDFProcessingError):
    """Erro durante a extração de texto do PDF (sem OCR)."""
    pass

class PDFOCRError(PDFProcessingError):
    """Erro durante o processo de OCR do PDF."""
    pass

class BarcodeNotFoundError(PDFProcessingError):
    """Código de barras não encontrado no PDF após todas as tentativas."""
    def __init__(self, message: str = "Código de barras não encontrado no documento.", original_exception: Optional[Exception] = None, filename: Optional[str] = None):
        super().__init__(message, original_exception, filename)

class InvalidPDFError(PDFProcessingError):
    """Erro ao tentar abrir ou processar um PDF corrompido ou em formato inesperado."""
    pass

class SOAPAPIError(PDFProcessingError):
    """Erro na comunicação ou processamento da API SOAP TOTVS."""
    pass

class CNPJLookupError(PDFProcessingError):
    """Erro ao buscar IDPGTO pelo CNPJ."""
    pass

class ConfigurationError(PDFProcessingError):
    """Erro de configuração (ex: Tesseract não encontrado, credenciais ausentes)."""
    pass

class InvalidDataError(PDFProcessingError):
    """Dados extraídos ou fornecidos são inválidos."""
    pass

