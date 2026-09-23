#!/bin/bash

cd /var/application/dev01/Discovery-Research-Informatics-DiscoveryAI-BioMAP-Analyzer

# Activate the virtual environment
source mega-venv/bin/activate

# Run your Python scripts
streamlit run MEGA/mega.py --server.address=127.0.0.1 --server.port=8501 > ./mega.log &

# Wait for both to finish (optional)
wait




