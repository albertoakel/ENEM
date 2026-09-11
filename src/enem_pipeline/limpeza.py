"""
Limpeza segura dos CSVs extraídos no staging.

Somente os arquivos principais de uma edição são removidos,
e apenas quando as respectivas Silver já existem.

Os arquivos ZIP da camada Bronze nunca são removidos.
"""

from pathlib import Path
from typing import Dict, List

from .config import STAGING_DIR
from .extracao import (
    listar_csvs_ano,
    selecionar_csvs_principais,
)
from .gravacao import (
    construir_caminho_parquet,
    construir_caminho_parquet_separado,
)


def obter_silvers_esperadas(
    ano: int,
    uf: str,
) -> List[Path]:
    """
    Retorna os Parquets esperados para uma edição.
    """
    if ano >= 2024:
        return [
            construir_caminho_parquet_separado(
                ano=ano,
                uf=uf,
                base="participantes",
            ),
            construir_caminho_parquet_separado(
                ano=ano,
                uf=uf,
                base="resultados",
            ),
        ]

    return [
        construir_caminho_parquet(
            ano=ano,
            uf=uf,
        )
    ]


def verificar_silvers(
    ano: int,
    uf: str,
) -> List[Path]:
    """
    Confirma que todas as Silver existem e não estão vazias.
    """
    silvers = obter_silvers_esperadas(
        ano=ano,
        uf=uf,
    )

    invalidas = [
        arquivo
        for arquivo in silvers
        if (
            not arquivo.exists()
            or arquivo.stat().st_size == 0
        )
    ]

    if invalidas:
        raise RuntimeError(
            "A limpeza foi bloqueada porque existem "
            f"Silver ausentes ou vazias: {invalidas}"
        )

    return silvers


def limpar_staging_ano(
    ano: int,
    uf: str,
    simular: bool = True,
) -> Dict[str, object]:
    """
    Remove os CSVs principais extraídos de uma edição.

    Por padrão, apenas simula a operação.
    """
    silvers = verificar_silvers(
        ano=ano,
        uf=uf,
    )

    arquivos_zip = listar_csvs_ano(
        ano
    )

    principais = selecionar_csvs_principais(
        arquivos_zip
    )

    diretorio_ano = (
        STAGING_DIR
        / f"ano_{ano}"
    )

    candidatos = []

    for arquivo in principais:
        caminho = (
            diretorio_ano
            / str(arquivo["nome_csv"])
        )

        if not caminho.exists():
            continue

        # Impede que um caminho fora do staging seja removido.
        if (
            caminho.resolve().parent
            != diretorio_ano.resolve()
        ):
            raise RuntimeError(
                f"Caminho inseguro: {caminho}"
            )

        candidatos.append(
            caminho
        )

    tamanho_bytes = sum(
        arquivo.stat().st_size
        for arquivo in candidatos
    )

    removidos = []

    if not simular:
        for arquivo in candidatos:
            arquivo.unlink()
            removidos.append(
                arquivo
            )

        # Remove somente se o diretório estiver vazio.
        if (
            diretorio_ano.exists()
            and not any(
                diretorio_ano.iterdir()
            )
        ):
            diretorio_ano.rmdir()

    return {
        "ano": ano,
        "uf": uf.strip().upper(),
        "simulacao": simular,
        "silvers_verificadas": silvers,
        "arquivos_encontrados": candidatos,
        "arquivos_removidos": removidos,
        "espaco_mb": (
            tamanho_bytes / 1024**2
        ),
    }