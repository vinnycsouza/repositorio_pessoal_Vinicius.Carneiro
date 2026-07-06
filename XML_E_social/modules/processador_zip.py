import io
import zipfile
from dataclasses import asdict
from typing import Dict, List, Tuple
import xml.etree.ElementTree as ET

import pandas as pd

from modules.parser_xml import (
    BaseContribuicao,
    BaseTrabalhador,
    RubricaInfo,
    RubricaPagamento,
    detectar_tipo_evento,
    parse_s1010,
    parse_s1200,
    parse_s3000,
    parse_s5001,
    parse_s5011,
    parse_empresa_info,
)



def iterar_arquivos_zip_recursivo(blob: bytes, caminho_base: str = ""):
    """Varre ZIP, subpastas e ZIP dentro de ZIP."""
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue

                nome = info.filename
                caminho_atual = f"{caminho_base}::{nome}" if caminho_base else nome
                try:
                    data = zf.read(info)
                except Exception:
                    continue

                if nome.lower().endswith(".zip"):
                    yield from iterar_arquivos_zip_recursivo(data, caminho_base=caminho_atual)
                else:
                    yield caminho_atual, data
    except zipfile.BadZipFile:
        return



def processar_zip_esocial(zip_bytes: bytes) -> Dict[str, object]:
    inventario: List[Dict[str, object]] = []
    erros_xml: List[Dict[str, str]] = []
    xmls_relevantes: List[Tuple[str, str, ET.Element]] = []
    rubricas: List[RubricaInfo] = []
    exclusoes: List[Dict[str, str]] = []
    empresas: List[Dict[str, str]] = []

    eventos_relevantes = {"S-1000", "S-1005", "S-1010", "S-1020", "S-1200", "S-3000", "S-5001", "S-5011"}

    for caminho, conteudo in iterar_arquivos_zip_recursivo(zip_bytes):
        if not caminho.lower().endswith(".xml"):
            inventario.append({
                "arquivo": caminho,
                "tipo": "NAO_XML",
                "tamanho_bytes": len(conteudo),
                "parseado": False,
            })
            continue

        try:
            root = ET.fromstring(conteudo)
        except Exception as exc:
            erros_xml.append({"arquivo": caminho, "erro": str(exc)})
            inventario.append({
                "arquivo": caminho,
                "tipo": "XML_INVALIDO",
                "tamanho_bytes": len(conteudo),
                "parseado": False,
            })
            continue

        tipo_evento = detectar_tipo_evento(root)
        inventario.append({
            "arquivo": caminho,
            "tipo": tipo_evento,
            "tamanho_bytes": len(conteudo),
            "parseado": tipo_evento in eventos_relevantes,
        })

        if tipo_evento in eventos_relevantes:
            xmls_relevantes.append((caminho, tipo_evento, root))
            empresas.append(parse_empresa_info(root, caminho))
            if tipo_evento == "S-1010":
                rubricas.extend(parse_s1010(root))
            elif tipo_evento == "S-3000":
                exclusoes.append(parse_s3000(root))

    # Índice por código/tabela mantendo todas as vigências do S-1010.
    # Não podemos sobrescrever por codRubr + ideTabRubr, pois uma troca de software
    # ou alteração de rubrica pode criar novo iniValid/fimValid para o mesmo código.
    rubricas_map: Dict[Tuple[str, str], List[RubricaInfo]] = {}
    for r in rubricas:
        rubricas_map.setdefault((r.cod_rubr, r.ide_tab_rubr), []).append(r)
        rubricas_map.setdefault((r.cod_rubr, ""), []).append(r)

    remuneracoes: List[RubricaPagamento] = []
    bases_trabalhador: List[BaseTrabalhador] = []
    bases_contribuicao: List[BaseContribuicao] = []

    contagem_parseada = {"S-1010": 0, "S-1200": 0, "S-5001": 0, "S-5011": 0, "S-3000": len(exclusoes)}

    for caminho, tipo_evento, root in xmls_relevantes:
        if tipo_evento == "S-1200":
            itens = parse_s1200(root, rubricas_map, caminho)
            remuneracoes.extend(itens)
            if itens:
                contagem_parseada["S-1200"] += 1
        elif tipo_evento == "S-5001":
            itens = parse_s5001(root, caminho)
            bases_trabalhador.extend(itens)
            if itens:
                contagem_parseada["S-5001"] += 1
        elif tipo_evento == "S-5011":
            itens = parse_s5011(root, caminho)
            bases_contribuicao.extend(itens)
            if itens:
                contagem_parseada["S-5011"] += 1
        elif tipo_evento == "S-1010":
            contagem_parseada["S-1010"] += 1

    recibos_excluidos = {x.get("nrRecEvt", "") for x in exclusoes if x.get("nrRecEvt")}

    remuneracoes_filtradas = [r for r in remuneracoes if r.nr_recibo_evento not in recibos_excluidos]
    bases_trabalhador_filtradas = [b for b in bases_trabalhador if b.nr_recibo_base not in recibos_excluidos]
    bases_contribuicao_filtradas = [b for b in bases_contribuicao if b.nr_recibo_base not in recibos_excluidos]

    df_inventario = pd.DataFrame(inventario)
    df_rubricas = pd.DataFrame([asdict(x) for x in rubricas])
    df_exclusoes = pd.DataFrame(exclusoes)
    df_remun = pd.DataFrame([asdict(x) for x in remuneracoes_filtradas])
    df_bases_trab = pd.DataFrame([asdict(x) for x in bases_trabalhador_filtradas])
    df_bases_contrib = pd.DataFrame([asdict(x) for x in bases_contribuicao_filtradas])
    df_erros = pd.DataFrame(erros_xml)
    df_empresa = pd.DataFrame(empresas)
    if not df_empresa.empty:
        df_empresa = df_empresa.drop_duplicates().copy()
        # Prioriza linha que tenha nome/razão social, normalmente vinda do S-1000.
        df_empresa["tem_nome"] = df_empresa["nome_empresa"].fillna("").astype(str).str.strip().ne("")
        df_empresa = df_empresa.sort_values(["tem_nome", "cnpj_empregador"], ascending=[False, True]).drop(columns=["tem_nome"])

    resumo_eventos = (
        df_inventario[df_inventario["tipo"].isin(eventos_relevantes)]
        .groupby("tipo", as_index=False)
        .agg(xml_localizados=("arquivo", "count"))
        if not df_inventario.empty
        else pd.DataFrame(columns=["tipo", "xml_localizados"])
    )

    df_parseado = pd.DataFrame(
        [{"tipo": k, "xml_parseados": v} for k, v in contagem_parseada.items()]
    )

    df_layout = resumo_eventos.merge(df_parseado, on="tipo", how="outer").fillna(0)
    if not df_layout.empty:
        df_layout["xml_localizados"] = df_layout["xml_localizados"].astype(int)
        df_layout["xml_parseados"] = df_layout["xml_parseados"].astype(int)
        df_layout["nao_parseados"] = df_layout["xml_localizados"] - df_layout["xml_parseados"]

    return {
        "inventario": df_inventario,
        "rubricas": df_rubricas,
        "exclusoes": df_exclusoes,
        "remuneracoes": df_remun,
        "bases_trabalhador": df_bases_trab,
        "bases_contribuicao": df_bases_contrib,
        "erros_xml": df_erros,
        "layout_check": df_layout,
        "empresa": df_empresa,
        "recibos_excluidos": recibos_excluidos,
    }
