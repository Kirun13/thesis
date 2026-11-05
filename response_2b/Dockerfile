FROM python:3.13.5-slim-bookworm
ENV PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
RUN apt-get update && apt-get install -y --no-install-recommends iproute2 iptables \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch==2.9.1+cpu --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir numpy==2.3.5
WORKDIR /app
COPY lab_2b.py /app/lab_2b.py
CMD ["python", "lab_2b.py", "edge"]
