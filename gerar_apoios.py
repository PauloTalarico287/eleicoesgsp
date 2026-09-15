# =============================================================================
# GERADOR DE APOIOS POR NÚMERO DE PARTIDO - ELEIÇÕES 2026
# Mural de Jornalismo das Periferias
#
# Lê o candidatos_sp_2026.json (já gerado por coleta_candidatos_sp_2026.py) e
# produz um JSON pequeno (apoios.json) que responde, pra cada número de
# partido, quem esse partido apoia pra Presidente e pra Governador — incluindo
# a foto, se já tiver sido baixada pra pasta fotos/.
#
# Por que dá pra fazer isso sem digitar coligação na mão:
# desde a EC 97/2017, não existe mais coligação em eleição proporcional
# (deputado federal/estadual) — só nas majoritárias (presidente, governador,
# senador). Ou seja: o "apoio" de um partido de deputado pra presidente é
# justamente a coligação majoritária da qual esse partido faz parte, e essa
# informação já vem pronta no campo DS_COMPOSICAO_COLIGACAO (aqui renomeado
# pra "coligacao_composicao") de cada candidato a Presidente/Governador.
#
# Rode isso DEPOIS de coleta_candidatos_sp_2026.py, no mesmo diretório
# (precisa do candidatos_sp_2026.json e, se quiser fotos, da pasta fotos/).
# =============================================================================

import json
import re
from datetime import datetime, timezone

ENTRADA = "candidatos_sp_2026.json"
SAIDA = "apoios.json"


def normaliza_sigla(sigla: str) -> str:
    """Uniformiza grafias (ex.: 'PC do B' / 'PCdoB' / 'PC DO B' -> 'PCDOB')."""
    s = sigla.upper().strip()
    s = re.sub(r"[^A-Z0-9]", "", s)  # tira espaço, ponto, hífen etc.
    return s


def extrai_siglas_coligacao(texto_coligacao: str, sigla_propria: str) -> list:
    """
    Quebra o campo de composição da coligação em lista de siglas.
    Formatos que o TSE costuma usar: "PT / PV / PCDOB", "PT-PV-PCDOB",
    "PT, PV, PCDOB". Se vier vazio (candidatura solo), usa só a sigla
    do próprio partido.
    """
    if not texto_coligacao or not str(texto_coligacao).strip():
        return [sigla_propria]
    partes = re.split(r"[\/,]|(?:\s-\s)", str(texto_coligacao))
    siglas = [normaliza_sigla(p) for p in partes if p.strip()]
    return siglas or [sigla_propria]


def monta_numero_por_sigla(candidatos: list) -> dict:
    """
    Descobre o número de cada partido olhando os candidatos a deputado
    federal/estadual (o número de urna deles sempre começa com o número
    do partido). Prefere deputado federal; usa estadual como reforço/checagem.
    """
    numero_por_sigla = {}
    for c in candidatos:
        if c.get("cargo") not in ("DEPUTADO FEDERAL", "DEPUTADO ESTADUAL"):
            continue
        sigla = normaliza_sigla(c.get("partido_sigla", ""))
        numero = str(c.get("numero", "")).strip()
        if not sigla or len(numero) < 2:
            continue
        numero_partido = numero[:2]
        # Se já vimos essa sigla com outro número (não deveria acontecer,
        # mas é uma checagem de sanidade), mantém o primeiro e avisa.
        if sigla in numero_por_sigla and numero_por_sigla[sigla] != numero_partido:
            print(
                f"[aviso] sigla {sigla} apareceu com números de partido "
                f"diferentes: {numero_por_sigla[sigla]} e {numero_partido}"
            )
            continue
        numero_por_sigla[sigla] = numero_partido
    return numero_por_sigla


def monta_candidatos_por_numero(candidatos: list) -> dict:
    """
    Mapeia numero_completo (string) -> dados do candidato, só pra
    deputado federal e estadual (que é quem tem "seu número" no sentido
    da ferramenta). Como o JSON é só de SP, o número completo já é
    suficiente pra identificar sem ambiguidade dentro do estado.
    """
    por_numero = {}
    for c in candidatos:
        if c.get("cargo") not in ("DEPUTADO FEDERAL", "DEPUTADO ESTADUAL"):
            continue
        numero = str(c.get("numero", "")).strip()
        if not numero:
            continue
        por_numero[numero] = {
            "nome_urna": c.get("nome_urna"),
            "partido_sigla": c.get("partido_sigla"),
            "cargo": c.get("cargo"),
            "foto": c.get("foto"),
        }
    return por_numero


def monta_apoios(candidatos: list, numero_por_sigla: dict) -> dict:
    """
    Pra cada candidato a Presidente/Governador, mapeia todos os partidos da
    coligação dele -> esse candidato. Retorna dict numero_partido -> registro.
    """
    apoios = {}

    for cargo_alvo, chave in (("PRESIDENTE", "presidente"), ("GOVERNADOR", "governador")):
        candidatos_cargo = [c for c in candidatos if c.get("cargo") == cargo_alvo]
        for c in candidatos_cargo:
            sigla_propria = normaliza_sigla(c.get("partido_sigla", ""))
            siglas_coligacao = extrai_siglas_coligacao(
                c.get("coligacao_composicao", ""), sigla_propria
            )
            registro = {
                "nome_urna": c.get("nome_urna"),
                "partido_sigla": c.get("partido_sigla"),
                "numero_candidato": c.get("numero"),
                "foto": c.get("foto"),
            }
            for sigla in siglas_coligacao:
                numero_partido = numero_por_sigla.get(sigla)
                if not numero_partido:
                    print(
                        f"[aviso] não achei o número do partido {sigla} "
                        f"(coligação de {c.get('nome_urna')}, {cargo_alvo}). "
                        f"Pulei essa sigla — confira manualmente."
                    )
                    continue
                apoios.setdefault(numero_partido, {})[chave] = registro

    return apoios


def main():
    with open(ENTRADA, "r", encoding="utf-8") as f:
        dados = json.load(f)

    candidatos = dados.get("candidatos", dados) if isinstance(dados, dict) else dados

    numero_por_sigla = monta_numero_por_sigla(candidatos)
    apoios = monta_apoios(candidatos, numero_por_sigla)
    candidatos_por_numero = monta_candidatos_por_numero(candidatos)

    saida = {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "fonte": ENTRADA,
        "total_partidos_mapeados": len(apoios),
        "total_candidatos_deputado": len(candidatos_por_numero),
        "apoios": apoios,
        "candidatos": candidatos_por_numero,
    }

    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    print(f"\n{len(apoios)} números de partido mapeados. Salvo em {SAIDA}.")
    faltando = [n for n in apoios if "presidente" not in apoios[n]]
    if faltando:
        print(f"[aviso] partidos sem apoio pra presidente identificado: {faltando}")


if __name__ == "__main__":
    main()
