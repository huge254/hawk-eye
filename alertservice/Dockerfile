FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple flask pymysql

COPY app.py .
EXPOSE 8080
CMD ["python", "app.py"]
