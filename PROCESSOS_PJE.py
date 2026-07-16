import time
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# 1. Lista de processos que você deseja analisar (substitua pelos seus)
processos = [
    "0001234-56.2023.5.03.0000",
    "0005678-90.2024.5.02.0000"
]

# Configuração do Navegador (Chrome)
options = webdriver.ChromeOptions()
# options.add_argument("--headless") # Descomente para rodar em segundo plano (sem abrir a janela)
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

resultados = []

for numero_processo in processos:
    try:
        # URL da Consulta Processual unificada do TST
        driver.get("https://consultaprocessual.tst.jus.br/")
        
        # Aguarda o campo de busca carregar
        wait = WebDriverWait(driver, 15)
        campo_busca = wait.until(EC.presence_of_element_by_id("numeroProcesso")) # Ajustar ID conforme o HTML do TST
        
        # Limpa e digita o número do processo
        campo_busca.clear()
        campo_busca.send_keys(numero_processo)
        
        # Clica no botão de buscar
        botao_buscar = driver.find_element(By.ID, "botaoPesquisar")
        botao_buscar.click()
        
        # Aguarda carregar a página de detalhes do processo
        time.sleep(3) 
        
        # Captura o texto de toda a página de movimentações
        corpo_pagina = driver.find_element(By.TAG_NAME, "body").text.lower()
        
        # Termos de busca para Trânsito em Julgado
        termos_transito = ["trânsito em julgado", "transito em julgado", "certificado o trânsito", "baixa definitiva"]
        
        transitou = any(termo in corpo_pagina for termo in termos_transito)
        
        resultados.append({
            "Processo": numero_processo,
            "Transitou em Julgado": "Sim" if transitou else "Não",
            "Status": "Sucesso"
        })
        
    except Exception as e:
        resultados.append({
            "Processo": numero_processo,
            "Transitou em Julgado": "Erro na consulta",
            "Status": f"Erro: {str(e)}"
        })

driver.quit()

# 2. Exporta os resultados para um arquivo Excel / CSV
df = pd.DataFrame(resultados)
df.to_excel("status_processos_tst.xlsx", index=False)
print("Automação concluída! Resultados salvos em 'status_processos_tst.xlsx'.")