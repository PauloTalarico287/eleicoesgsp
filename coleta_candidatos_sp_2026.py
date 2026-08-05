# =============================================================================
# COLETA DE CANDIDATOS - ELEIÇÕES GERAIS 2026 - ESTADO DE SÃO PAULO
# Mural de Jornalismo das Periferias
#
# Fonte: Portal de Dados Abertos do TSE
#   https://dadosabertos.tse.jus.br/dataset/candidatos-2026
#   CDN direto: https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/
#
# ATENÇÃO: o prazo final de registro de candidatura é 15/08/2026 (19h).
# Até lá (e mais uns dias, por causa do prazo de impugnação) esses dados
# mudam diariamente. Rode este script periodicamente até a lista estabilizar.
#
# Cargos cobertos: Presidente, Governador, Senador, Deputado Federal,
# Deputado Estadual — todos com abrangência SP.
# =============================================================================

import requests
import zipfile
import io
import os
import pandas as pd
import json
import time
from datetime import datetime, timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# O CDN do TSE bloqueia (403) requisições com o User-Agent padrão do
# requests/urllib. Precisamos simular um navegador.
HEADERS_NAVEGADOR = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/zip,application/octet-stream,*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://dadosabertos.tse.jus.br/",
}

ANO_ELEICAO = 2026
UF = "SP"
URL_ZIP = f"https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_{ANO_ELEICAO}.zip"

# Padrão descoberto a partir de anos anteriores (2024: foto_cand2024_PB_div.zip
# em .../eleicoes/eleicoes2024/fotos/). Especulativo pra 2026 — se o nome
# mudar, o erro 404/403 vai aparecer no download e a gente ajusta.
URL_ZIP_FOTOS = (
    f"https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{ANO_ELEICAO}"
    f"/fotos/foto_cand{ANO_ELEICAO}_{{uf}}_div.zip"
)
PASTA_FOTOS = "fotos"

# Cargos que entram na página (nomes exatamente como o TSE grava em DS_CARGO)
CARGOS_DESEJADOS = [
    "PRESIDENTE",
    "GOVERNADOR",
    "SENADOR",
    "DEPUTADO FEDERAL",
    "DEPUTADO ESTADUAL",
]

# Situações de registro que consideramos "candidatura válida por enquanto".
# Como o processo ainda está rolando em agosto/2026, mantemos candidaturas
# deferidas E as que ainda estão "sub judice" (em análise), e excluímos
# só o que já foi indeferido/cancelado/renúncia confirmada.
SITUACOES_EXCLUIR = [
    "INDEFERIDO",
    "INDEFERIDO COM RECURSO",
    "CANCELADO",
    "CASSADO",
    "RENÚNCIA",
    "FALECIDO",
]

# Colunas que vamos manter do CSV original do TSE (nomes oficiais)
COLUNAS_TSE = [
    "SQ_CANDIDATO",
    "NM_CANDIDATO",
    "NM_URNA_CANDIDATO",
    "NM_SOCIAL_CANDIDATO",
    "NR_CANDIDATO",
    "DS_CARGO",
    "SG_PARTIDO",
    "NM_PARTIDO",
    "NM_COLIGACAO",
    "DS_COMPOSICAO_COLIGACAO",
    "DS_SIT_TOT_TURNO",
    "DS_SITUACAO_CANDIDATURA",
    "DS_GENERO",
    "DS_GRAU_INSTRUCAO",
    "DS_COR_RACA",
    "SG_UF",
    "SG_UE",
    "NM_UE",
]

# Renomeia pra algo mais amigável pro front-end consumir
RENOMEAR = {
    "SQ_CANDIDATO": "id",
    "NM_CANDIDATO": "nome_completo",
    "NM_URNA_CANDIDATO": "nome_urna",
    "NM_SOCIAL_CANDIDATO": "nome_social",
    "NR_CANDIDATO": "numero",
    "DS_CARGO": "cargo",
    "SG_PARTIDO": "partido_sigla",
    "NM_PARTIDO": "partido_nome",
    "NM_COLIGACAO": "coligacao",
    "DS_COMPOSICAO_COLIGACAO": "coligacao_composicao",
    "DS_SIT_TOT_TURNO": "situacao_eleitoral",
    "DS_SITUACAO_CANDIDATURA": "situacao_candidatura",
    "DS_GENERO": "genero",
    "DS_GRAU_INSTRUCAO": "grau_instrucao",
    "DS_COR_RACA": "cor_raca",
    "SG_UF": "uf",
    "SG_UE": "codigo_ue",
    "NM_UE": "unidade_eleitoral",
}


