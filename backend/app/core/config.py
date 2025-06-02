import os
from pathlib import Path
from dotenv import load_dotenv

# Carregar variáveis de ambiente do arquivo .env se existir
env_path = Path(".") / ".env"
load_dotenv(dotenv_path=env_path)

class Settings:
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Sistema de Leitura de Boletos"
    
    # Configurações de CORS
    BACKEND_CORS_ORIGINS: list = ["http://localhost:3000", "http://localhost:8000"]
    
    # Diretórios de trabalho
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./uploads")
    TEMP_DIR: str = os.getenv("TEMP_DIR", "./temp")
    CACHE_DIR: str = os.getenv("CACHE_DIR", "./cache")
    
    # Configurações de OCR
    TESSERACT_CMD: str = os.getenv("TESSERACT_CMD", "tesseract")
    OCR_DPI: int = int(os.getenv("OCR_DPI", "300"))
    
    # Configurações de processamento
    MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", "4"))
    EXTRACTION_STRATEGY: str = os.getenv("EXTRACTION_STRATEGY", "complete")
    
    # Configurações SOAP
    SOAP_URL: str = os.getenv("SOAP_URL", "http://10.131.0.13:8051/wsDataServer/IwsDataServer")
    SOAP_USERNAME: str = os.getenv("SOAP_USERNAME", "douglas.vermil")
    SOAP_PASSWORD: str = os.getenv("SOAP_PASSWORD", "Chouest123@")

    # Criar diretórios necessários
    def create_directories(self):
        for dir_path in [self.UPLOAD_DIR, self.TEMP_DIR, self.CACHE_DIR]:
            os.makedirs(dir_path, exist_ok=True)

settings = Settings()