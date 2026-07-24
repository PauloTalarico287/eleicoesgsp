# ==============================================================================
# PIPELINE: Resultados 2022 por zona eleitoral — São Paulo (capital) + RMSP
# Feito para rodar no Google Colab. Cole em células separadas, na ordem abaixo.
# ==============================================================================
#
# COMO USAR:
#   1. Rode a CÉLULA 1 (download) uma vez só — o zip é grande.
#   2. Rode a CÉLULA 2 (inspeção) e CONFIRA se os nomes de coluna impressos
#      batem com o dicionário COLS logo abaixo. Se algo estiver diferente,
#      ajuste o dicionário antes de seguir. Isso é importante: eu escrevi
#      esse mapeamento com base no dicionário de dados público do TSE, mas
#      não tenho como validar contra o arquivo real no meu ambiente — por
#      isso essa conferência manual é obrigatória, não opcional.
#   3. Rode a CÉLULA 3 (agregação) — gera o resultados.json final.
#   4. Baixe o resultados.json (última linha) e coloque na mesma pasta do
#      index.html que vou te passar em seguida.
#
# ==============================================================================


# ------------------------------------------------------------------------------
# CÉLULA 1 — Download e extração
# ------------------------------------------------------------------------------
import requests, zipfile, io, os

URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2022.zip"
DEST = "/content/dados_tse"
os.makedirs(DEST, exist_ok=True)

print("Baixando (pode demorar, é um arquivo nacional)...")
r = requests.get(URL, timeout=300)
r.raise_for_status()
z = zipfile.ZipFile(io.BytesIO(r.content))
z.extractall(DEST)
print("Arquivos extraídos:")
for f in sorted(os.listdir(DEST)):
    print(" -", f)


# ------------------------------------------------------------------------------
# CÉLULA 2 — Inspeção (CONFIRA antes de seguir!)
# ------------------------------------------------------------------------------
import pandas as pd

# O arquivo de SP normalmente vem nomeado algo como:
# votacao_candidato_munzona_2022_SP.csv — ajuste se o nome vier diferente
# (confira a lista impressa na Célula 1).
ARQUIVO_SP = [f for f in os.listdir(DEST) if f.upper().endswith("SP.CSV")][0]
caminho = os.path.join(DEST, ARQUIVO_SP)
print("Lendo:", caminho)

# Os CSVs do TSE geralmente vêm em latin-1, separados por ';'
df_amostra = pd.read_csv(caminho, sep=";", encoding="latin-1", nrows=1000)

print("\nColunas encontradas no arquivo:")
print(list(df_amostra.columns))
print("\nAmostra:")
print(df_amostra.head(3))

# --- Mapeamento esperado (dicionário de dados público do TSE) ---
# Se os nomes acima forem diferentes do que está aqui, ajuste o dicionário
# COLS na Célula 3 antes de continuar.
COLS_ESPERADAS = {
    "turno": "NR_TURNO",
    "municipio_cod": "CD_MUNICIPIO",
    "municipio_nome": "NM_MUNICIPIO",
    "zona": "NR_ZONA",
    "cargo": "DS_CARGO",
    "candidato_nome_urna": "NM_URNA_CANDIDATO",
    "partido_sigla": "SG_PARTIDO",
    "votos": "QT_VOTOS_NOMINAIS",
}
print("\nEsperado (confira contra a lista de colunas acima):")
print(COLS_ESPERADAS)


# ------------------------------------------------------------------------------
# CÉLULA 3 — Filtro, agregação e exportação do JSON
# ------------------------------------------------------------------------------
import json

# Ajuste aqui SE a Célula 2 mostrou nomes diferentes:
COLS = {
    "turno": "NR_TURNO",
    "municipio_cod": "CD_MUNICIPIO",
    "municipio_nome": "NM_MUNICIPIO",
    "zona": "NR_ZONA",
    "cargo": "DS_CARGO",
    "candidato_nome_urna": "NM_URNA_CANDIDATO",
    "partido_sigla": "SG_PARTIDO",
    "votos": "QT_VOTOS_NOMINAIS",
}

