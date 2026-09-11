#config.py
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
#
BRONZE_DIR = DATA_DIR / "bronze"
STAGING_DIR = DATA_DIR / "staging"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"
#
METADATA_DIR = DATA_DIR / "metadata"
DICIONARIOS_DIR = METADATA_DIR / "dicionarios"
#
MANIFEST_DIR = BRONZE_DIR / "manifest"

CATALOGO_VARIAVEIS = (
    DICIONARIOS_DIR
    / "variaveis_enem_por_ano.csv"
)

SILVER_MICRODADOS_DIR = (
    SILVER_DIR
    / "microdados_selecionados"
)
#
ANO_INICIAL = 1998
ANO_FINAL = 2025
#
UF_PADRAO = "PA"

SEPARADOR_CATALOGO = ","
SEPARADOR_MICRODADOS = ";"

CODIFICACAO_MICRODADOS_PADRAO = "utf-8"

CODIFICACAO_MICRODADOS_POR_ANO = {
    2006: "latin-1",
    2008: "latin-1",
    2011: "latin-1",
    2012: "latin-1",
    2013: "latin-1",
    2014: "latin-1",
    2015: "latin-1",
    2016: "latin-1",
    2017: "latin-1",
    2018: "latin-1",
    2019: "latin-1",
    2020: "latin-1",
    2021: "latin-1",
    2022: "latin-1",
    2023: "latin-1",
    2024: "latin-1",
    2025: "latin-1",
}