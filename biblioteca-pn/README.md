# Biblioteca de PNs — insertos e parafusos por peça

Ferramenta de consulta (e cadastro) que mostra, para cada **peça (PN)**, qual **inserto** é usado
por boa prática e quais **parafusos** são indicados com esse inserto.

```
Conjunto (ex.: Overhead Bin)
└── Peça            CDPA689
    └── Rosca       8-32
        ├── Inserto CDIN07-08-06  ★ preferencial (opcional)
        │   ├── Parafuso NAS514P832-3P  (CSK · escareada)
        │   └── Parafuso NAS8302-3      (PAN · panela)
        └── Inserto CDIN23-08S
```

## Como usar

É **um único arquivo**: `Biblioteca_PN.html`. Abra com um duplo clique (Edge/Chrome). Não precisa
de instalação, servidor nem internet.

| O que fazer | Como |
|---|---|
| Achar um PN | Digite na busca do topo (atalho **/** ou **Ctrl+K**). Pode digitar parte do PN, sem hífen (`nas8302`). |
| Ver onde um inserto/parafuso é usado | Clique no PN do inserto ou parafuso para abrir a página com a seção **Onde é usado**. |
| Copiar um PN | Passe o mouse sobre o PN e clique no ícone de copiar. |
| Levar a tabela para o Excel | Na página da peça, use **Copiar tabela** e cole no Excel. |
| Cadastrar ou editar | Ative o **Modo edição** (topo à direita). Aparecem os botões de adicionar, editar e excluir. |
| Compartilhar com a equipe | **Dados › Salvar como HTML** gera um novo arquivo com os dados gravados dentro. Envie esse arquivo ou coloque no SharePoint. |

### Onde ficam os dados?

- Os dados "oficiais" ficam **dentro do próprio HTML** (bloco `<script id="seed-data">`).
- O que você edita no navegador fica salvo **só no seu navegador** até você usar
  **Dados › Salvar como HTML**. O aviso laranja na barra lateral lembra disso.
- **Dados › Descartar alterações locais** volta ao que está gravado no arquivo.

### Cadastro em massa pelo Excel

1. **Dados › Exportar para Excel (CSV)**, ou use o arquivo `modelo_importacao.csv` deste repositório.
2. Preencha **uma linha por combinação peça × inserto × parafuso**:

   | Conjunto | PN Peça | Descrição Peça | PN Inserto | Rosca | Descrição Inserto | Preferencial | PN Parafuso | Cabeça | Descrição Parafuso | Observação |
   |---|---|---|---|---|---|---|---|---|---|---|

   - `Preferencial`: `Sim` ou vazio.
   - `Cabeça`: `CSK` (escareada), `PAN` (panela), `HEX`, `FIL`, `SOC`, `TRU`, `WAF` ou outro código.
   - Uma peça sem inserto ainda pode ter só `Conjunto` e `PN Peça`.
3. Salve como CSV (separador `;`) e use **Dados › Importar CSV ou JSON**.
   O CSV é **mesclado**: cria o que é novo e não apaga nada.

> A rosca é exportada como `="8-32"` para o Excel não transformar `8-32` em data.
> A importação aceita os dois formatos.

**Backup completo:** use **Dados › Exportar JSON**. Ao importar um JSON, a biblioteca inteira é **substituída**.