def _sessao_com_retry() -> requests.Session:
    sessao = requests.Session()
    sessao.headers.update(HEADERS_NAVEGADOR)
    retry = Retry(
        total=4,
        backoff_factor=2,  # 2s, 4s, 8s, 16s entre tentativas
        status_forcelist=[403, 429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    sessao.mount("https://", HTTPAdapter(max_retries=retry))
    return sessao


def baixar_e_extrair_sp(url: str, uf: str) -> pd.DataFrame:
    """Baixa o ZIP consolidado do TSE e extrai só o CSV da UF desejada."""
    print(f"Baixando {url} ...")
    sessao = _sessao_com_retry()

    # Primeiro um GET na página do dataset ajuda a "esquentar" cookies/sessão
    # em alguns WAFs. Ignoramos erro aqui, é só best-effort.
    try:
        sessao.get("https://dadosabertos.tse.jus.br/dataset/candidatos-2026", timeout=30)
    except requests.RequestException:
        pass

    resp = sessao.get(url, timeout=120)

    if resp.status_code == 403:
        raise PermissionError(
            "Bloqueio 403 persistente no CDN do TSE. Possíveis causas:\n"
            "1) O arquivo de 2026 ainda não foi publicado (registro de\n"
            "   candidatura só fecha em 15/08/2026) — confira manualmente\n"
            "   em https://dadosabertos.tse.jus.br/dataset/candidatos-2026\n"
            "2) O CDN está bloqueando o IP do Colab (comum com provedores\n"
            "   de nuvem) — tente rodar localmente ou via GitHub Actions.\n"
        )
    resp.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        nomes = zf.namelist()
        # O TSE distribui um CSV por UF dentro do ZIP, ex: consulta_cand_2026_SP.csv
        candidatos_arquivo = [
            n for n in nomes if n.upper().endswith(f"_{uf}.CSV")
        ]
        if not candidatos_arquivo:
            raise FileNotFoundError(
                f"Não encontrei um CSV de {uf} dentro do ZIP. "
                f"Arquivos disponíveis: {nomes}"
            )
        arquivo = candidatos_arquivo[0]
        print(f"Lendo {arquivo} ...")
        with zf.open(arquivo) as f:
            # TSE usa ; como separador e latin-1 como encoding
            df = pd.read_csv(f, sep=";", encoding="latin-1", low_memory=False)

    return df


def filtrar_e_limpar(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra cargos desejados, remove situações inválidas e seleciona colunas."""
    df = df.copy()
    df.columns = [c.strip().upper() for c in df.columns]

    faltando = [c for c in COLUNAS_TSE if c not in df.columns]
    if faltando:
        print(f"[aviso] colunas ausentes no CSV, seguindo sem elas: {faltando}")

    colunas_disponiveis = [c for c in COLUNAS_TSE if c in df.columns]
    df = df[colunas_disponiveis]

    df["DS_CARGO"] = df["DS_CARGO"].str.strip().str.upper()
    df = df[df["DS_CARGO"].isin(CARGOS_DESEJADOS)]

    if "DS_SITUACAO_CANDIDATURA" in df.columns:
        situacao_upper = df["DS_SITUACAO_CANDIDATURA"].str.strip().str.upper()
        df = df[~situacao_upper.isin(SITUACOES_EXCLUIR)]

    df = df.rename(columns=RENOMEAR)
    df = df.sort_values(["cargo", "partido_sigla", "nome_urna"]).reset_index(drop=True)

    return df


def exportar(df: pd.DataFrame, prefixo: str = "candidatos_sp_2026", pasta_fotos: str = PASTA_FOTOS):
    """Gera JSON (pro site) e CSV (backup/conferência)."""
    registros = df.to_dict(orient="records")

    # Se já rodamos baixar_fotos antes disso, aproveita e linka a foto de
    # cada candidato no JSON (caminho relativo, pra funcionar direto no
    # GitHub Pages). Se não achar arquivo, deixa null — o front-end trata.
    for r in registros:
        candidato_id = str(r.get("id", ""))
        caminho_foto = None
        if os.path.isdir(pasta_fotos):
            for ext in (".jpg", ".jpeg", ".png"):
                candidato_path = os.path.join(pasta_fotos, candidato_id + ext)
                if os.path.isfile(candidato_path):
                    caminho_foto = f"{pasta_fotos}/{candidato_id}{ext}"
                    break
        r["foto"] = caminho_foto

    saida = {
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
        "ano_eleicao": ANO_ELEICAO,
        "uf": UF,
        "total_candidatos": len(registros),
        "cargos": CARGOS_DESEJADOS,
        "candidatos": registros,
    }

    caminho_json = f"{prefixo}.json"
    with open(caminho_json, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
    print(f"JSON salvo em {caminho_json} ({len(registros)} candidatos)")

    caminho_csv = f"{prefixo}.csv"
    df.to_csv(caminho_csv, index=False, encoding="utf-8")
    print(f"CSV salvo em {caminho_csv}")

    # Resumo rápido por cargo, útil pra conferir se bateu com o esperado
    print("\nResumo por cargo:")
    print(df["cargo"].value_counts())


def baixar_fotos(uf: str, ids_candidatos: set, pasta_destino: str = PASTA_FOTOS) -> int:
    """
    Baixa o ZIP de fotos da UF e extrai só as imagens dos candidatos que
    estão no nosso recorte (ids_candidatos = conjunto de SQ_CANDIDATO).
    Retorna quantas fotos foram extraídas. Se o ZIP não existir ainda
    (404) ou vier bloqueado (403), avisa e segue sem quebrar o pipeline
    inteiro — fotos são um "nice to have", não podem travar a coleta.
    """
    url = URL_ZIP_FOTOS.format(uf=uf)
    print(f"\nBaixando fotos de {uf}: {url}")
    sessao = _sessao_com_retry()

    try:
        resp = sessao.get(url, timeout=180)
    except requests.RequestException as e:
        print(f"[aviso] não deu pra baixar fotos ({e}). Seguindo sem fotos.")
        return 0

    if resp.status_code == 404:
        print(f"[aviso] {url} não existe (404). O padrão de nome pode ter "
              f"mudado pra {ANO_ELEICAO} — ainda não temos fotos.")
        return 0
    if resp.status_code != 200:
        print(f"[aviso] status {resp.status_code} ao baixar fotos. "
              f"Seguindo sem fotos por enquanto.")
        return 0

    os.makedirs(pasta_destino, exist_ok=True)
    extraidas = 0

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        nomes_no_zip = zf.namelist()
        print(f"[debug] {len(nomes_no_zip)} arquivo(s) dentro do zip. "
              f"Primeiros 10 nomes: {nomes_no_zip[:10]}")

        # Padrão real descoberto: "F{UF}{SQ_CANDIDATO}_div.jpg"
        # (ex: FSP250002532324_div.jpg). Monta um índice nome-sem-extensão
        # -> nome completo pra casar rápido com nosso recorte de ids.
        indice_por_base = {}
        for nome_arquivo in nomes_no_zip:
            base = os.path.splitext(os.path.basename(nome_arquivo))[0]
            indice_por_base[base] = nome_arquivo

        for candidato_id in ids_candidatos:
            base_esperada = f"F{uf}{candidato_id}_div"
            nome_arquivo = indice_por_base.get(base_esperada)
            if nome_arquivo is None:
                continue
            extensao = os.path.splitext(nome_arquivo)[1] or ".jpg"
            destino = os.path.join(pasta_destino, f"{candidato_id}{extensao}")
            with zf.open(nome_arquivo) as origem, open(destino, "wb") as saida:
                saida.write(origem.read())
            extraidas += 1

    print(f"Fotos extraídas: {extraidas} de {len(ids_candidatos)} candidatos no recorte")
    return extraidas


def main():
    df_bruto = baixar_e_extrair_sp(URL_ZIP, UF)
    df_limpo = filtrar_e_limpar(df_bruto)

    ids_candidatos = set(df_limpo["id"].astype(str))
    baixar_fotos(UF, ids_candidatos)

    exportar(df_limpo)


if __name__ == "__main__":
    main()
