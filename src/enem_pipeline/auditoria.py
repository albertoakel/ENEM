"""
Auditoria do catálogo de variáveis contra os arquivos do ENEM.

O módulo lê somente os cabeçalhos dos CSVs armazenados nos ZIPs,
sem extrair ou carregar os microdados completos.
"""

import csv
from io import TextIOWrapper
from typing import Dict, List, Set
from zipfile import ZipFile

import pandas as pd

from .catalogo import obter_variaveis_ano
from .config import (
    ANO_FINAL,
    ANO_INICIAL,
    SEPARADOR_MICRODADOS,
)
from .extracao import (
    listar_csvs_ano,
    localizar_zip,
    selecionar_csvs_principais,
)


def ler_cabecalho_csv_zip(
    ano: int,
    caminho_interno: str,
) -> List[str]:
    """
    Lê o cabeçalho de um CSV diretamente do arquivo ZIP.
    """
    caminho_zip = localizar_zip(ano)

    with ZipFile(caminho_zip, mode="r") as arquivo_zip:
        with arquivo_zip.open(
            caminho_interno,
            mode="r",
        ) as arquivo_binario:
            with TextIOWrapper(
                arquivo_binario,
                encoding="latin-1",
                newline="",
            ) as arquivo_texto:
                leitor = csv.reader(
                    arquivo_texto,
                    delimiter=SEPARADOR_MICRODADOS,
                )

                try:
                    cabecalho = next(leitor)
                except StopIteration as erro:
                    raise RuntimeError(
                        f"CSV vazio: {caminho_interno}"
                    ) from erro

    return [
        coluna.lstrip("\ufeff").strip()
        for coluna in cabecalho
    ]


def obter_colunas_principais_ano(
    ano: int,
) -> Set[str]:
    """
    Retorna a união das colunas dos CSVs principais do ano.

    Para 2024–2025, combina os cabeçalhos dos arquivos de
    participantes e resultados.
    """
    arquivos = listar_csvs_ano(ano)

    principais = selecionar_csvs_principais(
        arquivos
    )

    colunas: Set[str] = set()

    for arquivo in principais:
        cabecalho = ler_cabecalho_csv_zip(
            ano=ano,
            caminho_interno=str(
                arquivo["caminho_interno"]
            ),
        )

        colunas.update(cabecalho)

    return colunas


def auditar_ano(
    ano: int,
    catalogo: pd.DataFrame,
) -> Dict[str, object]:
    """
    Compara o catálogo de um ano com os CSVs correspondentes.
    """
    variaveis = obter_variaveis_ano(
        ano=ano,
        catalogo=catalogo,
    )

    colunas_csv = obter_colunas_principais_ano(
        ano=ano
    )

    ausentes = sorted(
        set(variaveis) - colunas_csv
    )

    return {
        "ano": ano,
        "variaveis_catalogo": len(variaveis),
        "colunas_disponiveis": len(colunas_csv),
        "variaveis_ausentes": len(ausentes),
        "lista_ausentes": ausentes,
        "status": (
            "OK"
            if not ausentes
            else "REVISAR"
        ),
        "erro": None,
    }


def auditar_todos_anos(
    catalogo: pd.DataFrame,
) -> pd.DataFrame:
    """
    Audita todas as edições previstas no projeto.
    """
    resultados = []

    for ano in range(
        ANO_INICIAL,
        ANO_FINAL + 1,
    ):
        try:
            resultado = auditar_ano(
                ano=ano,
                catalogo=catalogo,
            )

        except Exception as erro:
            resultado = {
                "ano": ano,
                "variaveis_catalogo": None,
                "colunas_disponiveis": None,
                "variaveis_ausentes": None,
                "lista_ausentes": [],
                "status": "ERRO",
                "erro": str(erro),
            }

        resultados.append(resultado)

    return pd.DataFrame(resultados)