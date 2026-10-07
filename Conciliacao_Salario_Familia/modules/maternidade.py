"""Conciliação documental: levantamento direciona, fonte de apoio valida."""
from __future__ import annotations

import io
import re
from collections import defaultdict

import pandas as pd

from modules.comparador import _sem_acentos, normalizar_competencia, normalizar_valor, ordenar_competencias


GRUPOS = ["Principal", "Apoio", "Revisar", "Excluir"]
MANAD_CAMPOS = ["REG", "CNPJ/CEI", "IND_FL", "COD_LTC", "COD_REG_TRAB", "DT_COMP", "COD_RUBR", "VLR_RUBR", "IND_RUBR", "IND_BASE_IRRF", "IND_BASE_PS"]
COLUNAS = ["cnpj", "competencia", "codigo", "tabela", "descricao", "valor", "arquivo", "linha_origem", "chave", "periodo_revisar"]


def texto(valor) -> str:
    return "" if pd.isna(valor) else str(valor).strip()


def candidata(descricao) -> bool:
    return "matern" in _sem_acentos(texto(descricao))


def sugerir_grupo(descricao) -> str:
    d = _sem_acentos(texto(descricao))
    if not candidata(d) or any(t in d for t in ["prorrog", "licenca", "rescis", "estabilidade", "indeniz", "inss"]):
        return "Revisar"
    if any(t in d for t in ["adicion", "adic ", "media", "insalubr", "pericul", "difer", "dif ", "dsr"]):
        return "Apoio"
    return "Principal"


def competencia(valor) -> str:
    c = normalizar_competencia(texto(valor))
    if re.fullmatch(r"13/\d{4}", c):
        return c[3:]
    if not re.fullmatch(r"\d{4}|(0[1-9]|1[0-2])/\d{4}", c):
        raise ValueError(f"Competência inválida: {texto(valor)}")
    return c


def cnpj_completo(valor) -> str:
    digitos = re.sub(r"\D", "", texto(valor))
    if len(digitos) != 14:
        raise ValueError("CNPJ ausente ou incompleto. A raiz de oito dígitos não é um CNPJ completo.")
    return digitos


def chave_manad(r) -> str:
    valores = [texto(r.get(c)) for c in MANAD_CAMPOS]
    valores[1] = cnpj_completo(valores[1])
    valores[5] = competencia(valores[5])
    v = normalizar_valor(valores[7])
    valores[7] = f"{v:.2f}" if pd.notna(v) else "inválido"
    return "|".join(valores)


def catalogo_manad(cadastro: pd.DataFrame) -> dict:
    mapa = defaultdict(set)
    for _, r in cadastro.iterrows():
        mapa[texto(r["COD_RUBRICA"])].add(texto(r["DESC_RUBRICA"]))
    return {k: " / ".join(sorted(v)) for k, v in mapa.items()}


def normalizar_manad(base: pd.DataFrame, cadastro: dict, arquivo: str) -> pd.DataFrame:
    faltantes = set(MANAD_CAMPOS) - set(base.columns)
    if faltantes:
        raise ValueError(f"Campos MANAD ausentes: {', '.join(sorted(faltantes))}")
    saida = []
    for indice, r in base.iterrows():
        descricao = cadastro.get(texto(r["COD_RUBR"]), "")
        saida.append({
            "cnpj": cnpj_completo(r["CNPJ/CEI"]), "competencia": competencia(r["DT_COMP"]),
            "codigo": texto(r["COD_RUBR"]), "tabela": "", "descricao": descricao,
            "valor": normalizar_valor(r["VLR_RUBR"]), "arquivo": arquivo,
            "linha_origem": int(indice) + 2, "chave": chave_manad(r),
            "periodo_revisar": bool(re.search(r"13|rescis", _sem_acentos(descricao))) and competencia(r["DT_COMP"]) != texto(r["DT_COMP"])[-4:],
        })
    return pd.DataFrame(saida, columns=COLUNAS)


