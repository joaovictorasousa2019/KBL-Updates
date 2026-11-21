# Frutaverso Studio — TikTok 90 segundos

Aplicativo nativo Windows, EXE unico com atualizacao automatica pelo GitHub.

Download: https://github.com/joaovictorasousa2019/KBL-Updates/releases?q=frutaverso-v

## Uso

1. Abra Frutaverso Studio no Windows, sem CMD.
2. Clique em IMPORTAR ZIP DE ROTEIRO + IMAGENS e escolha um pacote entregue com roteiro e arte.
3. Clique em GERAR VIDEO TIKTOK - 90 SEGUNDOS. O app valida o roteiro e os arquivos, produz vozes Kokoro locais, envia as cenas de acao/narracao ao Wan2.2 local, anima a boca entre imagens fornecidas para os dialogos conforme o envelope de audio, adiciona legendas e monta MP4 vertical.
4. A saida fica em %LOCALAPPDATA%\FrutaversoStudio\dados\saida.

## Especificacoes

- Formato 1080x1920, 24 fps, H.264/AAC, 90 segundos.
- 8 a 30 cenas, cujas duracoes somam exatamente 90 segundos.
- Imagens JPG/PNG/WebP com dimensoes minimas e codigo de roteiro JSON.
- Em cena falada, o pacote deve fornecer imagem de boca fechada, boca aberta e coordenadas da boca. Nao ha preenchimento manual pelo usuario; esses recursos fazem parte do pacote elaborado para o episodio.
- Em cena narrada, o programa produz animacao curta no ComfyUI Wan2.2 e usa loop de ida e volta para cobrir a duracao.
- Vozes Kokoro pt-BR baixadas uma unica vez (aproximadamente 355 MB) e executadas localmente.
- Dados, cache e projetos ficam fora da pasta do executavel, preservados em atualizacoes.

## Qualidade e limites verificados

O CI Windows valida sintaxe, importacao de ZIP de 90s e renderizacao curta com boca reagindo a WAV; compila e publica o EXE. A renderizacao real de 90s com Wan na GPU RTX 4060 Laptop nao pode ser testada no GitHub Actions sem a instalacao local do ComfyUI.

A boca acompanha a energia do audio entre duas imagens, mas NAO e sincronizacao labial fonetica neural (MuseTalk/LatentSync nao estao integrados). Sem imagem aberta/fechada o programa recusa a geracao, em vez de produzir bonecos improvisados. A qualidade final precisa ser avaliada antes da publicacao no TikTok.

## Pacote

Coloque um unico roteiro.json na raiz do ZIP, imagens no subdiretorio imagens/, e em cada cena declare nome, tipo, personagem, duracao, fala, imagem e prompt_movimento. Nas cenas de fala, inclua boca_aberta e regiao_boca no proprio roteiro, preparado pelo assistente. Sao aceitas cenas do tipo fala, narracao e acao.

Licencas: ferramentas de voz e video sao executadas localmente; verifique as licencas de modelos e dependencias aplicaveis. O EXE nao possui assinatura digital e pode gerar alerta SmartScreen.