import os
import subprocess
import sys
import platform
import threading
import time

def start_backend():
    """Inicia o backend."""
    root_dir = os.path.dirname(os.path.abspath(__file__))  # caminho da pasta onde o script está
    backend_path = os.path.join(root_dir, "backend")
    os.chdir(backend_path)
    subprocess.run([sys.executable, "start_backend.py"])

def start_frontend():
    root_dir = os.path.dirname(os.path.abspath(__file__))
    frontend_path = os.path.join(root_dir, "frontend")
    os.chdir(frontend_path)
    
    # Direct approach instead of using the Node.js wrapper
    if platform.system() == "Windows":
        subprocess.run("npm start", shell=True)
    else:
        subprocess.run(["npm", "start"])

def main():
    """Função principal para iniciar todos os serviços."""
    print("=" * 60)
    print("   Inicializando Sistema de Boletos (sem Docker)   ")
    print("=" * 60)
    
    # Verificar requisitos do sistema
    print("Verificando requisitos do sistema...")
    
    # Verificar se Node.js está instalado
    try:
        subprocess.run(
            ["node", "--version"], 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Node.js não encontrado! Por favor, instale o Node.js primeiro.")
        print("Download: https://nodejs.org/")
        return False
    
    # Verificar se pip está instalado
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            check=True
        )
    except subprocess.CalledProcessError:
        print("Pip não encontrado! Por favor, instale o pip primeiro.")
        return False
    
    # Iniciar o backend em uma thread separada
    backend_thread = threading.Thread(target=start_backend)
    backend_thread.daemon = True
    backend_thread.start()
    
    # Aguardar um pouco para garantir que o backend seja iniciado primeiro
    print("Aguardando inicialização do backend...")
    time.sleep(5)
    
    # Iniciar o frontend
    start_frontend()
    
    return True

if __name__ == "__main__":
    main()