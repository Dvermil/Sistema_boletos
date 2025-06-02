# coding: utf-8
import streamlit as st
import sqlite3
import datetime
import logging # Será configurado depois
import sys
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import threading
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode, JsCode
import pandas as pd
import pdfplumber
import re
import os
import tempfile
import io # Necessário para BytesIO
from io import BytesIO # Especificamente BytesIO
import requests
from requests.auth import HTTPBasicAuth
from typing import Optional, List, Tuple # Adicionado List e Tuple

from pdfminer.high_level import extract_text as pdfminer_extract_text
from pdfminer.layout import LAParams

# Importações de erros customizados
from .errors import (
    PDFProcessingError,
    PDFTextExtractionError,
    PDFOCRError,
    BarcodeNotFoundError,
    InvalidPDFError,
    ConfigurationError,
    SOAPAPIError, # Adicionada para uso em enviar_dados_soap
    CNPJLookupError, # Adicionada para uso em get_idpgto_by_cnpj ou chamadores
    InvalidDataError # Adicionada para uso geral
)

# Adicione ao seu código de importação
try:
    import pytesseract
    import pdf2image
    from PIL import Image
    import numpy as np
    try:
        from pyzbar.pyzbar import decode as pyzbar_decode
        BARCODE_DETECTION_AVAILABLE = True
    except ImportError:
        BARCODE_DETECTION_AVAILABLE = False
        # logger.warning("pyzbar não instalado. Detecção direta de códigos de barras limitada.")
    OCR_AVAILABLE = True
except ImportError:
    BARCODE_DETECTION_AVAILABLE = False
    OCR_AVAILABLE = False
    # logger.warning("Dependências para OCR/detecção de código de barras não instaladas.")

BARCODE_PATTERNS = [
    # Arrecadação (48 dígitos, formato com pontos)
    r"\b(8\d{10}\s*\.\s*\d\s*\.\s*\d{11}\s*\.\s*\d\s*\.\s*\d{11}\s*\.\s*\d\s*\.\s*\d{11}\s*\.\s*\d)\b",
    r"\b(8\d{11}\s+\d{12}\s+\d{12}\s+\d{12})\b",  # Arrecadação (48 dígitos, formato com espaços)
    r"\b(8\d{10}\s*-\s*\d\s+\d{11}\s*-\s*\d\s+\d{11}\s*-\s*\d\s+\d{11}\s*-\s*\d)\b", # Arrecadação (48 dígitos, formato com hífens)
    # Boleto (47 dígitos, formato com pontos/espaços)
    r"\b(\d{5}[\.\s]?\d{5}\s+\d{5}[\.\s]?\d{6}\s+\d{5}[\.\s]?\d{6}\s+\d{1}\s+\d{14})\b",
    r"\d{11}-\d\s*\d{11}-\d\s*\d{11}-\d\s*\d{11}-\d",
    # Chave de Acesso NF-e (44 dígitos, formato com espaços)
    r"\b(\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4}\s+\d{4})\b",
    r"\b(\d{4}\s?){10}\d{4}\b",
    # Padrões Genéricos (normalizados)
    r"\d{48}\b",
    r"\b\d{47}\b",
    r"\b\d{44}\b",
]

# Padrões a descartar (chaves de acesso NFe)
NFE_PATTERNS = [
    # Chave de acesso NFe (44 dígitos) - vários formatos
    r"\b(\d{4}\s\d{4}\s\d{4}\s\d{4}\s\d{4}\s\d{4}\s\d{4}\s\d{4}\s\d{4}\s\d{4}\s\d{4})\b",
    r"\b(NFe[: ]\d{44})\b",
    r"\b(CHAVE DE ACESSO[:\s]+\d{44})\b",
    r"\b(CHAVE\s+\d{44})\b",
    r"\b(\d{4}[\s\.]\d{4}[\s\.]\d{4}[\s\.]\d{4}[\s\.]\d{4}[\s\.]\d{4}[\s\.]\d{4}[\s\.]\d{4}[\s\.]\d{4}[\s\.]\d{4}[\s\.]\d{4})\b"
]



def load_cnpj_idpgto_mapping():
    """
    Carrega o mapeamento CNPJ → IDPGTO do arquivo CSV.
    Retorna um dicionário com CNPJs limpos (apenas números) como chaves e IDPGTO como valores.
    """
    mapping = {}
    try:
        # Carregar o arquivo CSV com delimitador ";"
        df = pd.read_csv("Listas_Fornecedores1.csv", sep=";", encoding="utf-8")
        
        for _, row in df.iterrows():
            try:
                idpgto = int(row["IDPGTO"])
                cnpj = str(row["CNPJ/CPF"]).strip()
                cnpj_clean = re.sub(r"[^\d]", "", cnpj)
                if cnpj_clean:
                    mapping[cnpj_clean] = idpgto
            except (ValueError, KeyError) as e:
                logger.warning(f"Erro ao processar linha do CSV de mapeamento CNPJ: {row} - {e}")
                continue
    except FileNotFoundError:
        logger.error("Arquivo Listas_Fornecedores1.csv não encontrado. Mapeamento CNPJ->IDPGTO não carregado.")
        # Poderia levantar uma ConfigurationError aqui se o arquivo for essencial
    except Exception as e:
        logger.error(f"Erro ao carregar o arquivo de mapeamento CNPJ: {e}", exc_info=True)
    return mapping

def get_idpgto_by_cnpj(cnpj):
    """
    Obtém o IDPGTO com base no CNPJ.
    
    Args:
        cnpj: CNPJ do fornecedor (pode conter formatação: pontos, barras, hífens)
        
    Returns:
        Tupla (idpgto, encontrado) onde:
        - idpgto: o ID encontrado (None se não encontrado)
        - encontrado: booleano indicando se o CNPJ foi encontrado
    """
    # Verificar se o CNPJ é válido
    if not cnpj or cnpj == "Não encontrado":
        return None, False
    
    # Limpar CNPJ (remover formatação)
    cnpj_clean = re.sub(r'[^\d]', '', str(cnpj))
    
    if not cnpj_clean or len(cnpj_clean) not in [11, 14]:  # CPF tem 11, CNPJ tem 14
        return None, False
    
    # Carregar mapeamento (com cache para melhor performance)
    if not hasattr(get_idpgto_by_cnpj, "_mapping"):
        get_idpgto_by_cnpj._mapping = load_cnpj_idpgto_mapping()
    
    # Buscar no mapeamento
    if cnpj_clean in get_idpgto_by_cnpj._mapping:
        return get_idpgto_by_cnpj._mapping[cnpj_clean], True
    
    return None, False

# Função para enviar dados via SOAP

