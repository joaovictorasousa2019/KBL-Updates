# KBL Updates

Repositório central de distribuição e controle de versões dos aplicativos KBL.

## Estrutura

- `manifest.json`: catálogo central dos aplicativos.
- `apps/comparativo-despesas/version.json`: versão do KBL Comparativo de Despesas.
- `apps/composicao-saldos/version.json`: versão do KBL Composição de Saldos.
- `apps/irpj-csll/version.json`: versão do KBL IRPJ e CSLL.
- `apps/fechamento-contabil/version.json`: versão do KBL Fechamento Contábil.

## Fluxo de atualização

1. Gerar o pacote da nova versão.
2. Publicar o pacote da atualização.
3. Atualizar o respectivo `version.json` com versão, arquivo, SHA-256 e notas.
4. O aplicativo consulta o manifesto e compara a versão instalada.
5. Havendo versão nova, o KBL Updater baixa, valida, faz backup e aplica a atualização.

## Segurança

Os dados locais dos usuários não devem ficar dentro da pasta substituída durante a atualização. O atualizador deve validar SHA-256 e manter backup para rollback.
