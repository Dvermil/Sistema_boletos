import requests
import re
import logging
from typing import Dict, List, Tuple

from ..core.config import settings

logger = logging.getLogger("soap_service")

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