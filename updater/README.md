# KBL Updater

Atualizador comum dos aplicativos KBL.

## Como o app verifica atualização

O app chama:

```
pythonw kbl_updater.py --manifest-url <URL> --app-dir <PASTA> --local-version <VERSAO> --pid <PID> --restart <EXE>
```

Para apenas consultar:

```
python kbl_updater.py --manifest-url <URL> --app-dir <PASTA> --local-version <VERSAO> --check-only
```

## Regras

- dados do usuário devem ficar fora da pasta substituída;
- pacote deve ser ZIP;
- SHA-256 é obrigatório;
- backup/rollback é criado antes da troca dos arquivos;
- ZIP é validado contra path traversal;
- o app é reiniciado ao final;
- manifestos com `published=false` são ignorados.

## Publicação

1. Gere o ZIP da nova versão.
2. Publique o ZIP em uma GitHub Release.
3. Calcule o SHA-256.
4. Preencha o `version.json` do app.
5. Altere `published` para `true`.
