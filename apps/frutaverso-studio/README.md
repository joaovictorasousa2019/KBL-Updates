# Frutaverso Studio

Aplicativo Windows (.exe) para gerar videos verticais com Wan 2.2 / ComfyUI local, montar vozes e legendas e salvar MP4.

**Download permanente:** https://github.com/joaovictorasousa2019/KBL-Updates/releases?q=frutaverso-v

**Instalacao uma unica vez:** baixe o arquivo FrutaversoStudio.exe da versao mais recente e execute por duplo clique. O aplicativo copia a si mesmo para %LOCALAPPDATA%\FrutaversoStudio\app, cria atalho Frutaverso Studio na area de trabalho e passa a verificar novas versoes na abertura, sem CMD. Instalacao sem administrador.

**Atualizacoes:** para publicar uma nova versao, altere a constante VERSION (por exemplo, 0.4.0 -> 0.4.1) em source/frutaverso.py e envie o commit para main. O workflow build-frutaverso-studio.yml compila no Windows e publica o EXE e o SHA256 em um release publico separado pelo prefixo frutaverso-v. No inicio, o app verifica os releases, baixa, valida a integridade SHA256, substitui o executavel instalado e reinicia. Nao modifica o catalogo dos outros aplicativos KBL.

**Dados persistentes:** %LOCALAPPDATA%\FrutaversoStudio\dados\ inclui episodios, imagens, cache das animacoes e videos finais. Nenhuma atualizacao apaga esses dados. Na primeira execucao, o app tenta importar automaticamente as tres imagens da pasta extraida do Frutaverso v0.2/v0.3 nos diretorios Downloads, Desktop e Documents. Se nao encontrar, disponibiliza imagens demonstrativas e permite escolher imagens reais pela interface.

**Requisitos:** Windows 10/11 x64, ComfyUI Desktop previamente configurado com Wan 2.2 TI2V 5B e seus modelos, placa NVIDIA (recomendacao do piloto: RTX 4060 8 GB), espaco livre, memoria RAM suficiente e acesso a internet somente para verificar/baixar atualizacoes. Nao precisa instalar Python nem abrir terminal para utilizar o EXE. FFmpeg e componentes de edicao sao incluidos pelo PyInstaller.

**Voz:** usa sintese offline do Windows (SAPI). A qualidade e o idioma dependem das vozes instaladas no Windows; sincronizacao labial realista ainda nao foi implementada.

**Observacoes:** como o executavel nao possui assinatura digital, o SmartScreen do Windows podera exibir alerta. Os downloads so sao aceitos dos releases do proprio repositorio e sao verificados por SHA-256. Para a primeira producao, o ComfyUI deve estar instalado e com a API local funcional. O aplicativo inicia o ComfyUI se o localizar e controla as cenas pela API; nao precisa operar workflows manualmente.
