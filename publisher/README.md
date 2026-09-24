# Publicação de atualizações

O repositório público distribui somente manifestos e pacotes de atualização. O código-fonte dos aplicativos não precisa ficar aqui.

## Primeira configuração na máquina que publica

1. Instale o GitHub CLI (gh).
2. Execute uma vez: gh auth login.
3. Use o script PUBLICAR_ATUALIZACAO.ps1.

## Exemplo

powershell .\PUBLICAR_ATUALIZACAO.ps1 -AppId "comparativo-despesas" -Version "3.9.22" -ZipPath "C:\KBL\Builds\KBL_Comparativo_Despesas_v3_9_22.zip"

O script calcula SHA-256, cria ou atualiza a GitHub Release, monta a URL pública e atualiza o version.json automaticamente.

## IDs atuais

- comparativo-despesas
- composicao-saldos
- conciliador-contabil
- irpj-csll
- fechamento-contabil
