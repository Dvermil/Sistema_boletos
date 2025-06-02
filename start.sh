#!/bin/bash

# Cores para saída no terminal
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}   Inicializando Sistema de Boletos      ${NC}"
echo -e "${GREEN}=========================================${NC}"

# Verificar se o Docker está instalado
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker não encontrado! Por favor, instale o Docker primeiro.${NC}"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}Docker Compose não encontrado! Por favor, instale o Docker Compose primeiro.${NC}"
    exit 1
fi

# Criando estrutura de diretórios
echo -e "${YELLOW}Criando estrutura de diretórios...${NC}"
mkdir -p data/uploads data/temp data/cache

# Iniciando serviços com Docker Compose
echo -e "${YELLOW}Iniciando serviços...${NC}"
docker-compose up -d

# Verificar se os serviços foram iniciados corretamente
if [ $? -eq 0 ]; then
    echo -e "${GREEN}=========================================${NC}"
    echo -e "${GREEN}   Sistema iniciado com sucesso!         ${NC}"
    echo -e "${GREEN}   Backend: http://localhost:8000        ${NC}"
    echo -e "${GREEN}   Frontend: http://localhost:3000       ${NC}"
    echo -e "${GREEN}   API Docs: http://localhost:8000/docs  ${NC}"
    echo -e "${GREEN}=========================================${NC}"
else
    echo -e "${RED}Falha ao iniciar os serviços. Verifique os logs com 'docker-compose logs'.${NC}"
    exit 1
fi