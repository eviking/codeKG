# To update: docker pull python:3.12-slim && docker inspect python:3.12-slim --format '{{index .RepoDigests 0}}'
FROM python:3.12.13-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
ENV GIT_AUTHOR_NAME="CodeKG" GIT_AUTHOR_EMAIL="codekg@codekg" \
    GIT_COMMITTER_NAME="CodeKG" GIT_COMMITTER_EMAIL="codekg@codekg"
WORKDIR /app
COPY services/api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/api/ .
COPY shared/ /app/shared/
ENV PYTHONPATH=/app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
