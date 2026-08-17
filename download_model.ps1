# Download the all-MiniLM-L6-v2 sentence-transformer model to D:\models
# Run this in PowerShell on your host machine (NOT in Docker)

Write-Host "Creating D:\models directory..." -ForegroundColor Green
New-Item -ItemType Directory -Path "D:\models\sentence-transformers" -Force | Out-Null

Write-Host "Checking if sentence-transformers is installed..." -ForegroundColor Green
python -c "import sentence_transformers" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing sentence-transformers and torch..." -ForegroundColor Yellow
    pip install sentence-transformers torch
}

Write-Host "Downloading all-MiniLM-L6-v2 model to D:\models (this may take a few minutes, ~100MB)..." -ForegroundColor Green

python -c @"
from sentence_transformers import SentenceTransformer
import sys

try:
    model = SentenceTransformer(
        'sentence-transformers/all-MiniLM-L6-v2',
        cache_folder=r'D:\models'
    )
    print('✓ Model downloaded successfully!')
    print(r'✓ Model location: D:\models\sentence-transformers\all-MiniLM-L6-v2')
    print('✓ You can now start your Docker containers')
except Exception as e:
    print(f'✗ Download failed: {e}')
    sys.exit(1)
"@

if ($LASTEXITCODE -eq 0) {
    Write-Host "Setup complete!" -ForegroundColor Green
} else {
    Write-Host "Download failed!" -ForegroundColor Red
    Exit 1
}
