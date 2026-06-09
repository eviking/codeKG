# To update: docker pull python:3.12-slim && docker inspect python:3.12-slim --format '{{index .RepoDigests 0}}'
FROM python:3.12.13-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203
WORKDIR /app
RUN apt-get update && apt-get install -y git gcc && rm -rf /var/lib/apt/lists/*
COPY services/ingestion/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Build tree-sitter-sfapex (Salesforce Apex) grammar from source — no PyPI package exists
RUN git clone --depth=1 https://github.com/aheber/tree-sitter-sfapex.git /tmp/tree-sitter-sfapex \
    && gcc -shared -fPIC -o /usr/local/lib/tree_sitter_apex.so \
       /tmp/tree-sitter-sfapex/apex/src/parser.c \
    && rm -rf /tmp/tree-sitter-sfapex
COPY services/ingestion/ .
COPY shared/ /app/shared/
ENV PYTHONPATH=/app
# Default: run the minimal web service (claude-md/refresh endpoint)
# Override CMD to "python run_scan.py" for ephemeral scan jobs
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
