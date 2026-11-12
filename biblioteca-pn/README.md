# Biblioteca de PNs — insertos e parafusos por peça

Ferramenta de consulta (e cadastro) que mostra, para cada **peça (PN)**, qual **inserto** é usado
por boa prática e quais **parafusos** são indicados com esse inserto.

```
Commodity (ex.: Overhead Bin)
└── Peça            CDPA689
    └── Rosca       8-32
        ├── Inserto CDIN07-08-06  ★ preferencial (opcional)
        │   ├── Parafuso NAS514P832-3P  (CSK · escareada)
        │   └── Parafuso NAS8302-3      (PAN · panela)
        └── Inserto CDIN23-08S
```

## Como usar

A tela inicial mostra um botão para cada **commodity** (OHBin, Galley, Lavatory, Windscreen, Wardrobe).
Dentro de cada uma, as peças aparecem numa **árvore de cima para baixo** (como um organograma): commodity → peças →
INSERTO (rosca) → insertos → parafusos. Clique numa peça para abrir os insertos; clique num inserto
para recolher ou mostrar os parafusos. O ícone ↗ no canto de cada caixa abre a página de detalhes.

É **um único arquivo**: `Biblioteca_PN.html`. Abra com um duplo clique (Edge/Chrome). Não precisa
de instalação, servidor nem internet.

| O que fazer | Como |
|---|---|
| Achar um PN | Digite na busca do topo (atalho **/** ou **Ctrl+K**). Pode digitar parte do PN, sem hífen (`nas8302`). |
| Ver onde um inserto/parafuso é usado | Clique no PN do inserto ou parafuso para abrir a página com a seção **Onde é usado**. |
| Copiar um PN | Passe o mouse sobre o PN e clique no ícone de copiar. |
| Levar a tabela para o Excel | Na página da peça, use **Copiar tabela** e cole no Excel. |
| Cadastrar ou editar | Ative o **Modo edição** (topo à direita) e digite a **senha de edição** (peça ao responsável pela biblioteca). Aparecem os botões de adicionar, editar e excluir. A senha vale até fechar a aba. |
| Compartilhar com a equipe | **Dados › Salvar como HTML** gera um novo arquivo com os dados gravados dentro. Envie esse arquivo ou coloque no SharePoint. |

### Onde ficam os dados?

- Os dados "oficiais" ficam **dentro do próprio HTML** (bloco `<script id="seed-data">`).
- O que você edita no navegador fica salvo **só no seu navegador** até você usar
  **Dados › Salvar como HTML**. O aviso laranja na barra lateral lembra disso.
- **Dados › Descartar alterações locais** volta ao que está gravado no arquivo.

### Cadastro em massa pelo Excel

1. **Dados › Exportar para Excel (CSV)**, ou use o arquivo `modelo_importacao.csv` deste repositório.
2. Preencha **uma linha por combinação peça × inserto × parafuso**:

   | Commodity | PN Peça | Descrição Peça | PN Inserto | Rosca | Descrição Inserto | Preferencial | PN Parafuso | Cabeça | Descrição Parafuso | Observação |
   |---|---|---|---|---|---|---|---|---|---|---|

   - `Preferencial`: `Sim` ou vazio.
   - `Cabeça`: `CSK` (escareada), `PAN` (panela), `HEX`, `FIL`, `SOC`, `TRU`, `WAF` ou outro código.
   - Uma peça sem inserto ainda pode ter só `Commodity` e `PN Peça`.
   - Arquivos antigos com a coluna `Conjunto` também são aceitos.
3. Salve como CSV (separador `;`) e use **Dados › Importar CSV ou JSON**.
   O CSV é **mesclado**: cria o que é novo e não apaga nada.

> A rosca é exportada como `="8-32"` para o Excel não transformar `8-32` em data.
> A importação aceita os dois formatos.

**Backup completo:** use **Dados › Exportar JSON**. Ao importar um JSON, a biblioteca inteira é **substituída**.

### Senha de edição

- O **Modo edição**, **Importar** e **Descartar alterações** pedem a senha. Consultar não pede.
- O arquivo guarda só uma impressão digital criptografada da senha (PBKDF2-SHA256), nunca a senha em si.
- Para trocar: com o Modo edição ligado, **Dados › Trocar senha de edição**, depois **Salvar como HTML**.
- A senha evita edições acidentais ou de quem não deve mexer. Quem souber editar código HTML consegue
  contorná-la; a proteção de verdade é a permissão de escrita na pasta onde o arquivo oficial fica.

### Commodities e imagens

- Cada commodity tem um desenho próprio. No Modo edição, use o lápis no botão da commodity para trocar o
  nome, o nome curto do botão (ex.: `OHBin`), o desenho, ou colar uma **foto/print** (Ctrl+V) no lugar dele.
- A imagem é reduzida e guardada dentro do próprio arquivo (não precisa de pasta de imagens).

### Modelo 3D (3DXML)

- Na página de cada peça há o quadro **Modelo 3D**: arraste um `.3dxml` **tesselado** (geometria em XML) e ele abre ali,
  para girar, mover e dar zoom. O arquivo é lido só no computador e, por enquanto, **não fica salvo** na biblioteca.
- 3DXML binário (`format=UVR`) e `.cgr` não podem ser lidos pelo navegador. Use o `Inspetor_3DXML.html` para conferir
  o tipo de exportação de um arquivo.
