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
    "0000915-57.2024.5.22.0006",
    "0000805-83.2023.5.22.0106",
    "0001765-44.2024.5.07.0034",
    "0001091-48.2024.5.22.0002",
    "0000991-02.2023.5.07.0017",
    "0000031-78.2025.5.06.0122",
    "0000135-46.2024.5.07.0003",
    "0001379-10.2022.5.05.0561",
    "0000883-97.2024.5.20.0009",
    "0001290-36.2023.5.06.0201",
    "0000380-27.2022.5.06.0271",
    "0000244-98.2022.5.19.0002",
    "0000235-75.2024.5.22.0005",
    "0001004-06.2024.5.06.0013",
    "0000147-19.2025.5.19.0059",
    "0000085-03.2023.5.19.0009",
    "0000354-39.2024.5.22.0004",
    "0000049-68.2024.5.19.0059",
    "0000734-23.2024.5.06.0161",
    "0000541-96.2023.5.06.0143",
    "0001723-54.2023.5.05.0561",
    "0001323-71.2021.5.06.0144",
    "0000637-68.2022.5.06.0201",
    "0001646-94.2022.5.10.0802",
    "0000750-57.2025.5.19.0006",
    "0000935-08.2023.5.07.0004",
    "0000940-94.2024.5.07.0036",
    "0000274-46.2023.5.10.0812",
    "0001066-80.2024.5.07.0025",
    "0000235-61.2025.5.06.0401",
    "0000437-72.2024.5.06.0401",
    "0000809-76.2024.5.19.0007",
    "0000783-92.2024.5.13.0024",
    "0000826-68.2023.5.22.0006",
    "0000903-98.2022.5.19.0005",
    "0000498-36.2022.5.05.0463",
    "0000672-56.2017.5.19.0002",
    "0000684-80.2024.5.06.0101",
    "0001634-09.2016.5.05.0195",
    "0000236-37.2021.5.19.0009",
    "0000593-85.2024.5.20.0008",
    "0000441-56.2022.5.05.0030",
    "0000112-70.2015.5.05.0036",
    "0000470-88.2022.5.05.0133",
    "0000889-94.2024.5.06.0009",
    "0000850-62.2019.5.06.0142",
    "0000920-40.2022.5.05.0421",
    "0000459-27.2022.5.05.0661",
    "0000376-79.2024.5.06.0251",
    "0000063-66.2024.5.07.0033",
    "0000707-06.2022.5.06.0001",
    "0000630-15.2023.5.05.0122",
    "0000958-24.2022.5.06.0001",
    "0000359-69.2024.5.07.0007",
    "0000287-68.2024.5.22.0103",
    "0000750-31.2023.5.06.0413",
    "0000303-29.2021.5.06.0020",
    "0001473-31.2024.5.07.0011",
    "0000997-24.2023.5.19.0001",
    "0000354-39.2024.5.22.0004",
    "0001255-28.2024.5.06.0141",
    "0000658-14.2022.5.06.0017",
    "0000628-12.2023.5.05.0133",
    "0000277-96.2024.5.19.0009",
    "0000156-71.2023.5.06.0201",
    "0000921-31.2024.5.06.0161",
    "0000670-25.2022.5.05.0221",
    "0000012-24.2023.5.05.0493",
    "0000668-91.2023.5.05.0133",
    "0000915-74.2024.5.07.0006",
    "0000044-23.2024.5.06.0022",
    "0000388-32.2023.5.06.0412",
    "0000009-93.2022.5.05.0464",
    "0000300-73.2024.5.22.0004",
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