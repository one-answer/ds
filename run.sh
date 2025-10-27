conda create -n ds python=3.10
conda activate ds
pip install -r requirements.txt
nohup env PYTHONUNBUFFERED=1 python deepseek_ok_plus.py > ./app.log 2>&1 &