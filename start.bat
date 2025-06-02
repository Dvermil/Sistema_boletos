@echo off
echo =========================================
echo    Inicializando Sistema de Boletos      
echo =========================================

REM Verificar se o Docker está instalado
where docker >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Docker não encontrado! Por favor, instale o Docker primeiro.
    exit /b 1
)

REM Criando estrutura de diretórios
echo Criando estrutura de diretórios...
mkdir data\uploads data\temp data\cache 2>nul

REM Iniciando serviços com Docker Compose
echo Iniciando serviços...
docker-compose up -d

if %ERRORLEVEL% EQU 0 (
    echo =========================================
    echo    Sistema iniciado com sucesso!         
    echo    Backend: http://localhost:8000        
    echo    Frontend: http://localhost:3000       
    echo    API Docs: http://localhost:8000/docs  
    echo =========================================
) else (
    echo Falha ao iniciar os serviços. Verifique os logs com 'docker-compose logs'.
    exit /b 1
)