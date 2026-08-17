FROM ollama/ollama:latest

USER root

COPY backend_fastapi/netskope-ca.crt /usr/local/share/ca-certificates/netskope-ca.crt
RUN update-ca-certificates

# Models will be pulled at runtime on first connection
# Run with: docker exec ollama_service ollama pull mistral:7b