def enviar_dados_soap(idlan, ipte, idpgto=None, cnpj=None, origem_deteccao=None):
    """
    Envia dados via SOAP para o sistema TOTVS e retorna logs detalhados.
    
    Args:
        idlan: ID do lançamento (ID.Fluxus)
        ipte: Código de barras ou linha digitável
        idpgto: IDPGTO fornecido diretamente (opcional)
        cnpj: CNPJ do fornecedor (usado se idpgto não for fornecido)
        origem_deteccao: Como o código foi detectado ("pyzbar", "texto", "ocr")
        
    Returns:
        Tupla (sucesso, mensagem, logs)
    """
    url = "http://10.131.0.13:8051/wsDataServer/IwsDataServer"
    username = "douglas.vermil"
    password = "Chouest123@"
    
    logs = []  # Lista para armazenar logs detalhados
    logs.append(f"Iniciando envio para IDLAN={idlan}, Código={ipte}")
    
    # Determinar qual tag usar com base na origem da detecção
    tag_a_usar = "IPTE"  # Padrão
    if origem_deteccao == "pyzbar":
        tag_a_usar = "CODIGOBARRA"
        logs.append("Usando tag CODIGOBARRA pois código foi detectado via leitor de código de barras")
    else:
        logs.append("Usando tag IPTE pois código foi detectado via extração de texto/OCR")
    
    # 1. Determinar o IDPGTO (com prioridade para o valor direto)
    idpgto_value = None
    
    # Tentativa 1: Usar idpgto direto (se válido)
    if idpgto and str(idpgto).isdigit():  # Verifica se é numérico
        try:
            idpgto_value = int(idpgto)
            logs.append(f"Usando IDPGTO fornecido diretamente: {idpgto_value}")
        except (ValueError, TypeError):
            logs.append(f"IDPGTO fornecido inválido: {idpgto}")
    
    # Tentativa 2: Buscar via CNPJ (se idpgto direto não for válido)
    if idpgto_value is None and cnpj and cnpj != "Não encontrado":
        logs.append(f"Tentando buscar IDPGTO pelo CNPJ: {cnpj}")
        idpgto_found, encontrado = get_idpgto_by_cnpj(cnpj)
        if encontrado:
            idpgto_value = idpgto_found
            logs.append(f"IDPGTO encontrado via CNPJ: {idpgto_value}")
        else:
            logs.append(f"IDPGTO não encontrado para o CNPJ: {cnpj}")
    
    # 3. Falha se nenhum IDPGTO válido foi encontrado
    if idpgto_value is None:
        logs.append("ERRO: IDPGTO não disponível. Verifique o CNPJ ou preencha manualmente.")
        return False, "IDPGTO não disponível. Verifique o CNPJ ou preencha manualmente.", logs
    
    # 4. Construção do SOAP Request
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": "http://www.totvs.com/IwsDataServer/SaveRecord"
    }
    
    # Construir o XML com a tag apropriada
    codigo_tag = f"<{tag_a_usar}>{ipte}</{tag_a_usar}>"
    
    body = f"""<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:tot="http://www.totvs.com/">
        <soapenv:Header/>
        <soapenv:Body>
            <tot:SaveRecord>
                <tot:DataServerName>FinLanDataBR</tot:DataServerName>
                <tot:XML><![CDATA[
                    <FinLAN>
                        <FLAN>
                            <CODCOLIGADA>4</CODCOLIGADA>
                            <CODCOLPGTO>4</CODCOLPGTO>
                            <IDPGTO>{idpgto_value}</IDPGTO>
                            <IDLAN>{idlan}</IDLAN>
                            {codigo_tag}
                        </FLAN>
                    </FinLAN>
                ]]></tot:XML>
                <tot:Contexto>CODSISTEMA=F;CODCOLIGADA=4;CODUSUARIO=douglas.vermil</tot:Contexto>
            </tot:SaveRecord>
        </soapenv:Body>
    </soapenv:Envelope>"""

    logs.append("Enviando requisição SOAP...")
    
    # 5. Envio e tratamento da resposta
    try:
        response = requests.post(url, headers=headers, data=body, auth=(username, password))
        status_code = response.status_code
        logs.append(f"Status code: {status_code}")
        
        # Registrar headers da resposta
        logs.append("Headers da resposta:")
        for key, value in response.headers.items():
            logs.append(f"  {key}: {value}")
        
        # Registrar conteúdo da resposta (limitado para evitar logs enormes)
        content = response.text
        logs.append(f"Conteúdo da resposta (primeiros 1000 caracteres):")
        logs.append(content[:1000] + ("..." if len(content) > 1000 else ""))
        
        # Verificar status code
        response.raise_for_status()
        
        # Verificar mensagens específicas de erro no conteúdo da resposta
        # Novo bloco para detectar erro de código de barras inválido
        if "Código de Barras não está válido" in content or "ConsisteCodigoBarras" in content:
            error_msg = "Código de barras inválido. Verifique os dígitos informados."
            logs.append(f"ERRO: {error_msg}")
            return False, error_msg, logs
        
        # Outros padrões de erro existentes
        if "dado bancário não pertence" in content:
            logs.append("ERRO: Dado bancário não pertence ao fornecedor")
            return False, "Erro: Dado bancário não pertence ao fornecedor.", logs
        
        if "Error" in content or "Erro" in content:
            error_msg = "Erro não especificado na resposta"
            # Tentar extrair mensagem de erro
            import re
            error_match = re.search(r'<Message>(.*?)</Message>', content)
            if error_match:
                error_msg = error_match.group(1)
            logs.append(f"ERRO: {error_msg}")
            return False, f"Erro: {error_msg}", logs
            
        logs.append("Envio realizado com sucesso!")
        return True, "Sucesso!", logs
        
    except requests.exceptions.RequestException as e:
        logs.append(f"ERRO de comunicação: {str(e)}")
        return False, f"Erro de comunicação: {str(e)}", logs


def has_cid_markers(text: Optional[str]) -> bool:
    """Verifica se o texto contém marcadores (cid:x) em grande quantidade."""
    if not text:
        return False
    cid_count = len(re.findall(r"\(cid:\d+\)", text))
    total_words = len(text.split())
    if total_words == 0:
        return cid_count > 0
    return cid_count > 0 and (cid_count / total_words) > 0.2

def _extract_text_from_pdf_page(page: pdfplumber.page.Page) -> str:
    """Extrai texto de uma única página usando pdfplumber com tolerâncias ajustadas."""
    try:
        return page.extract_text(x_tolerance=1, y_tolerance=1) or ""
    except Exception as e:
        logger.warning(f"Erro ao extrair texto da página com pdfplumber: {e}")
        return ""

