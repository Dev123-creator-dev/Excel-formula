#!/bin/bash
echo "Starting MEGA."
cd /var/application/prod/mega
source venv/bin/activate
pip install --default-timeout=99999 -r requirements.txt
streamlit run mega.py --server.address=127.0.0.1 --server.port=8501 > ./mega.log &
wait