#!/bin/zsh
# load the sample catalogues into the local dev database
cd "$(dirname "$0")"
PY=.venv/bin/python
$PY -m ingest init-db
load() { B=$($PY -m ingest --actor local upload --brand "$1" --profile "$2" --file "$3" | awk '/^batch/{print $2}'); $PY -m ingest --actor local parse --batch $B && $PY -m ingest --actor local apply --batch $B; }
load fras-le fras_le "/Users/ayusharora/Downloads/original/AFF_XL_PRICE_LIST_01.04.26.pdf"
load uno-minda uno_minda "data/pdfs/uno_minda/03_Master Price List 4WH MAR FY 26-27.pdf"
$PY -m ingest snapshot