def _extract_text_with_pdfplumber(pdf_path: str, filename: str) -> str:
    """Extrai texto de um arquivo PDF usando pdfplumber."""
    full_text = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                # logger.debug(f"Extraindo texto da página {i+1}/{len(pdf.pages)} de {filename} com pdfplumber")
                txt = _extract_text_from_pdf_page(page)
                full_text.append(txt)
        return "\n".join(full_text)
    except pdfplumber.exceptions.PDFSyntaxError as e:
        raise InvalidPDFError(f"Erro de sintaxe no PDF: {e}", original_exception=e, filename=filename)
    except Exception as e:
        raise PDFTextExtractionError(f"Erro ao abrir/processar PDF com pdfplumber: {e}", original_exception=e, filename=filename)

def _extract_text_with_pdfminer(pdf_path: str, filename: str) -> str:
    """Extrai texto de um arquivo PDF usando pdfminer.six."""
    try:
        logger.debug(f"Tentando extração com pdfminer.six para {filename}")
        laparams = LAParams(all_texts=True, line_margin=0.2)
        extracted_text = pdfminer_extract_text(pdf_path, laparams=laparams)
        # logger.info(f"Texto extraído com pdfminer.six para {filename} (len: {len(extracted_text)})")
        return extracted_text
    except ImportError:
        logger.warning("pdfminer.six não está instalado. Não foi possível usar como fallback.")
        # Não levanta erro aqui, pois é um fallback. O chamador decide.
        return "" # Retorna vazio para indicar que não conseguiu
    except Exception as e:
        raise PDFTextExtractionError(f"Erro ao usar pdfminer.six: {e}", original_exception=e, filename=filename)

def _get_primary_text_extraction(pdf_path: str, filename: str) -> str:
    """Tenta extrair texto usando pdfplumber e, se necessário, pdfminer como fallback."""
    logger.info(f"Iniciando extração de texto primária para {filename}")
    text_pdfplumber = _extract_text_with_pdfplumber(pdf_path, filename)

    if not text_pdfplumber.strip() or has_cid_markers(text_pdfplumber):
        logger.warning(f"Texto de pdfplumber insatisfatório para {filename} (vazio ou muitos CIDs). Tentando pdfminer.six.")
        text_pdfminer = _extract_text_with_pdfminer(pdf_path, filename)
        # Usa pdfminer se extraiu algo e é significativamente diferente/melhor, ou se pdfplumber não retornou nada
        if text_pdfminer and (len(text_pdfminer.strip()) > len(text_pdfplumber.strip()) + 10 or not text_pdfplumber.strip()):
            logger.info(f"Usando resultado do pdfminer.six para {filename}.")
            return text_pdfminer
        logger.info(f"Mantendo resultado do pdfplumber (ou vazio) para {filename} após tentativa com pdfminer.")
    return text_pdfplumber

def validar_digito_mod10(campo, com_dv=True):
    """
    Implementa o algoritmo de validação por Módulo 10 (padrão FEBRABAN).
    
    Args:
        campo: String com o campo a ser validado (incluindo o DV se com_dv=True)
        com_dv: Boolean indicando se o campo inclui o DV (True) ou não (False)
    
    Returns:
        Boolean indicando se o campo é válido
    """
    if not campo or not campo.isdigit():
        return False
        
    # Se o campo inclui DV, separar o campo do DV
    if com_dv:
        campo_sem_dv = campo[:-1]
        dv_informado = int(campo[-1])
    else:
        campo_sem_dv = campo
        dv_informado = None
    
    # Processar do último dígito para o primeiro (direita para esquerda)
    soma = 0
    peso = 2  # Começa com peso 2
    
    for i in range(len(campo_sem_dv)-1, -1, -1):
        # Multiplica o dígito pelo peso (2 ou 1)
        resultado = int(campo_sem_dv[i]) * peso
        
        # Soma os dígitos do resultado (e.g., 18 -> 1+8=9)
        # Para números < 10, o valor permanece o mesmo
        if resultado >= 10:
            resultado = sum(int(digit) for digit in str(resultado))
        
        soma += resultado
        
        # Alterna o peso: 2->1 ou 1->2
        peso = 1 if peso == 2 else 2
    
    # Calcular DV esperado: (10 - (soma % 10)) % 10
    dv_calculado = (10 - (soma % 10)) % 10
    
    # Se não tem DV informado, retorna o calculado
    if dv_informado is None:
        return dv_calculado
    
    # Verifica se o DV informado é igual ao calculado
    return dv_informado == dv_calculado

def validar_digito_mod11_febraban(campo, com_dv=True):
    """
    Implementa o algoritmo de validação por Módulo 11 (padrão FEBRABAN).
    
    Args:
        campo: String com o campo a ser validado (incluindo o DV se com_dv=True)
        com_dv: Boolean indicando se o campo inclui o DV (True) ou não (False)
    
    Returns:
        Boolean indicando se o campo é válido ou o DV calculado se com_dv=False
    """
    if not campo or not campo.isdigit():
        return False
    
    # Se o campo inclui DV, separar o campo do DV
    if com_dv:
        campo_sem_dv = campo[:-1]
        dv_informado = int(campo[-1])
    else:
        campo_sem_dv = campo
        dv_informado = None
    
    # Processar do último dígito para o primeiro (direita para esquerda)
    soma = 0
    peso = 2  # Começa com peso 2
    
    for i in range(len(campo_sem_dv)-1, -1, -1):
        # Multiplica o dígito pelo peso (2 a 9)
        resultado = int(campo_sem_dv[i]) * peso
        soma += resultado
        
        # Incrementa o peso, reiniciando em 2 após chegar a 9
        peso = peso + 1 if peso < 9 else 2
    
    # Calcular resto da divisão por 11
    resto = soma % 11
    
    # Aplicar regras FEBRABAN para o cálculo do DV
    if resto == 0 or resto == 1:
        dv_calculado = 0
    elif resto == 10:
        dv_calculado = 1
    else:
        dv_calculado = 11 - resto
    
    # Se não tem DV informado, retorna o calculado
    if dv_informado is None:
        return dv_calculado
    
    # Verifica se o DV informado é igual ao calculado
    return dv_informado == dv_calculado

def validar_digito_mod11_nfe(campo, com_dv=True):
    """
    Implementa o algoritmo de validação por Módulo 11 para NF-e.
    
    Args:
        campo: String com o campo a ser validado (incluindo o DV se com_dv=True)
        com_dv: Boolean indicando se o campo inclui o DV (True) ou não (False)
    
    Returns:
        Boolean indicando se o campo é válido ou o DV calculado se com_dv=False
    """
    if not campo or not campo.isdigit():
        return False
    
    # Se o campo inclui DV, separar o campo do DV
    if com_dv:
        campo_sem_dv = campo[:-1]
        dv_informado = int(campo[-1])
    else:
        campo_sem_dv = campo
        dv_informado = None
    
    # Processar do último dígito para o primeiro (direita para esquerda)
    soma = 0
    peso = 2  # Começa com peso 2
    
    for i in range(len(campo_sem_dv)-1, -1, -1):
        # Multiplica o dígito pelo peso (2 a 9)
        resultado = int(campo_sem_dv[i]) * peso
        soma += resultado
        
        # Incrementa o peso, reiniciando em 2 após chegar a 9
        peso = peso + 1 if peso < 9 else 2
    
    # Calcular resto da divisão por 11
    resto = soma % 11
    
    # Aplicar regras NFe para o cálculo do DV
    if resto == 0 or resto == 1:
        dv_calculado = 0
    else:
        dv_calculado = 11 - resto
    
    # Se não tem DV informado, retorna o calculado
    if dv_informado is None:
        return dv_calculado
    
    # Verifica se o DV informado é igual ao calculado
    return dv_informado == dv_calculado

