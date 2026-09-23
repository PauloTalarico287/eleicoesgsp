"""
Prestação de contas — Deputados Estaduais e Federais de SP (Eleições 2026)
Versão para rodar dentro de um runner do GitHub Actions.

Diferença em relação à versão para Colab: aqui o download roda na
infraestrutura do GitHub (não na sua conexão), e a saída é só a planilha
agregada e pequena, gravada em ./resultados/ para o Actions publicar como
artefato do workflow.
"""

import os

import pandas as pd
import requests
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ANO = 2026
UF_ALVO = "SP"
CARGOS_ALVO = ["DEPUTADO ESTADUAL", "DEPUTADO FEDERAL"]

URL_ZIP_CANDIDATOS = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/"
    f"prestacao_de_contas_eleitorais_candidatos_{ANO}.zip"
)
URL_DATASET = "https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-2026"

# Mesmo padrão usado em coleta_candidatos_sp_2026.py, que já funciona contra
# o CDN do TSE pelo Actions: navegador simulado + Referer + aquecimento de
# sessão na página do dataset antes de bater na CDN.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/zip,application/octet-stream,*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://dadosabertos.tse.jus.br/",
}

PASTA_DADOS = "dados_tse"
PASTA_SAIDA = "resultados"

# Ajuste aqui se os nomes reais de coluna do TSE diferirem (rode com a env var
# MODO=colunas pra imprimir os nomes de cada CSV antes de decidir).
COL_UF = "SG_UF"
COL_CARGO = "DS_CARGO"
COL_CANDIDATO = "NM_CANDIDATO"
COL_NUMERO = "NR_CANDIDATO"
COL_PARTIDO = "SG_PARTIDO"
COL_FONTE_RECEITA = "DS_FONTE_RECEITA"
COL_VALOR_RECEITA = "VR_RECEITA"
COL_TIPO_DESPESA = "DS_ORIGEM_DESPESA"
COL_VALOR_DESPESA_CONTRATADA = "VR_DESPESA_CONTRATADA"
COL_VALOR_DESPESA_PAGA = "VR_PAGTO_DESPESA"