def normalizar_esocial(base: pd.DataFrame, arquivo: str) -> pd.DataFrame:
    campos = {"nr_insc_estab", "per_apur", "cod_rubr", "ide_tab_rubr", "dsc_rubr", "vr_rubr"}
    if not campos.issubset(base.columns):
        raise ValueError("O relatório precisa conter movimentos detalhados com CNPJ, competência, rubrica, tabela, descrição e valor.")
    saida = []
    for indice, r in base.iterrows():
        if "tp_insc_estab" in base and texto(r["tp_insc_estab"]) != "1":
            raise ValueError("Há inscrições de estabelecimento que não são CNPJ.")
        descricao = texto(r["dsc_rubr"])
        # Hash isolado não identifica um lançamento: o mesmo item pode ocorrer em eventos diferentes.
        caminho = texto(r.get("caminho_item"))
        origem = texto(r.get("arquivo"))
        chave = f"{origem}|{caminho}" if origem and caminho else ""
        periodo = competencia(r["per_apur"])
        saida.append({
            "cnpj": cnpj_completo(r["nr_insc_estab"]), "competencia": periodo,
            "codigo": texto(r["cod_rubr"]), "tabela": texto(r["ide_tab_rubr"]),
            "descricao": descricao, "valor": normalizar_valor(r["vr_rubr"]),
            "arquivo": origem or arquivo, "linha_origem": int(indice) + 2, "chave": chave,
            "periodo_revisar": (bool(re.search(r"13|rescis", _sem_acentos(descricao))) and len(periodo) != 4) or texto(r.get("origem_periodo")) == "infoPerAnt",
            "natureza": texto(r.get("nat_rubr")), "incidencia_cp": texto(r.get("cod_inc_cp")),
            "tipo_rubrica": texto(r.get("tp_rubr")), "inicio_validade": texto(r.get("ini_valid")),
            "fim_validade": texto(r.get("fim_valid")), "status_cadastro": texto(r.get("status_auditoria")),
            "recibo": texto(r.get("nr_recibo_evento")), "per_ref": texto(r.get("per_ref")),
        })
    return pd.DataFrame(saida, columns=COLUNAS + ["natureza", "incidencia_cp", "tipo_rubrica", "inicio_validade", "fim_validade", "status_cadastro", "recibo", "per_ref"])


def ler_levantamento(conteudo: bytes, origem: str, nome: str) -> pd.DataFrame:
    with pd.ExcelFile(io.BytesIO(conteudo)) as excel:
        if origem == "MANAD":
            base = pd.read_excel(excel, sheet_name="K300_FILTRADO", dtype=str)
            cadastro = pd.read_excel(excel, sheet_name="K150_SELECIONADAS", dtype=str)
            return normalizar_manad(base, catalogo_manad(cadastro), nome)
        aba = next((a for a in ["03_movimentos", "03_movimentos_cp", "apoio_s1200"] if a in excel.sheet_names), None)
        if not aba:
            raise ValueError("Levantamento eSocial sem aba de movimentos detalhados. Gere a versão completa.")
        base = pd.read_excel(excel, sheet_name=aba, dtype=str)
        return normalizar_esocial(base, nome)