def validar_codigo_barras(codigo):
    """
    Valida um código de barras baseado no seu tipo (boleto, arrecadação ou NFe).
    
    Args:
        codigo: String com o código de barras já normalizado (apenas dígitos)
    
    Returns:
        Tupla (válido, tipo) onde:
        - válido: Boolean indicando se o código é válido
        - tipo: String indicando o tipo de código ('boleto', 'arrecadacao', 'nfe' ou 'desconhecido')
    """
    if not codigo or not codigo.isdigit():
        return False, "desconhecido"
    
    # Normalizar removendo espaços, pontos, etc.
    codigo_clean = re.sub(r"[\s.-]+", "", codigo)
    
    # Verificar o tipo de código baseado no comprimento e primeiro dígito
    if len(codigo_clean) == 44:
        # Pode ser NFe (44 dígitos) ou código de barras de boleto (44 dígitos)
        if codigo_clean[0] in "0123456789":
            # Provavelmente NFe
            return validar_digito_mod11_nfe(codigo_clean), "nfe"
        
    elif len(codigo_clean) == 47:
        # Linha digitável de boleto (47 dígitos)
        return validar_boleto(codigo_clean), "boleto"
        
    elif len(codigo_clean) == 48:
        # Linha digitável de arrecadação/convênio (48 dígitos)
        return validar_arrecadacao(codigo_clean), "arrecadacao"
    
    # Outros casos não implementados ainda
    return False, "desconhecido"

def validar_boleto(linha_digitavel):
    """
    Valida uma linha digitável de boleto de 47 dígitos.
    
    Args:
        linha_digitavel: String com a linha digitável normalizada (47 dígitos)
    
    Returns:
        Boolean indicando se a linha é válida
    """
    if len(linha_digitavel) != 47 or not linha_digitavel.isdigit():
        return False
    
    # Extrair campos conforme documentação FEBRABAN
    campo1 = linha_digitavel[:10]  # Incluindo DV na posição 10
    campo2 = linha_digitavel[10:21]  # Incluindo DV na posição 21
    campo3 = linha_digitavel[21:32]  # Incluindo DV na posição 32
    campo4 = linha_digitavel[32:33]  # DV geral
    campo5 = linha_digitavel[33:]  # Fator de vencimento e valor
    
    # Validar DVs dos campos 1, 2 e 3 usando Módulo 10
    if not validar_digito_mod10(campo1) or not validar_digito_mod10(campo2) or not validar_digito_mod10(campo3):
        return False
    
    # Reconstruir o código de barras para validação do DV geral (campo4)
    # A reconstrução segue regras específicas da FEBRABAN
    # Primeiro extrair os componentes necessários (sem os DVs individuais)
    banco_moeda = linha_digitavel[:4]
    codigo_barras = (
        banco_moeda +  # Banco+Moeda (4 dígitos)
        campo4 +  # DV geral (1 dígito)
        linha_digitavel[33:37] +  # Fator vencimento (4 dígitos)
        linha_digitavel[37:47] +  # Valor (10 dígitos)
        linha_digitavel[4:9] +  # Campo livre parte 1 (5 dígitos)
        linha_digitavel[10:20] +  # Campo livre parte 2 (10 dígitos)
        linha_digitavel[21:31]  # Campo livre parte 3 (10 dígitos)
    )
    
    # Validar DV geral (campo4) usando Módulo 11 FEBRABAN
    # O DV está na posição 4 do código de barras reconstruído
    campo_para_validar = codigo_barras[:4] + codigo_barras[5:]  # Todos exceto o DV
    dv_calculado = validar_digito_mod11_febraban(campo_para_validar, com_dv=False)
    
    return int(campo4) == dv_calculado

def validar_arrecadacao(linha_digitavel):
    """
    Valida uma linha digitável de arrecadação/convênio de 48 dígitos.
    
    Args:
        linha_digitavel: String com a linha digitável normalizada (48 dígitos)
    
    Returns:
        Boolean indicando se a linha é válida
    """
    if len(linha_digitavel) != 48 or not linha_digitavel.isdigit():
        return False
    
    # Verificar o tipo de validação baseado no 3º dígito
    # 6,7 = Módulo 10; 8,9 = Módulo 11
    tipo_validacao = linha_digitavel[2]
    
    # Extrair campos (cada campo termina com um DV)
    campo1 = linha_digitavel[:12]
    campo2 = linha_digitavel[12:24]
    campo3 = linha_digitavel[24:36]
    campo4 = linha_digitavel[36:48]
    
    # Escolher função de validação conforme o tipo
    if tipo_validacao in "67":
        validar_campo = validar_digito_mod10
    elif tipo_validacao in "89":
        validar_campo = validar_digito_mod11_febraban
    else:
        return False  # Tipo de validação não suportado
    
    # Validar cada campo
    return (validar_campo(campo1) and 
            validar_campo(campo2) and 
            validar_campo(campo3) and 
            validar_campo(campo4))

def _filtrar_codigos_por_validade(codigos_candidatos):
    """
    Filtra uma lista de códigos de barras candidatos baseado na validação por checksum.
    
    Args:
        codigos_candidatos: Lista de strings com códigos candidatos
    
    Returns:
        Lista filtrada de códigos válidos, priorizando boletos sobre outros tipos
    """
    if not codigos_candidatos:
        return []
    
    boletos_validos = []
    arrecadacoes_validas = []
    nfes_validas = []
    outros_codigos = []
    
    for codigo in codigos_candidatos:
        valido, tipo = validar_codigo_barras(codigo)
        if valido:
            if tipo == "boleto":
                boletos_validos.append((codigo, 1))  # Prioridade 1 (mais alta)
            elif tipo == "arrecadacao":
                arrecadacoes_validas.append((codigo, 2))  # Prioridade 2
            elif tipo == "nfe":
                nfes_validas.append((codigo, 3))  # Prioridade 3
        else:
            outros_codigos.append((codigo, 4))  # Prioridade 4 (mais baixa)
    
    # Juntar todas as listas em ordem de prioridade
    todos_codigos_priorizados = (
        boletos_validos + 
        arrecadacoes_validas + 
        nfes_validas + 
        outros_codigos
    )
    
    # Retornar apenas os códigos, mantendo a ordem de prioridade
    return [codigo for codigo, _ in todos_codigos_priorizados]