def _sessao_com_retry() -> requests.Session:
    sessao = requests.Session()
    sessao.headers.update(HEADERS)
    retry = Retry(
        total=4,
        backoff_factor=2,  # 2s, 4s, 8s, 16s entre tentativas
        status_forcelist=[403, 429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    sessao.mount("https://", HTTPAdapter(max_retries=retry))
    return sessao


def baixar_e_extrair(url: str, pasta_destino: str = PASTA_DADOS) -> str:
    import zipfile

    os.makedirs(pasta_destino, exist_ok=True)
    caminho_zip = os.path.join(pasta_destino, "prestacao_contas.zip")
    print(f"Baixando {url} ...")

    sessao = _sessao_com_retry()

    # "Esquenta" cookies/sessão visitando a página do dataset antes da CDN —
    # best-effort, ignora erro aqui.
    try:
        sessao.get(URL_DATASET, timeout=30)
    except requests.RequestException:
        pass

    with sessao.get(url, timeout=600, stream=True) as resp:
        if resp.status_code == 403:
            raise PermissionError(
                "Bloqueio 403 persistente no CDN do TSE mesmo com sessão "
                "aquecida e retry. Pode ser que este arquivo específico "
                "tenha proteção adicional (alta demanda na prestação "
                "parcial) — vale tentar de novo mais tarde."
            )
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        baixado = 0
        with open(caminho_zip, "wb") as f:
            for bloco in resp.iter_content(chunk_size=1024 * 1024):
                f.write(bloco)
                baixado += len(bloco)
                if total:
                    print(f"\r{baixado/1024/1024:.0f}/{total/1024/1024:.0f} MB", end="")
    print("\nExtraindo...")
    with zipfile.ZipFile(caminho_zip) as z:
        z.extractall(pasta_destino)
    # Apaga o zip bruto pra não subir peso desnecessário no runner
    os.remove(caminho_zip)
    return pasta_destino


def localizar_arquivo(pasta: str, pista: str) -> str:
    candidatos = [
        f for f in os.listdir(pasta)
        if pista.lower() in f.lower() and f.lower().endswith(".csv")
    ]
    if not candidatos:
        raise FileNotFoundError(f"Nenhum arquivo com '{pista}' em {pasta}: {os.listdir(pasta)}")
    return os.path.join(pasta, candidatos[0])


def ler_csv_tse(caminho: str) -> pd.DataFrame:
    return pd.read_csv(caminho, sep=";", encoding="latin-1", low_memory=False)


def mostrar_colunas(pasta: str) -> None:
    for nome in os.listdir(pasta):
        if nome.lower().endswith(".csv"):
            df = pd.read_csv(os.path.join(pasta, nome), sep=";", encoding="latin-1", nrows=5)
            print(f"\n=== {nome} ===")
            print(list(df.columns))


def filtrar_sp_deputados(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df[COL_CARGO] = df[COL_CARGO].astype(str).str.upper().str.strip()
    filtro_uf = df[COL_UF].astype(str).str.upper().str.strip() == UF_ALVO
    filtro_cargo = df[COL_CARGO].isin(CARGOS_ALVO)
    return df[filtro_uf & filtro_cargo].copy()


def resumo_receitas(df_receitas: pd.DataFrame):
    df = filtrar_sp_deputados(df_receitas)
    df[COL_VALOR_RECEITA] = pd.to_numeric(df[COL_VALOR_RECEITA], errors="coerce")

    total_por_candidato = (
        df.groupby([COL_CANDIDATO, COL_NUMERO, COL_PARTIDO, COL_CARGO])[COL_VALOR_RECEITA]
        .sum().reset_index().rename(columns={COL_VALOR_RECEITA: "total_arrecadado"})
        .sort_values("total_arrecadado", ascending=False)
    )
    por_fonte = (
        df.groupby([COL_CANDIDATO, COL_FONTE_RECEITA])[COL_VALOR_RECEITA]
        .sum().reset_index().rename(columns={COL_VALOR_RECEITA: "valor"})
        .sort_values("valor", ascending=False)
    )
    return total_por_candidato, por_fonte


def resumo_despesas(df_contratadas: pd.DataFrame, df_pagas: pd.DataFrame) -> pd.DataFrame:
    dfc = filtrar_sp_deputados(df_contratadas)
    dfp = filtrar_sp_deputados(df_pagas)
    dfc[COL_VALOR_DESPESA_CONTRATADA] = pd.to_numeric(dfc[COL_VALOR_DESPESA_CONTRATADA], errors="coerce")
    dfp[COL_VALOR_DESPESA_PAGA] = pd.to_numeric(dfp[COL_VALOR_DESPESA_PAGA], errors="coerce")

    contratado = dfc.groupby([COL_CANDIDATO, COL_NUMERO])[COL_VALOR_DESPESA_CONTRATADA].sum().reset_index()
    pago = dfp.groupby([COL_CANDIDATO, COL_NUMERO])[COL_VALOR_DESPESA_PAGA].sum().reset_index()

    comparativo = pd.merge(contratado, pago, on=[COL_CANDIDATO, COL_NUMERO], how="outer").fillna(0)
    comparativo["diferenca_contratado_menos_pago"] = (
        comparativo[COL_VALOR_DESPESA_CONTRATADA] - comparativo[COL_VALOR_DESPESA_PAGA]
    )
    return comparativo.sort_values(COL_VALOR_DESPESA_CONTRATADA, ascending=False)


def principais_categorias_despesa(df_despesas: pd.DataFrame, col_valor: str, top_n: int = 30) -> pd.DataFrame:
    df = filtrar_sp_deputados(df_despesas)
    df[col_valor] = pd.to_numeric(df[col_valor], errors="coerce")
    return (
        df.groupby(COL_TIPO_DESPESA)[col_valor].sum().reset_index()
        .sort_values(col_valor, ascending=False).head(top_n)
    )


COLUNAS_MOEDA = {
    "total_arrecadado", "valor",
    COL_VALOR_DESPESA_CONTRATADA, COL_VALOR_DESPESA_PAGA,
    "diferenca_contratado_menos_pago",
}


def _formatar_aba(worksheet, df: pd.DataFrame) -> None:
    for col_idx, nome_coluna in enumerate(df.columns, start=1):
        worksheet.cell(row=1, column=col_idx).font = Font(bold=True)
        largura = max(12, min(40, len(str(nome_coluna)) + 4))
        worksheet.column_dimensions[get_column_letter(col_idx)].width = largura
        if nome_coluna in COLUNAS_MOEDA:
            for row_idx in range(2, len(df) + 2):
                worksheet.cell(row=row_idx, column=col_idx).number_format = "R$ #,##0.00"
    worksheet.freeze_panes = "A2"


def exportar_para_excel(tabelas: dict, caminho: str) -> None:
    with pd.ExcelWriter(caminho, engine="openpyxl") as writer:
        for nome_aba, df in tabelas.items():
            df.to_excel(writer, sheet_name=nome_aba[:31], index=False)
            _formatar_aba(writer.sheets[nome_aba[:31]], df)
    print(f"Planilha gerada: {caminho}")


def main():
    pasta = baixar_e_extrair(URL_ZIP_CANDIDATOS)

    if os.environ.get("MODO") == "colunas":
        mostrar_colunas(pasta)
        return

    df_receitas = ler_csv_tse(localizar_arquivo(pasta, "receitas"))
    df_desp_contratadas = ler_csv_tse(localizar_arquivo(pasta, "despesas_contratadas"))
    df_desp_pagas = ler_csv_tse(localizar_arquivo(pasta, "despesas_pagas"))

    total_arrecadado, receitas_por_fonte = resumo_receitas(df_receitas)
    comparativo_despesas = resumo_despesas(df_desp_contratadas, df_desp_pagas)
    top_pagas = principais_categorias_despesa(df_desp_pagas, COL_VALOR_DESPESA_PAGA)
    top_contratadas = principais_categorias_despesa(df_desp_contratadas, COL_VALOR_DESPESA_CONTRATADA)

    os.makedirs(PASTA_SAIDA, exist_ok=True)
    exportar_para_excel(
        {
            "Total arrecadado": total_arrecadado,
            "Receitas por fonte": receitas_por_fonte,
            "Despesas contratado x pago": comparativo_despesas,
            "Top despesas pagas": top_pagas,
            "Top despesas contratadas": top_contratadas,
        },
        os.path.join(PASTA_SAIDA, "prestacao_contas_sp_2026.xlsx"),
    )


if __name__ == "__main__":
    main()