def ler_manad(conteudo: bytes, nome: str) -> tuple[pd.DataFrame, list[str]]:
    try:
        linhas = conteudo.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError:
        linhas = conteudo.decode("cp1252").splitlines()
    cadastro = defaultdict(set)
    registros = []
    avisos = []
    periodos = []
    for numero, linha in enumerate(linhas, 1):
        campos = linha.rstrip().split("|")
        if campos[0] == "0000" and len(campos) >= 14:
            periodos.append((campos[2], campos[12], campos[13]))
        if campos[0] == "K150":
            if len(campos) < 5:
                raise ValueError(f"Registro K150 incompleto na linha {numero}.")
            cadastro[(campos[1], campos[3])].add(campos[4])
        if campos[0] == "K300":
            if len(campos) < 11:
                raise ValueError(f"Registro K300 incompleto na linha {numero}.")
            registros.append((numero, dict(zip(MANAD_CAMPOS, campos[:11]))))
    if not registros:
        raise ValueError("Nenhum registro K300 encontrado no MANAD.")
    if len(set(periodos)) != len(periodos):
        avisos.append("MANAD contém blocos com períodos repetidos; lançamentos foram preservados.")
    if any(len(v) > 1 for v in cadastro.values()):
        avisos.append("Há descrições diferentes para o mesmo CNPJ/código no cadastro MANAD. Revise a classificação.")
    partes = []
    # Separar empresas evita associar códigos iguais de empregadores diferentes.
    for cnpj in sorted({r["CNPJ/CEI"] for _, r in registros}):
        selecionados = [(n, r) for n, r in registros if r["CNPJ/CEI"] == cnpj]
        base = pd.DataFrame([r for _, r in selecionados])
        mapa = {cod: " / ".join(sorted(ds)) for (emp, cod), ds in cadastro.items() if emp == cnpj}
        normalizado = normalizar_manad(base, mapa, nome)
        normalizado["linha_origem"] = [n for n, _ in selecionados]
        partes.append(normalizado)
    return pd.concat(partes, ignore_index=True), avisos


def ler_incidencia(conteudo: bytes, nome: str) -> tuple[pd.DataFrame, list[str]]:
    avisos = []
    with pd.ExcelFile(io.BytesIO(conteudo)) as excel:
        aba = next((a for a in ["03_movimentos_cp", "apoio_s1200", "03_movimentos"] if a in excel.sheet_names), None)
        if aba is None:
            avisos.append("Relatório resumido: validação de lançamentos indisponível. Gere a versão completa.")
            return pd.DataFrame(columns=COLUNAS), avisos
        base = normalizar_esocial(pd.read_excel(excel, sheet_name=aba, dtype=str), nome)
        # apoio_s1200 e 03_movimentos_cp representam a mesma base; ler apenas uma.
        if "apoio_s2299" in excel.sheet_names:
            rescisao = pd.read_excel(excel, sheet_name="apoio_s2299", dtype=str)
            if not rescisao.empty:
                base = pd.concat([base, normalizar_esocial(rescisao, nome)], ignore_index=True)
        if base["descricao"].eq("").any():
            avisos.append("Há movimentos sem descrição no relatório de incidência. A completude da busca por maternidade é parcial.")
        return base, avisos


