"""
Gera resultados.json (votação 2022 por zona/município na RMSP), com o campo
"eleito" corrigido.

BUG QUE ESTE SCRIPT CORRIGE:
"NÃO ELEITO" contém a substring "ELEITO", então uma checagem ingênua como
`"ELEITO" in situacao.upper()` marca candidatos derrotados como eleitos.
Aqui a função eh_eleito() exclui esse caso explicitamente.
"""

import io
import json
import os
import unicodedata
import zipfile

import pandas as pd
import requests

URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_2022.zip"
DEST = "dados_tse"
SAIDA = "resultados.json"

COLS = {
    "turno": "NR_TURNO",
    "municipio_cod": "CD_MUNICIPIO",
    "municipio_nome": "NM_MUNICIPIO",
    "zona": "NR_ZONA",
    "cargo": "DS_CARGO",
    "candidato_nome_urna": "NM_URNA_CANDIDATO",
    "partido_sigla": "SG_PARTIDO",
    "votos": "QT_VOTOS_NOMINAIS",
    "situacao": "DS_SIT_TOT_TURNO",
}

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

TOP_N_POR_RECORTE = 30


def normaliza(s):
    s = str(s).upper().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    return s


def eh_eleito(situacao):
    s = normaliza(situacao)
    return "ELEITO" in s and "NAO ELEITO" not in s


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


def baixar_e_extrair():
    os.makedirs(DEST, exist_ok=True)
    print("Baixando (arquivo nacional, pode demorar)...")
    r = requests.get(URL, headers=HEADERS, timeout=300)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    z.extractall(DEST)
    print("Arquivos extraídos:", sorted(os.listdir(DEST)))


def caminho_csv_sp():
    candidatos = [f for f in os.listdir(DEST) if f.upper().endswith("SP.CSV")]
    if not candidatos:
        raise FileNotFoundError(f"Nenhum CSV *SP.csv encontrado em {DEST}: {os.listdir(DEST)}")
    return os.path.join(DEST, candidatos[0])


def gerar():
    caminho = caminho_csv_sp()
    print("Lendo:", caminho)
    df = pd.read_csv(caminho, sep=";", encoding="latin-1", usecols=list(COLS.values()))

    df["_municipio_norm"] = df[COLS["municipio_nome"]].apply(normaliza)
    municipios_rmsp_norm = set(normaliza(m) for m in MUNICIPIOS_RMSP)
    df_rmsp = df[df["_municipio_norm"].isin(municipios_rmsp_norm)].copy()
    print(f"Linhas após filtro RMSP: {len(df_rmsp)} de {len(df)} originais")

    resultado = {
        "meta": {
            "fonte": "TSE - votacao_candidato_munzona_2022",
            "gerado_em": pd.Timestamp.now().isoformat(),
        },
        "dados": {},
    }

    for turno, g_turno in df_rmsp.groupby(COLS["turno"]):
        turno_key = str(int(turno))
        resultado["dados"][turno_key] = {}

        for cargo, g_cargo in g_turno.groupby(COLS["cargo"]):
            resultado["dados"][turno_key][cargo] = {}

            for municipio, g_mun in g_cargo.groupby(COLS["municipio_nome"]):
                total_mun = (
                    g_mun.groupby([COLS["candidato_nome_urna"], COLS["partido_sigla"]])
                    .agg(votos=(COLS["votos"], "sum"), situacao=(COLS["situacao"], "first"))
                    .reset_index()
                    .sort_values("votos", ascending=False)
                    .head(TOP_N_POR_RECORTE)
                )
                votos_total_mun = g_mun[COLS["votos"]].sum()

                bloco_municipio = {
                    "TOTAL": [
                        {
                            "nome": r[COLS["candidato_nome_urna"]],
                            "partido": r[COLS["partido_sigla"]],
                            "votos": int(r["votos"]),
                            "pct": round(100 * r["votos"] / votos_total_mun, 2) if votos_total_mun else 0,
                            "eleito": eh_eleito(r["situacao"]),
                        }
                        for _, r in total_mun.iterrows()
                    ]
                }

                for zona, g_zona in g_mun.groupby(COLS["zona"]):
                    rank_zona = (
                        g_zona.groupby([COLS["candidato_nome_urna"], COLS["partido_sigla"]])
                        .agg(votos=(COLS["votos"], "sum"), situacao=(COLS["situacao"], "first"))
                        .reset_index()
                        .sort_values("votos", ascending=False)
                        .head(TOP_N_POR_RECORTE)
                    )
                    votos_total_zona = g_zona[COLS["votos"]].sum()
                    bloco_municipio[str(int(zona))] = [
                        {
                            "nome": r[COLS["candidato_nome_urna"]],
                            "partido": r[COLS["partido_sigla"]],
                            "votos": int(r["votos"]),
                            "pct": round(100 * r["votos"] / votos_total_zona, 2) if votos_total_zona else 0,
                            "eleito": eh_eleito(r["situacao"]),
                        }
                        for _, r in rank_zona.iterrows()
                    ]

                resultado["dados"][turno_key][cargo][municipio] = bloco_municipio

        print(f"Turno {turno_key} processado.")

    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False)
    print("Salvo em", SAIDA, "-", os.path.getsize(SAIDA) / 1_000_000, "MB")

    # Checagem automática: se o bug ainda estiver presente, isso aparece claro no log.
    for turno_key, cargos in resultado["dados"].items():
        for cargo in ("Presidente", "Governador", "Senador"):
            if cargo not in cargos:
                continue
            mun_amostra = next(iter(cargos[cargo]))
            total = cargos[cargo][mun_amostra]["TOTAL"]
            n_eleitos = sum(1 for c in total if c["eleito"])
            print(f"Checagem — Turno {turno_key} · {cargo} · {mun_amostra}: {n_eleitos} eleito(s) de {len(total)}")


if __name__ == "__main__":
    baixar_e_extrair()
    gerar()