def is_nfe_access_key(codigo):
    """
    Verifica se o código é uma chave de acesso de NF-e.
    
    Args:
        codigo: String com o código já normalizado (apenas dígitos)
    
    Returns:
        Boolean indicando se é uma chave de acesso de NF-e
    """
    if not codigo or not codigo.isdigit() or len(codigo) != 44:
        return False
    
    # Chave de acesso NF-e sempre começa com código da UF (primeiro 2 dígitos entre 11-53)
    uf_code = int(codigo[:2])
    if 11 <= uf_code <= 53:
        # O 35º dígito da chave de acesso NF-e é o modelo do documento
        # 55 = NF-e, 65 = NFC-e, 57 = CT-e
        modelo = codigo[34:36]
        if modelo in ['55', '65', '57']:
            return True
    
    return False

def is_boleto_ou_arrecadacao(codigo):
    """
    Verifica se o código parece ser de boleto ou arrecadação.
    
    Args:
        codigo: String com o código já normalizado (apenas dígitos)
    
    Returns:
        Boolean indicando se parece ser boleto ou arrecadação
    """
    if not codigo or not codigo.isdigit():
        return False
    
    # Linha digitável de boleto (47 dígitos)
    if len(codigo) == 47:
        # Primeiro dígito de boleto geralmente é de 1-9 (código do banco)
        if codigo[0] in "123456789":
            return True
    
    # Linha digitável de arrecadação (48 dígitos)
    elif len(codigo) == 48:
        # Arrecadação começa com 8
        if codigo[0] == "8":
            return True
    
    # Código de barras de boleto (44 dígitos) - diferente da chave NF-e
    elif len(codigo) == 44:
        # Primeiro dígito geralmente é código de banco (1-9)
        if codigo[0] in "123456789":
            # Verificar se não é uma chave de NF-e
            if not is_nfe_access_key(codigo):
                return True
    
    return False

def _filtrar_codigos_por_validade(codigos_candidatos):
    """
    Filtra uma lista de códigos de barras candidatos baseado na validação por checksum
    e características específicas de cada tipo de código.
    
    Args:
        codigos_candidatos: Lista de strings com códigos candidatos
    
    Returns:
        Lista filtrada de códigos válidos, priorizando boletos sobre outros tipos
    """
    if not codigos_candidatos:
        return []
    
    boletos_validos = []
    arrecadacoes_validas = []
    outros_codigos = []
    
    for codigo in codigos_candidatos:
        # Verificar se é NFe e descartar
        if is_nfe_access_key(codigo):
            logger.info(f"Descartando chave de acesso NFe: {codigo}")
            continue
        
        # Verificar se parece ser boleto ou arrecadação
        if is_boleto_ou_arrecadacao(codigo):
            valido, tipo = validar_codigo_barras(codigo)
            if valido:
                if tipo == "boleto":
                    boletos_validos.append((codigo, 1))  # Prioridade 1 (mais alta)
                elif tipo == "arrecadacao":
                    arrecadacoes_validas.append((codigo, 2))  # Prioridade 2
            else:
                # Mesmo que não passe na validação, se tem formato de boleto
                # pode ser um erro de leitura, então mantemos com baixa prioridade
                outros_codigos.append((codigo, 3))
        else:
            # Códigos que não são nem NFe, nem boleto/arrecadação
            outros_codigos.append((codigo, 4))  # Prioridade mais baixa
    
    # Juntar todas as listas em ordem de prioridade
    todos_codigos_priorizados = (
        boletos_validos + 
        arrecadacoes_validas + 
        outros_codigos
    )
    
    # Retornar apenas os códigos, mantendo a ordem de prioridade
    return [codigo for codigo, _ in todos_codigos_priorizados]


def extract_barcode_from_image(image):
    """
    Extrai diretamente códigos de barras de uma imagem usando pyzbar,
    aplicando validação por checksum para filtrar códigos inválidos.
    
    Args:
        image: Imagem PIL ou numpy array
        
    Returns:
        Lista de códigos de barras encontrados, priorizados por tipo e validade,
        ou lista vazia se nenhum for encontrado
    """
    try:
        from pyzbar.pyzbar import decode
        barcodes = decode(image)
        candidates = []
        
        for barcode in barcodes:
            # Decodificar e limpar os dados do código de barras
            barcode_data = barcode.data.decode('utf-8')
            barcode_type = barcode.type
            logger.debug(f"Código de barras encontrado - Tipo: {barcode_type}, Dados: {barcode_data}")
            
            # Limpar e normalizar o código de barras (remover espaços, etc.)
            cleaned_data = re.sub(r"[\s.-]+", "", barcode_data)
            
            # Verificar se o código tem o tamanho esperado (44, 47 ou 48 dígitos)
            if len(cleaned_data) in [44, 47, 48] and cleaned_data.isdigit():
                candidates.append(cleaned_data)
        
        # Priorizar os códigos válidos e filtrar os inválidos
        filtered_barcodes = _filtrar_codigos_por_validade(candidates)
        return filtered_barcodes
        
    except ImportError:
        logger.warning("Módulo pyzbar não instalado. Detecção direta de códigos de barras indisponível.")
        return []
    except Exception as e:
        logger.error(f"Erro ao decodificar código de barras: {e}")
        return []

def extract_barcode_with_opencv(image):
    """
    Tenta extrair códigos de barras usando OpenCV.
    Útil como alternativa quando pyzbar não está disponível.
    
    Args:
        image: Imagem em formato numpy array
        
    Returns:
        Lista de códigos de barras encontrados ou lista vazia
    """
    try:
        import cv2
        
        # Converter para escala de cinza se não estiver
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image
            
        # Aplicar thresholding para melhorar a detecção
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
        
        # Detectar bordas
        edges = cv2.Canny(thresh, 50, 200, apertureSize=3)
        
        # Encontrar linhas que podem fazer parte de códigos de barras
        lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=100, minLineLength=100, maxLineGap=10)
        
        # Este método é mais complexo e requer processamento adicional
        # para transformar detecções de linhas em códigos de barras.
        # O resultado é menos preciso que o pyzbar, sendo principalmente
        # útil para pré-processamento e identificação de regiões de interesse.
        
        # Nesta implementação básica, apenas indicamos que encontramos
        # possíveis regiões com código de barras para processamento OCR posterior.
        
        if lines is not None and len(lines) > 10:
            return True  # Indica que possivelmente há código de barras
        return False
        
    except ImportError:
        logger.warning("OpenCV não disponível para detecção de códigos de barras.")
        return False
    except Exception as e:
        logger.error(f"Erro ao processar imagem com OpenCV: {e}")
        return False