def validar(levantamento: pd.DataFrame, fonte: pd.DataFrame, origem: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    detalhe = levantamento.copy()
    fonte = fonte.copy()
    if not fonte.empty and not set(detalhe.cnpj).issubset(set(fonte.cnpj)):
        raise ValueError("O validador não contém todos os CNPJs do levantamento. Confira os arquivos da empresa.")
    # Identificação de candidatos pela descrição, nunca por códigos fixos de empresa.
    chaves_candidatas = set(zip(fonte.loc[fonte.descricao.map(candidata), "cnpj"], fonte.loc[fonte.descricao.map(candidata), "codigo"], fonte.loc[fonte.descricao.map(candidata), "tabela"]))
    detalhe["candidata"] = [candidata(r.descricao) or (r.cnpj, r.codigo, r.tabela) in chaves_candidatas for r in detalhe.itertuples()]
    # O usuário já selecionou o levantamento: preservar descrições alternativas
    # para revisão, mesmo quando não contêm o termo sugerido.
    ocorrencias = []
    indice = defaultdict(list)
    for i, r in fonte.iterrows():
        chave = (r.cnpj, r.competencia, r.codigo, r.tabela)
        indice[chave].append(i)
    usados = set()
    estados = []
    descricoes = []
    incidencias = []
    for _, r in detalhe.iterrows():
        k = (r.cnpj, r.competencia, r.codigo, r.tabela)
        candidatos = indice[k]
        completos = [i for i in candidatos if pd.notna(r.valor) and pd.notna(fonte.loc[i, "valor"]) and abs(float(r.valor) - float(fonte.loc[i, "valor"])) < .005]
        if origem == "MANAD":
            completos = [i for i in completos if fonte.loc[i, "chave"] == r.chave]
        elif r.chave:
            completos = [i for i in completos if fonte.loc[i, "chave"] == r.chave]
        disponiveis = [i for i in completos if i not in usados]
        if disponiveis:
            i = disponiveis[0]
            usados.add(i)
            estados.append("Lançamento confere" if origem == "MANAD" or r.chave else "Valor confere; identificação parcial")
            descricoes.append(fonte.loc[i, "descricao"] or r.descricao)
            incidencias.append(texto(fonte.loc[i].get("incidencia_cp")))
            if origem != "MANAD" and texto(fonte.loc[i].get("status_cadastro")) != "S1010_VALIDO":
                estados[-1] += "; cadastro S-1010 requer conferência"
            if r.descricao and fonte.loc[i, "descricao"] and _sem_acentos(r.descricao) != _sem_acentos(fonte.loc[i, "descricao"]):
                estados[-1] += "; descrição divergente"
        else:
            estados.append("Repetição excedente no levantamento" if completos else "Não localizado ou valor divergente")
            descricoes.append(r.descricao)
            incidencias.append("")
        if pd.isna(r.valor):
            estados[-1] = "Valor ausente ou inválido"
    detalhe["validacao"] = estados
    detalhe["descricao_validador"] = descricoes
    detalhe["incidencia_validador"] = incidencias
    repetidas = detalhe.chave.ne("") & detalhe.duplicated("chave", keep=False)
    detalhe.loc[repetidas, "validacao"] += "; repetição preservada"
    for i, r in fonte.iterrows():
        if i not in usados and candidata(r.descricao):
            ocorrencias.append({**r.to_dict(), "ocorrencia": "Lançamento de maternidade no validador ausente do levantamento"})
    return detalhe, pd.DataFrame(ocorrencias)


def sugerir_classificacao(detalhe: pd.DataFrame) -> pd.DataFrame:
    colunas = ["cnpj", "codigo", "tabela", "descricao", "grupo", "competencia_destino", "justificativa"]
    linhas = []
    for (cnpj, codigo, tabela), base in detalhe.groupby(["cnpj", "codigo", "tabela"], dropna=False, sort=False):
        ds = " / ".join(sorted(set(base.descricao) | set(base.descricao_validador)))
        grupo = sugerir_grupo(ds)
        if base.periodo_revisar.any():
            grupo = "Revisar"
        linhas.append({"cnpj": cnpj, "codigo": codigo, "tabela": tabela, "descricao": ds,
                       "grupo": grupo, "competencia_destino": "", "justificativa": ""})
    return pd.DataFrame(linhas, columns=colunas)


def aplicar_classificacao(detalhe: pd.DataFrame, classificacao: pd.DataFrame) -> pd.DataFrame:
    chave = ["cnpj", "codigo", "tabela"]
    if classificacao.duplicated(chave).any():
        raise ValueError("Classificação duplicada para a mesma rubrica.")
    base = detalhe.copy()
    base["competencia_original"] = base.competencia
    saida = base.merge(classificacao[chave + ["grupo", "competencia_destino", "justificativa"]], on=chave, how="left", validate="many_to_one")
    if saida.grupo.isna().any() or not saida.grupo.isin(GRUPOS).all() or saida.grupo.eq("Revisar").any():
        raise ValueError("Classifique todas as rubricas como Principal, Apoio ou Excluir antes de gerar.")
    for i, r in saida.iterrows():
        if texto(r.competencia_destino):
            periodos = saida.loc[(saida.cnpj == r.cnpj) & (saida.codigo == r.codigo) & (saida.tabela == r.tabela), "competencia"]
            anos = {competencia(p)[-4:] for p in periodos}
            destino = competencia(r.competencia_destino)
            if len(anos) > 1 or destino[-4:] not in anos:
                raise ValueError("A competência de destino deve pertencer ao mesmo ano de todos os lançamentos da rubrica. Separe o levantamento por ano para reclassificar períodos.")
            saida.loc[i, "competencia"] = destino
        if r.periodo_revisar and r.grupo != "Excluir" and not texto(r.justificativa):
            raise ValueError("Rubricas de 13º em período mensal, rescisão ou períodos anteriores precisam de justificativa de enquadramento.")
    return saida


def comparar_maternidade(ecac: pd.DataFrame, detalhe: pd.DataFrame) -> pd.DataFrame:
    if "salario_maternidade" not in ecac:
        raise ValueError("O Excel e-CAC não contém salário-maternidade. Reprocesse os PDFs no módulo 1.")
    dados = ecac.copy()
    dados["cnpj"] = dados.cnpj.map(cnpj_completo)
    dados["competencia"] = dados.competencia.map(competencia)
    if dados.duplicated(["cnpj", "competencia"]).any():
        raise ValueError("Excel e-CAC com declarações duplicadas por competência. Use a aba consolidada gerada pelo app.")
    dados["Declarado no e-CAC"] = dados.salario_maternidade.map(normalizar_valor)
    chaves = ["cnpj", "competencia"]
    selecionado = detalhe.loc[detalhe.grupo.isin(["Principal", "Apoio"])].copy()
    if not selecionado.empty and not set(selecionado.cnpj).intersection(set(dados.cnpj)):
        raise ValueError("Nenhum CNPJ do levantamento corresponde à DCTFWeb. Confira o estabelecimento e os documentos da empresa.")
    linhas = []
    for k, base in selecionado.groupby(chaves, sort=False):
        valores = {}
        for grupo, coluna in [("Principal", "Principal"), ("Apoio", "Apoios considerados")]:
            itens = base.loc[base.grupo.eq(grupo), "valor"]
            valores[coluna] = float("nan") if itens.isna().any() else round(itens.sum(), 2)
        linhas.append(dict(zip(chaves, k), **valores, **{
            "Validação documental": "Conferência com ressalvas" if not base.validacao.eq("Lançamento confere").all() else "Lançamentos conferem",
        }))
    consolidado = pd.DataFrame(linhas, columns=chaves + ["Principal", "Apoios considerados", "Validação documental"])
    resultado = consolidado.merge(dados[chaves + ["Declarado no e-CAC"]], on=chaves, how="outer")
    resultado["Total identificado"] = (resultado["Principal"] + resultado["Apoios considerados"]).round(2)
    for grupo, coluna in [("Principal", "sem apoios"), ("Total identificado", "com apoios")]:
        diferenca = (resultado[grupo] - resultado["Declarado no e-CAC"]).round(2)
        resultado[f"Potencial crédito {coluna}"] = diferenca.clip(lower=0)
        resultado[f"Declarado superior {coluna}"] = (-diferenca).clip(lower=0)
    def situacao(r):
        if pd.isna(r["Declarado no e-CAC"]):
            return "Valor e-CAC ausente ou não informado"
        if pd.isna(r["Total identificado"]):
            return "Levantamento ausente ou valor inválido"
        if r["Potencial crédito com apoios"] > 0:
            return "Potencial crédito sujeito à validação jurídica"
        if r["Declarado superior com apoios"] > 0:
            return "Declarado superior ao total identificado"
        return "Valores coincidentes com apoios"
    resultado["Situação"] = resultado.apply(situacao, axis=1)
    resultado["Validação documental"] = resultado["Validação documental"].fillna("Sem levantamento considerado")
    ordem = chaves + ["Principal", "Apoios considerados", "Total identificado", "Declarado no e-CAC", "Potencial crédito sem apoios", "Potencial crédito com apoios", "Declarado superior sem apoios", "Declarado superior com apoios", "Validação documental", "Situação"]
    return ordenar_competencias(resultado[ordem]).reset_index(drop=True)
