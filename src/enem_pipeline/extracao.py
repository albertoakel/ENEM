#extração.py
"""
Rotinas de inspeção e extração dos microdados do ENEM.

Este módulo localiza os arquivos ZIP armazenados na camada Bronze,
identifica os CSVs internos e extrai somente os arquivos necessários
para o processamento.

Layouts reconhecidos:
- 1998 a 2023: MICRODADOS_ENEM_AAAA.csv;
- 2024 e 2025: PARTICIPANTES_AAAA.csv e RESULTADOS_AAAA.csv.

Arquivos de itens de prova e questionários são identificados, mas
não são extraídos pela rotina principal.

A extração é realizada na área temporária `data/staging/ano_AAAA`.
Os arquivos originais da Bronze não são modificados.
"""

from pathlib import Path, PurePosixPath
from typing import Dict, List
from zipfile import BadZipFile, ZipFile
import shutil

from .config import (
    ANO_FINAL,
    ANO_INICIAL,
    BRONZE_DIR,
    STAGING_DIR,
)


def validar_ano(ano: int) -> None:
    """
    Verifica se o ano está dentro do intervalo do projeto.
    """
    if not ANO_INICIAL <= ano <= ANO_FINAL:
        raise ValueError(
            f"Ano inválido: {ano}. "
            f"Intervalo permitido: "
            f"{ANO_INICIAL}-{ANO_FINAL}."
        )


def localizar_zip(ano: int) -> Path:
    """
    Localiza o arquivo ZIP correspondente ao ano.
    """
    validar_ano(ano)

    caminho_zip = (
        BRONZE_DIR
        / f"microdados_enem_{ano}.zip"
    )

    if not caminho_zip.exists():
        raise FileNotFoundError(
            f"ZIP não encontrado: {caminho_zip}"
        )

    return caminho_zip


def classificar_csv(caminho_interno: str) -> str:
    """
    Classifica um CSV de acordo com seu nome.
    """
    nome = PurePosixPath(
        caminho_interno
    ).name.upper()

    if "PARTICIPANTES" in nome:
        return "participantes"

    if "RESULTADOS" in nome:
        return "resultados"

    if "MICRODADOS_ENEM" in nome:
        return "microdados"

    if "ITENS_PROVA" in nome:
        return "itens_prova"

    if nome.startswith("QUEST_"):
        return "questionario"

    return "csv_desconhecido"


def listar_csvs_ano(ano: int) -> List[Dict[str, object]]:
    """
    Lista e classifica todos os CSVs de uma edição.
    """
    caminho_zip = localizar_zip(ano)
    registros = []

    try:
        with ZipFile(
            caminho_zip,
            mode="r",
        ) as arquivo_zip:

            for info in arquivo_zip.infolist():

                if info.is_dir():
                    continue

                if not info.filename.lower().endswith(
                    ".csv"
                ):
                    continue

                registros.append(
                    {
                        "ano": ano,
                        "arquivo_zip": caminho_zip.name,
                        "caminho_interno": info.filename,
                        "nome_csv": PurePosixPath(
                            info.filename
                        ).name,
                        "tipo": classificar_csv(
                            info.filename
                        ),
                        "tamanho_bytes": info.file_size,
                        "tamanho_mb": (
                            info.file_size / 1024**2
                        ),
                    }
                )

    except BadZipFile as erro:
        raise BadZipFile(
            f"Arquivo ZIP inválido: {caminho_zip}"
        ) from erro

    if not registros:
        raise FileNotFoundError(
            f"Nenhum CSV encontrado em: "
            f"{caminho_zip}"
        )

    return registros


def selecionar_csvs_principais(arquivos: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """
    Seleciona os CSVs principais de uma edição.
    """
    microdados = [
        arquivo
        for arquivo in arquivos
        if arquivo["tipo"] == "microdados"
    ]

    participantes = [
        arquivo
        for arquivo in arquivos
        if arquivo["tipo"] == "participantes"
    ]

    resultados = [
        arquivo
        for arquivo in arquivos
        if arquivo["tipo"] == "resultados"
    ]

    if participantes or resultados:
        if (
            len(participantes) != 1
            or len(resultados) != 1
        ):
            raise RuntimeError(
                "Layout separado incompleto. "
                "Era esperado um arquivo de participantes "
                "e um arquivo de resultados."
            )

        return [
            participantes[0],
            resultados[0],
        ]

    if len(microdados) == 1:
        return microdados

    raise RuntimeError(
        "Não foi possível identificar "
        "o conjunto principal de CSVs."
    )


def extrair_csvs_principais(ano: int,reutilizar_existentes: bool = True) -> List[Path]:
    """
    Extrai os CSVs principais para o staging.

    Se um arquivo já existir e tiver o tamanho esperado,
    ele poderá ser reutilizado. Arquivos divergentes nunca
    são sobrescritos automaticamente.
    """
    caminho_zip = localizar_zip(ano)

    arquivos = listar_csvs_ano(ano)

    arquivos_principais = (
        selecionar_csvs_principais(arquivos)
    )

    diretorio_destino = (
        STAGING_DIR
        / f"ano_{ano}"
    )

    diretorio_destino.mkdir(
        parents=True,
        exist_ok=True,
    )

    destinos = []

    for arquivo in arquivos_principais:
        destino = (
            diretorio_destino
            / str(arquivo["nome_csv"])
        )

        if destino.exists():
            tamanho_atual = destino.stat().st_size
            tamanho_esperado = int(
                arquivo["tamanho_bytes"]
            )

            if tamanho_atual != tamanho_esperado:
                raise RuntimeError(
                    f"Arquivo existente com tamanho "
                    f"divergente: {destino}"
                )

            if not reutilizar_existentes:
                raise FileExistsError(
                    f"O arquivo já existe: {destino}"
                )

        destinos.append(destino)

    tamanho_pendente = sum(
        int(arquivo["tamanho_bytes"])
        for arquivo, destino
        in zip(arquivos_principais, destinos)
        if not destino.exists()
    )

    espaco_disponivel = shutil.disk_usage(
        STAGING_DIR
    ).free

    if (
        tamanho_pendente > 0
        and espaco_disponivel
        < tamanho_pendente * 1.2
    ):
        raise OSError(
            "Espaço insuficiente para a extração."
        )

    with ZipFile(
        caminho_zip,
        mode="r",
    ) as arquivo_zip:

        for arquivo, destino in zip(
            arquivos_principais,
            destinos,
        ):
            if destino.exists():
                continue

            caminho_interno = str(
                arquivo["caminho_interno"]
            )

            try:
                with arquivo_zip.open(
                    caminho_interno,
                    mode="r",
                ) as origem:

                    with destino.open("xb") as saida:
                        shutil.copyfileobj(
                            origem,
                            saida,
                            length=16 * 1024**2,
                        )

            except Exception:
                if destino.exists():
                    destino.unlink()

                raise

            tamanho_extraido = (
                destino.stat().st_size
            )

            tamanho_esperado = int(
                arquivo["tamanho_bytes"]
            )

            if tamanho_extraido != tamanho_esperado:
                destino.unlink()

                raise RuntimeError(
                    f"Tamanho divergente após "
                    f"extração: {destino}"
                )

    return destinos