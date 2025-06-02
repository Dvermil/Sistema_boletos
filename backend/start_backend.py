import os
import subprocess
import sys
import platform

def check_command(command):
    """Verifica se um comando está disponível no sistema."""
    try:
        subprocess.run(
            command, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            check=True, 
            shell=True
        )
        return True
    except subprocess.CalledProcessError:
        return False

def main():
    # Verificar requisitos
    print("Verificando requisitos do sistema...")
    
    # Verificar se as dependências estão instaladas
    if not check_command("pdfinfo -v"):
        print("Poppler não encontrado! Por favor, instale o Poppler primeiro.")
        print("Windows: https://github.com/oschwartz10612/poppler-windows/releases")
        print("Linux: sudo apt-get install poppler-utils")
        return False
    
    if not check_command("tesseract --version"):
        print("Tesseract OCR não encontrado! Por favor, instale o Tesseract primeiro.")
        print("Windows: https://github.com/UB-Mannheim/tesseract/releases")
        print("Linux: sudo apt-get install tesseract-ocr tesseract-ocr-por")
        return False
    
    # Criar diretórios necessários
    os.makedirs("data/uploads", exist_ok=True)
    os.makedirs("data/temp", exist_ok=True)
    os.makedirs("data/cache", exist_ok=True)
    
    # Instalar dependências se requirements.txt existir
    if os.path.exists("requirements.txt"):
        print("Instalando dependências Python...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    
    # Iniciar a API
    print("Iniciando a API FastAPI...")
    os.environ["UPLOAD_DIR"] = "data/uploads"
    os.environ["TEMP_DIR"] = "data/temp"
    os.environ["CACHE_DIR"] = "data/cache"
    
    subprocess.run(["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"])
    
    return True

if __name__ == "__main__":
    main()