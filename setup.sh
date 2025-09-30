#!/bin/bash
set -e

# create a venv
cd methods/spider-agent-dbt
uv venv --clear
uv pip install -r requirements.txt
source .venv/bin/activate

# return to main directory
cd ../..

# Run the setup
cd spider2-dbt

if [ ! -f "DBT_start_db.zip" ]; then
    echo "Downloading DBT_start_db.zip"
    gdown https://drive.google.com/uc?id=1N3f7BSWC4foj-V-1C9n8M2XmgV7FOcqL
fi
if [ ! -f "dbt_gold.zip" ]; then
    echo "Downloading dbt_gold.zip"
    gdown https://drive.google.com/uc?id=1s0USV_iQLo4oe05QqAMnhGGp5jeejCzp
fi

python setup.py