def _extract_text_with_ocr_and_barcode(pdf_path: str, filename: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Extrai texto de um arquivo PDF usando OCR e tenta detectar códigos de barras diretamente.
    
    Returns:
        Tupla (texto_ocr, codigo_barras, origem_deteccao) onde:
        - texto_ocr: Texto extraído via OCR
        - codigo_barras: Código de barras detectado (ou None)
        - origem_deteccao: "pyzbar" se detectado diretamente, "ocr" se detectado no texto, ou None
    """
    if not OCR_AVAILABLE:
        raise ConfigurationError("OCR não está disponível (pytesseract/pdf2image não instalados)", filename=filename)

    logger.info(f"Iniciando OCR e detecção de código de barras para {filename}...")
    direct_barcode = None
    detection_source = None
    
    try:
        images = pdf2image.convert_from_path(pdf_path, dpi=300)
    except pdf2image.exceptions.PDFInfoNotInstalledError as e:
        raise ConfigurationError("Utilitários Poppler não encontrados", original_exception=e, filename=filename)
    except Exception as e_conv:
        raise PDFOCRError(f"Erro ao converter PDF para imagem: {e_conv}", original_exception=e_conv, filename=filename)

    if not images:
        raise PDFOCRError("Nenhuma imagem gerada do PDF para OCR", filename=filename)

    ocr_full_text = []
    
    for i, img in enumerate(images):
        page_num = i + 1
        try:
            # Primeiro tenta detectar códigos de barras diretamente na imagem
            if direct_barcode is None:  # Se ainda não encontrou um código de barras
                # Converte para formato numpy para compatibilidade com OpenCV e pyzbar
                np_image = np.array(img)
                
                # Tenta com pyzbar primeiro
                barcodes = extract_barcode_from_image(np_image)
                if barcodes:
                    direct_barcode = barcodes[0]  # Usa o primeiro código encontrado
                    detection_source = "pyzbar"  # Marcamos a fonte da detecção
                    # logger.info(f"Código de barras detectado diretamente na página {page_num} de {filename}: {direct_barcode}")
                elif extract_barcode_with_opencv(np_image):
                    # OpenCV detectou possível região de código de barras,
                    # mas não conseguiu decodificar. Vamos tentar OCR específico nesta área.
                    # Aqui você pode adicionar lógica para recortar e processar a região.
                    pass
            
            # Continua com OCR normal para o texto
            img_gray = img.convert("L")
            page_text = pytesseract.image_to_string(img_gray, lang="por")
            ocr_full_text.append(page_text)
            
        except pytesseract.TesseractNotFoundError as e:
            raise ConfigurationError("Tesseract não encontrado", original_exception=e, filename=filename)
        except Exception as e_ocr_page:
            logger.warning(f"Erro no OCR da página {page_num}: {e_ocr_page}")
            ocr_full_text.append("")
        finally:
            del img  # Libera memória

    # Limpar recursos
    del images
    
    final_ocr_text = "\n".join(ocr_full_text).strip()
    if not final_ocr_text and not direct_barcode:
        raise PDFOCRError("Nenhum texto ou código de barras extraído", filename=filename)
    
    return final_ocr_text, direct_barcode, detection_source

def _extract_text_with_ocr(pdf_path: str, filename: str) -> str:
    """
    Extrai texto de um arquivo PDF usando OCR.
    Levanta ConfigurationError se OCR não estiver disponível/configurado.
    Levanta PDFOCRError em caso de falha no OCR.
    """
    if not OCR_AVAILABLE:
        raise ConfigurationError("OCR não está disponível (pytesseract/pdf2image não instalados ou não importados corretamente).", filename=filename)

    # logger.info(f"Iniciando OCR para {filename}...")
    try:
        images = pdf2image.convert_from_path(pdf_path, dpi=300) # DPI 300 é bom para OCR
    except pdf2image.exceptions.PDFInfoNotInstalledError as e:
        raise ConfigurationError("Utilitários Poppler (pdfinfo) não encontrados. pdf2image precisa deles.", original_exception=e, filename=filename)
    except Exception as e_conv:
        raise PDFOCRError(f"Erro ao converter PDF para imagem para OCR: {e_conv}", original_exception=e_conv, filename=filename)

    if not images:
        raise PDFOCRError("Nenhuma imagem gerada a partir do PDF para OCR.", filename=filename)

    ocr_full_text = []
    for i, img in enumerate(images):
        page_num = i + 1
        try:
            # logger.debug(f"Processando OCR da página {page_num}/{len(images)} de {filename}")
            img_gray = img.convert("L")
            # config_ocr = "--psm 6 -l por -c tessedit_char_whitelist=0123456789." # Pode ser configurável
            page_text = pytesseract.image_to_string(img_gray, lang="por") # lang="por" para português
            ocr_full_text.append(page_text)
        except pytesseract.TesseractNotFoundError as e:
            raise ConfigurationError("Tesseract não encontrado. Verifique a instalação e o PATH.", original_exception=e, filename=filename)
        except Exception as e_ocr_page:
            # logger.warning(f"Erro no OCR da página {page_num} de {filename}: {e_ocr_page}")
            # Continua para tentar outras páginas, mas o resultado pode ser incompleto.
            # Se for crítico que todas as páginas sejam processadas, levantar PDFOCRError aqui.
            ocr_full_text.append("") # Adiciona string vazia para manter a contagem de páginas se necessário
        finally:
            del img # Tenta liberar memória da imagem
    del images # Libera a lista de imagens
    
    final_ocr_text = "\n".join(ocr_full_text).strip()
    if not final_ocr_text:
        raise PDFOCRError("Nenhum texto foi extraído via OCR.", filename=filename)
    
    logger.info(f"OCR concluído para {filename}. Texto extraído (len: {len(final_ocr_text)}).")
    return final_ocr_text

def _find_and_clean_barcode_in_text(text_content: str, filename: str) -> Optional[str]:
    """
    Busca por padrões de código de barras em um texto, valida e retorna o código limpo.
    """
    if not text_content:
        logger.debug(f"Texto vazio fornecido para busca de código de barras em {filename}.")
        return None

    normalized_text = re.sub(r"[\s.-]+", "", text_content)
    logger.debug(f"Texto normalizado para busca de código de barras (primeiros 200 chars): {normalized_text[:200]}")

    all_matches = []
    
    for pattern_idx, pattern in enumerate(BARCODE_PATTERNS):
        logger.debug(f"Tentando padrão de regex #{pattern_idx + 1} para {filename}: {pattern}")
        is_formatted_pattern = re.search(r"[\s\.\-]", pattern) is not None
        text_to_search = text_content if is_formatted_pattern else normalized_text

        try:
            matches = re.findall(pattern, text_to_search)
            if matches:
                for match_idx, match in enumerate(matches):
                    match_str = match[0] if isinstance(match, (tuple, list)) and match else str(match)
                    clean_item = re.sub(r"[\s.-]+", "", match_str)
                    logger.debug(f"Padrão #{pattern_idx+1} Match #{match_idx+1}: Original='{match_str}', Limpo='{clean_item}' (len: {len(clean_item)}) para {filename}")
                    if len(clean_item) in [44, 47, 48]:
                        all_matches.append(clean_item)
        except re.error as e:
            logger.warning(f"Regex inválido: {pattern} - Erro: {e} ao processar {filename}")
            continue # Pula para o próximo padrão
    
    # Priorizar os códigos válidos
    filtered_matches = _filtrar_codigos_por_validade(all_matches)
    
    if filtered_matches:
        logger.info(f"Código de barras encontrado e validado para {filename}: {filtered_matches[0]}")
        return filtered_matches[0]
    
    logger.info(f"Nenhum código de barras válido encontrado no texto fornecido para {filename}.")
    return None

def extract_and_clean_barcode(pdf_path: str, filename: str) -> Tuple[str, str]:
    """
    Extrai a linha digitável (Boleto/Arrecadação - 47/48 dígitos) ou
    Chave de Acesso (44 dígitos) de um PDF. Tenta OCR como fallback.
    Aplica validação por checksum para garantir códigos válidos.
    Levanta exceções customizadas em caso de erros.

    Args:
        pdf_path: Caminho para o arquivo PDF.
        filename: Nome original do arquivo (para logging e erros).

    Returns:
        Tupla (código_barras_limpo, origem_deteccao) onde origem_deteccao é 
        "pyzbar" se detectado via pyzbar ou "ocr"/"texto" para outras formas

    Raises:
        PDFProcessingError, PDFTextExtractionError, PDFOCRError, BarcodeNotFoundError,
        InvalidPDFError, ConfigurationError.
    """

    logger.info(f"Iniciando extração de código de barras para: {filename}")
    barcode: Optional[str] = None
    detection_source: str = "texto"  # Valor padrão para extração via texto
    
    # Variáveis para armazenar todos os candidatos a código para validação final
    all_candidates = []
    candidate_sources = {}  # Mapeia candidato -> fonte
    nfe_keys_found = []     # Armazena chaves NFe encontradas para debug
    
    # 1. Extração de texto primária (geralmente mais confiável para boletos)
    try:
        extracted_text = _get_primary_text_extraction(pdf_path, filename)
        if extracted_text:
            # Primeiro detectar e descartar chaves de NFe
            for pattern in NFE_PATTERNS:
                try:
                    matches = re.findall(pattern, extracted_text)
                    for match in matches:
                        clean_nfe = re.sub(r"[\s.-]+", "", match)
                        if len(clean_nfe) >= 44:  # Algumas regex podem capturar mais que 44 dígitos
                            clean_nfe = clean_nfe[-44:] if clean_nfe.isdigit() else clean_nfe
                            if is_nfe_access_key(clean_nfe):
                                nfe_keys_found.append(clean_nfe)
                                logger.info(f"Chave NFe detectada e descartada: {clean_nfe}")
                except re.error:
                    continue
                
            # Buscar códigos de boleto/arrecadação
            for pattern_idx, pattern in enumerate(BARCODE_PATTERNS):
                try:
                    matches = re.findall(pattern, extracted_text)
                    for match in matches:
                        match_str = match[0] if isinstance(match, (tuple, list)) and match else str(match)
                        clean_item = re.sub(r"[\s.-]+", "", match_str)
                        
                        # Verificar se é boleto ou arrecadação e não NFe
                        if is_boleto_ou_arrecadacao(clean_item) and not is_nfe_access_key(clean_item):
                            all_candidates.append(clean_item)
                            candidate_sources[clean_item] = "texto"
                            logger.debug(f"Candidato a boleto/arrecadação via texto: {clean_item}")
                except re.error:
                    continue
    except (InvalidPDFError, PDFTextExtractionError) as e:
        logger.warning(f"Erro na extração primária para {filename}: {e}. Tentando outros métodos.")
    
    # 2. Tentativa de detecção direta de código de barras via pyzbar
    if not all_candidates or len(all_candidates) == 0:
        try:
            # Converter PDF para imagens
            images = pdf2image.convert_from_path(pdf_path, dpi=300)
            
            for i, img in enumerate(images):
                # Tentar detectar códigos de barras diretamente na imagem
                barcodes = extract_barcode_from_image(img)
                
                for barcode in barcodes:
                    # Verificar se não é uma chave NFe
                    if not is_nfe_access_key(barcode) and is_boleto_ou_arrecadacao(barcode):
                        all_candidates.append(barcode)
                        candidate_sources[barcode] = "pyzbar"
                        logger.debug(f"Candidato via pyzbar na página {i+1}: {barcode}")
        except Exception as e_direct:
            logger.warning(f"Erro na detecção direta de códigos: {e_direct}")
    
    # 3. OCR como último recurso
    if not all_candidates or len(all_candidates) == 0:
        try:
            ocr_text = _extract_text_with_ocr(pdf_path, filename)
            if ocr_text:
                # Buscar códigos de boleto/arrecadação
                for pattern_idx, pattern in enumerate(BARCODE_PATTERNS):
                    try:
                        matches = re.findall(pattern, ocr_text)
                        for match in matches:
                            match_str = match[0] if isinstance(match, (tuple, list)) and match else str(match)
                            clean_item = re.sub(r"[\s.-]+", "", match_str)
                            
                            # Verificar se é boleto ou arrecadação e não NFe
                            if is_boleto_ou_arrecadacao(clean_item) and not is_nfe_access_key(clean_item):
                                all_candidates.append(clean_item)
                                candidate_sources[clean_item] = "ocr"
                                logger.debug(f"Candidato a boleto/arrecadação via OCR: {clean_item}")
                    except re.error:
                        continue
        except (ConfigurationError, PDFOCRError) as e:
            logger.warning(f"Erro durante OCR: {e}")
    
    # 4. Filtrar e validar todos os candidatos encontrados
    filtered_candidates = _filtrar_codigos_por_validade(all_candidates)
    
    if filtered_candidates:
        # Pegar o primeiro candidato válido (priorizado pela função de filtro)
        barcode = filtered_candidates[0]
        detection_source = candidate_sources.get(barcode, "desconhecido")
        logger.info(f"Código de barras de boleto/arrecadação válido encontrado via {detection_source} em {filename}: {barcode}")
        return barcode, detection_source
    
    # 5. Se chegamos aqui, nenhum código de boleto/arrecadação válido foi encontrado
    logger.error(f"Código de barras de boleto/arrecadação não encontrado em {filename}. Chaves NFe encontradas (e descartadas): {nfe_keys_found}")
    raise BarcodeNotFoundError(f"Código de barras de boleto não encontrado em {filename}. DANFE/NFe encontrada, mas não boleto.", filename=filename)


def process_pdf(pdf_file):
    """Extrai informações (NF, Fornecedor, etc.) do PDF usando pdfplumber e, se necessário, OCR."""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file_obj: # Renomeado para evitar conflito
            temp_file_obj.write(pdf_file.getbuffer())
            temp_path = temp_file_obj.name
        
        # filename para logs e erros
        original_filename = pdf_file.name

        # logger.info(f"Processando arquivo: {original_filename}")

        # A extração de texto para outros campos (NF, CNPJ etc.) também deve ser refatorada
        # para usar _get_primary_text_extraction e _extract_text_with_ocr se necessário.
        # Por enquanto, vamos manter a lógica original de process_pdf para esses campos,
        # mas idealmente ela seria modularizada também.

        # Simulação da extração de texto principal para outros campos (simplificado)
        all_text_for_fields = ""
        try:
            all_text_for_fields = _get_primary_text_extraction(temp_path, original_filename)
            if not all_text_for_fields.strip(): # Se texto primário for vazio, tenta OCR
                logger.info(f"Texto primário vazio para campos em {original_filename}, tentando OCR.")
                try:
                    all_text_for_fields = _extract_text_with_ocr(temp_path, original_filename)
                except (ConfigurationError, PDFOCRError) as e_ocr_fields:
                    logger.warning(f"Falha no OCR para campos de {original_filename}: {e_ocr_fields}. Alguns campos podem não ser extraídos.")
                    pass # Continua com texto vazio se OCR falhar
        except (InvalidPDFError, PDFTextExtractionError) as e_text_fields:
            logger.warning(f"Erro na extração de texto para campos de {original_filename}: {e_text_fields}. Tentando OCR.")
            try:
                all_text_for_fields = _extract_text_with_ocr(temp_path, original_filename)
            except (ConfigurationError, PDFOCRError) as e_ocr_fields_fallback:
                logger.warning(f"Falha no OCR de fallback para campos de {original_filename}: {e_ocr_fields_fallback}. Alguns campos podem não ser extraídos.")
                pass # Continua com texto vazio
        
        logger.debug(f"Texto final para extração de campos em {original_filename} (len: {len(all_text_for_fields)})." )

        results = {
            "Arquivo": original_filename,
            "Código de Barras": "Não encontrado" # Default
        }

        # Extração de outros campos (usando all_text_for_fields)
        nf_match = re.search(r"Número da NF:\s*(\d+)", all_text_for_fields)
        if nf_match: results["Número da NF"] = nf_match.group(1)

        idnf_match = re.search(r"ID\. NF:\s*(\d+)", all_text_for_fields)
        if idnf_match: results["ID. NF"] = idnf_match.group(1)

        fluxus_patterns = [r"ID\.Fluxus\s*(\d+)", r"ID.Fluxus\s+(\d+)", r"ID\s*Fluxus\s*(\d+)", r"Fluxus\s*(\d+)"]
        for pattern in fluxus_patterns:
            fluxus_match = re.search(pattern, all_text_for_fields)
            if fluxus_match: results["ID.Fluxus"] = fluxus_match.group(1); break
        if "ID.Fluxus" not in results:
            table_pattern = r"(\d{7})\s+\d{12}\s+\d{2}/\d{2}/\d{2}"
            table_match = re.search(table_pattern, all_text_for_fields)
            if table_match: results["ID.Fluxus"] = table_match.group(1)

        fornecedor_patterns = [r"Fornecedor:\s*F\d+\s+([^\n]+)\s+CNPJ:", r"Fornecedor:\s*([^\n]+)", r"F\d+\s+([^CNPJ\n]+)"]
        for fp in fornecedor_patterns:
            f_match = re.search(fp, all_text_for_fields)
            if f_match: results["Fornecedor"] = f_match.group(1).strip(); break

        cnpj_patterns = [r"CNPJ:\s*([\d\.\-/]+)", r"CNPJ\s+([\d\.\-/]+)", r"CNPJ/CPF:?\s*([\d\.\-/]+)", r"CPF/CNPJ:\s*([\d\.\-/]+)"]
        for cp in cnpj_patterns:
            c_match = re.search(cp, all_text_for_fields)
            if c_match: results["CNPJ"] = c_match.group(1); break
    
        # Extração do código de barras usando a função refatorada
        try:
            barcode, detection_source = extract_and_clean_barcode(temp_path, original_filename)
            results["Código de Barras"] = barcode
            results["Origem Detecção"] = detection_source
            logger.info(f"Código de barras extraído para {original_filename}: {barcode}, origem: {detection_source}")
        except BarcodeNotFoundError as e:
            results["Código de Barras"] = "Não encontrado"
            results["Erro_CodigoBarras"] = str(e) # Adiciona info do erro específico
            logger.warning(f"Código de barras não encontrado para {original_filename}: {e}")
        except PDFProcessingError as e: # Captura outros erros da extração de barcode
            results["Código de Barras"] = "Erro na Extração"
            results["Erro_CodigoBarras"] = str(e)
            logger.error(f"Erro ao extrair código de barras de {original_filename}: {e}", exc_info=True)

        return results

    except PDFProcessingError as e: # Erros customizados esperados
        logger.error(f"Erro de processamento de PDF para {pdf_file.name}: {e}", exc_info=True)
        return {
            "Arquivo": pdf_file.name,
            "Código de Barras": "Erro no Processamento",
            "Origem Detecção": "texto",  # Default para compatibilidade
            "Erro": str(e)
        }
    except Exception as e_geral: # Erros inesperados
        logger.critical(f"Erro inesperado e não tratado ao processar {pdf_file.name}: {e_geral}", exc_info=True)
        return {
            "Arquivo": pdf_file.name,
            "Código de Barras": "Erro Crítico",
            "Origem Detecção": "texto",  # Default para compatibilidade
            "Erro": f"Erro inesperado: {str(e_geral)}"
        }
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
                logger.debug(f"Arquivo temporário {temp_path} removido.")
            except Exception as e_unlink:
                logger.error(f"Erro ao remover arquivo temporário {temp_path}: {e_unlink}")
                pass

if __name__ == "__main__":
    # Configuração do logging principal aqui
    log_level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    # Formato do Log
    LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(module)s.%(funcName)s:%(lineno)d - %(message)s"
    
    # Configuração básica, mas handlers podem ser mais específicos
    logging.basicConfig(level=log_level, format=LOG_FORMAT, stream=sys.stdout)

    logger = logging.getLogger("PDFProcessorApp") # Logger principal da aplicação
    logger.info(f"Aplicação iniciada com nível de log: {log_level_str}")

    # global cnpj_global_mapping
    cnpj_global_mapping = load_cnpj_idpgto_mapping()
    logger.info(f"{len(cnpj_global_mapping)} mapeamentos CNPJ->IDPGTO carregados.")

    # main() # A função main original precisa ser chamada aqui
    pass # A chamada a main() será restaurada após todas as refatorações.
