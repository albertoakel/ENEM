"""
Gravação dos dados transformados na camada Silver.

Layouts:

1998–2023:
    microdados_selecionados/
        ano=AAAA/
            uf=UF/
                enem_UF_AAAA.parquet

2024–2025:
    participantes/
        ano=AAAA/
            uf=UF/
                participantes_UF_AAAA.parquet

    resultados/
        ano=AAAA/
            uf=UF/
                resultados_UF_AAAA.parquet
"""

from pathlib import Path
from uuid import uuid4

import duckdb

from .config import (
    ANO_FINAL,
    ANO_INICIAL,
    SILVER_DIR,
)
from .leitura import (
    citar_identificador,
    escapar_texto_sql,
    validar_nome_view,
)


BASES_SEPARADAS = {
    "participantes",
    "resultados",
}


def validar_ano_uf(
    ano: int,
    uf: str,
) -> str:
    """
    Valida o ano e normaliza a sigla da UF.
    """
    if not ANO_INICIAL <= ano <= ANO_FINAL:
        raise ValueError(
            f"Ano inválido: {ano}. "
            f"Intervalo permitido: "
            f"{ANO_INICIAL}-{ANO_FINAL}."
        )

    uf = uf.strip().upper()

    if len(uf) != 2 or not uf.isalpha():
        raise ValueError(
            f"Sigla de UF inválida: {uf}"
        )

    return uf


def construir_caminho_parquet(
    ano: int,
    uf: str,
) -> Path:
    """
    Constrói o caminho da Silver unificada de 1998–2023.
    """
    uf = validar_ano_uf(
        ano=ano,
        uf=uf,
    )

    return (
        SILVER_DIR
        / "microdados_selecionados"
        / f"ano={ano}"
        / f"uf={uf}"
        / f"enem_{uf}_{ano}.parquet"
    )


def construir_caminho_parquet_separado(
    ano: int,
    uf: str,
    base: str,
) -> Path:
    """
    Constrói o caminho de uma Silver separada.

    Bases aceitas:
    - participantes;
    - resultados.
    """
    uf = validar_ano_uf(
        ano=ano,
        uf=uf,
    )

    if ano < 2024:
        raise ValueError(
            "O layout separado é válido somente "
            "a partir de 2024."
        )

    base = base.strip().lower()

    if base not in BASES_SEPARADAS:
        raise ValueError(
            f"Base separada inválida: {base}"
        )

    return (
        SILVER_DIR
        / base
        / f"ano={ano}"
        / f"uf={uf}"
        / f"{base}_{uf}_{ano}.parquet"
    )


def contar_registros_parquet(
    conexao: duckdb.DuckDBPyConnection,
    arquivo_parquet: Path,
) -> int:
    """
    Conta os registros de um arquivo Parquet.
    """
    if not arquivo_parquet.exists():
        raise FileNotFoundError(
            f"Parquet não encontrado: "
            f"{arquivo_parquet}"
        )

    caminho_sql = escapar_texto_sql(
        str(arquivo_parquet)
    )

    resultado = conexao.execute(
        f"""
        SELECT COUNT(*)
        FROM read_parquet(
            '{caminho_sql}'
        )
        """
    ).fetchone()

    return int(resultado[0])


def gravar_no_destino(
    conexao: duckdb.DuckDBPyConnection,
    nome_view: str,
    destino: Path,
    sobrescrever: bool = False,
) -> Path:
    """
    Grava uma view ou tabela em um destino Parquet.

    A escrita é realizada primeiro em um arquivo
    temporário e validada antes da movimentação.
    """
    validar_nome_view(nome_view)

    destino.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if destino.exists() and not sobrescrever:
        raise FileExistsError(
            f"O arquivo já existe: {destino}"
        )

    origem_sql = citar_identificador(
        nome_view
    )

    total_origem = conexao.execute(
        f"""
        SELECT COUNT(*)
        FROM {origem_sql}
        """
    ).fetchone()[0]

    if total_origem == 0:
        raise RuntimeError(
            f"A origem {nome_view} "
            "não possui registros."
        )

    temporario = destino.with_name(
        f".{destino.stem}_"
        f"{uuid4().hex}.tmp.parquet"
    )

    temporario_sql = escapar_texto_sql(
        str(temporario)
    )

    try:
        conexao.execute(
            f"""
            COPY (
                SELECT *
                FROM {origem_sql}
            )
            TO '{temporario_sql}'
            (
                FORMAT PARQUET,
                COMPRESSION ZSTD
            )
            """
        )

        total_gravado = contar_registros_parquet(
            conexao=conexao,
            arquivo_parquet=temporario,
        )

        if total_gravado != total_origem:
            raise RuntimeError(
                "Quantidade de registros divergente: "
                f"origem={total_origem}, "
                f"Parquet={total_gravado}."
            )

        if destino.exists():
            if sobrescrever:
                destino.unlink()
            else:
                raise FileExistsError(
                    f"O arquivo já existe: {destino}"
                )

        temporario.rename(
            destino
        )

    except Exception:
        if temporario.exists():
            temporario.unlink()

        raise

    return destino


def gravar_parquet(
    conexao: duckdb.DuckDBPyConnection,
    nome_view: str,
    ano: int,
    uf: str,
    sobrescrever: bool = False,
) -> Path:
    """
    Grava a Silver unificada de 1998–2023.
    """
    destino = construir_caminho_parquet(
        ano=ano,
        uf=uf,
    )

    return gravar_no_destino(
        conexao=conexao,
        nome_view=nome_view,
        destino=destino,
        sobrescrever=sobrescrever,
    )


def gravar_parquet_separado(
    conexao: duckdb.DuckDBPyConnection,
    nome_view: str,
    ano: int,
    uf: str,
    base: str,
    sobrescrever: bool = False,
) -> Path:
    """
    Grava uma base separada de 2024–2025.
    """
    destino = (
        construir_caminho_parquet_separado(
            ano=ano,
            uf=uf,
            base=base,
        )
    )

    return gravar_no_destino(
        conexao=conexao,
        nome_view=nome_view,
        destino=destino,
        sobrescrever=sobrescrever,
    )