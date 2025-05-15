FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip setuptools && \
    pip install --no-cache-dir --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt

COPY . .

CMD ["python", "main.py"]