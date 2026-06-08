# To update: docker pull python:3.12-slim && docker inspect python:3.12-slim --format '{{index .RepoDigests 0}}'
FROM python:3.12.13-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203
WORKDIR /app
COPY services/mcp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY services/mcp/ .
COPY shared/ /app/shared/
ENV PYTHONPATH=/app
CMD ["python", "main.py"]