# Os 39 municípios da Região Metropolitana de São Paulo
MUNICIPIOS_RMSP = [
    "ARUJA", "BARUERI", "BIRITIBA-MIRIM", "CAIEIRAS", "CAJAMAR", "CARAPICUIBA",
    "COTIA", "DIADEMA", "EMBU DAS ARTES", "EMBU-GUACU", "FERRAZ DE VASCONCELOS",
    "FRANCISCO MORATO", "FRANCO DA ROCHA", "GUARAREMA", "GUARULHOS",
    "ITAPECERICA DA SERRA", "ITAPEVI", "ITAQUAQUECETUBA", "JANDIRA", "JUQUITIBA",
    "MAIRIPORA", "MAUA", "MOGI DAS CRUZES", "OSASCO", "PIRAPORA DO BOM JESUS",
    "POA", "RIBEIRAO PIRES", "RIO GRANDE DA SERRA", "SALESOPOLIS", "SANTA ISABEL",
    "SANTANA DE PARNAIBA", "SANTO ANDRE", "SAO BERNARDO DO CAMPO",
    "SAO CAETANO DO SUL", "SAO LOURENCO DA SERRA", "SAO PAULO", "SUZANO",
    "TABOAO DA SERRA", "VARGEM GRANDE PAULISTA",
]
# normalização simples (sem acento, maiúsculo) pra comparar com segurança
import unicodedata
def normaliza(s):
    s = str(s).upper().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s

MUNICIPIOS_RMSP_NORM = set(normaliza(m) for m in MUNICIPIOS_RMSP)

TOP_N_POR_RECORTE = 30  # quantos candidatos manter em cada ranking (zona ou município)
                        # aumente se quiser a lista completa (JSON fica maior)

print("Lendo arquivo completo (pode demorar um pouco)...")
df = pd.read_csv(caminho, sep=";", encoding="latin-1", usecols=list(COLS.values()))
df["_municipio_norm"] = df[COLS["municipio_nome"]].apply(normaliza)
df_rmsp = df[df["_municipio_norm"].isin(MUNICIPIOS_RMSP_NORM)].copy()
print(f"Linhas após filtro RMSP: {len(df_rmsp)} de {len(df)} originais")

resultado = {"meta": {"fonte": "TSE - votacao_candidato_munzona_2022",
                       "gerado_em": pd.Timestamp.now().isoformat()},
             "dados": {}}

for turno, g_turno in df_rmsp.groupby(COLS["turno"]):
    turno_key = str(int(turno))
    resultado["dados"][turno_key] = {}

    for cargo, g_cargo in g_turno.groupby(COLS["cargo"]):
        resultado["dados"][turno_key][cargo] = {}

        for municipio, g_mun in g_cargo.groupby(COLS["municipio_nome"]):
            # total do município (soma de todas as zonas)
            total_mun = (
                g_mun.groupby([COLS["candidato_nome_urna"], COLS["partido_sigla"]])[COLS["votos"]]
                .sum().reset_index()
                .sort_values(COLS["votos"], ascending=False)
                .head(TOP_N_POR_RECORTE)
            )
            votos_total_mun = g_mun[COLS["votos"]].sum()

            bloco_municipio = {
                "TOTAL": [
                    {"nome": r[COLS["candidato_nome_urna"]],
                     "partido": r[COLS["partido_sigla"]],
                     "votos": int(r[COLS["votos"]]),
                     "pct": round(100 * r[COLS["votos"]] / votos_total_mun, 2) if votos_total_mun else 0}
                    for _, r in total_mun.iterrows()
                ]
            }

            # por zona (relevante principalmente para São Paulo capital)
            for zona, g_zona in g_mun.groupby(COLS["zona"]):
                rank_zona = (
                    g_zona.groupby([COLS["candidato_nome_urna"], COLS["partido_sigla"]])[COLS["votos"]]
                    .sum().reset_index()
                    .sort_values(COLS["votos"], ascending=False)
                    .head(TOP_N_POR_RECORTE)
                )
                votos_total_zona = g_zona[COLS["votos"]].sum()
                bloco_municipio[str(int(zona))] = [
                    {"nome": r[COLS["candidato_nome_urna"]],
                     "partido": r[COLS["partido_sigla"]],
                     "votos": int(r[COLS["votos"]]),
                     "pct": round(100 * r[COLS["votos"]] / votos_total_zona, 2) if votos_total_zona else 0}
                    for _, r in rank_zona.iterrows()
                ]

            resultado["dados"][turno_key][cargo][municipio] = bloco_municipio

    print(f"Turno {turno_key} processado.")

with open("/content/resultados.json", "w", encoding="utf-8") as f:
    json.dump(resultado, f, ensure_ascii=False)

print("Pronto! Arquivo salvo em /content/resultados.json")
print("Tamanho:", os.path.getsize("/content/resultados.json") / 1_000_000, "MB")

# No Colab, baixe o arquivo assim:
from google.colab import files
files.download("/content/resultados.json")
