# Integração no KBL Fechamento Contábil v2.6

A v2.6 continua sendo a base funcional. O módulo de atualização é aditivo.

## Arquivos a colocar ao lado do app

- `kbl_update_center.py`
- `kbl_updater.py`

## Botão no Hub

Importe:

```python
from kbl_update_center import open_update_center
```

No botão **Atualizações**:

```python
open_update_center(root)
```

Use o objeto raiz Tk real do aplicativo no lugar de `root`, caso o projeto use outro nome.

## Registro local

O centro usa:

`%APPDATA%\KBLAccounting\Updates\registry.json`

Cada aplicativo pode ser cadastrado assim:

```json
{
  "schema_version": 1,
  "apps": {
    "comparativo-despesas": {
      "install_dir": "C:/KBL/Comparativo",
      "entrypoint": "Abrir KBL Comparativo.pyw",
      "version": "3.9.21"
    }
  }
}
```

Quando o app tiver `version.json` dentro da pasta instalada, a versão desse arquivo prevalece.

## Dados

O atualizador não deve substituir bancos, histórico ou configuração do usuário. A recomendação continua sendo manter esses dados em `%APPDATA%\KBLAccounting\...`.

## Repositório

O `KBL-Updates` precisa ficar público para que os aplicativos baixem `manifest.json` sem armazenar token do GitHub no computador.
