# Biblioteca de PNs — guia para continuar o projeto

Leia este arquivo inteiro antes de mexer em qualquer coisa. Ele existe para que outra sessão (ou outro modelo)
continue o trabalho mantendo o mesmo design, as mesmas decisões e o mesmo jeito de entregar.

## O que é

Biblioteca de consulta para engenharia de interiores de aeronaves: para cada **peça (PN)** mostra o **inserto**
usado por boa prática e os **parafusos** indicados com ele, organizados por **commodity** (OHBin, Galley,
Lavatory, Windscreen, Wardrobe…). Interface em **português do Brasil**.

## Restrições que não podem ser quebradas

1. **Um único arquivo HTML, offline.** `Biblioteca_PN.html` abre com duplo clique (`file://`) no Edge/Chrome.
   Sem servidor, sem internet, **sem CDN, sem biblioteca externa**: todo CSS/JS/SVG fica dentro do arquivo.
2. **O usuário não pode baixar arquivos no PC do trabalho nem abrir o Claude lá.** Ele pega o arquivo no GitHub
   (botão *Copy raw file*), cola no Bloco de Notas e salva como `.html` (Tipo "Todos os arquivos", UTF-8).
   Consequência: nada de dependências, nada de vários arquivos obrigatórios, tamanho contido.
3. **Em `file://` o navegador não deixa `fetch()` de arquivos vizinhos.** Funcionam: `<script src>` de um `.js`
   vizinho, `<img src>`, seletor de arquivo, arrastar-e-soltar, Ctrl+V de imagem, File System Access API.
4. **Senha de edição:** só o hash PBKDF2 fica no arquivo (`editLock` nos dados). **Nunca** escrever a senha em
   código, commit, README ou neste arquivo. Quem pedir a senha deve perguntar ao dono do projeto.
5. **Não inventar dados de engenharia.** PNs, insertos, parafusos e descrições só entram se o usuário informar.
   O que falta fica como pendência visível.
6. Trabalhar na branch indicada na sessão; não criar PR sem pedido; não mexer nos arquivos do `pdfcompare` na raiz.

## Arquivos

| Arquivo | Para quê |
|---|---|
| `Biblioteca_PN.html` | O programa inteiro + os dados (bloco `<script id="seed-data" type="application/json">`). |
| `Inspetor_3DXML.html` | Ferramenta à parte: diz o que há dentro de um `.3dxml` (tesselado XML × binário). |
| `modelo_importacao.csv` | Modelo para cadastro em massa pelo Excel. |
| `tools/build_artifact.py` | Gera a versão de prévia para publicar como Artifact no claude.ai (ver "Prévia"). |
| `README.md` | Manual do usuário final. Atualizar quando mudar comportamento visível. |

## Como o código está organizado (`Biblioteca_PN.html`)

Tudo num IIFE, JavaScript puro, sem framework. Renderização por *template strings* + `innerHTML`.

- **Dados** (`db`): `assemblies` (commodities: `id, name, short, art, image, description`), `parts`
  (`pn, description, assembly, notes, inserts:[{insert, preferred, note, screws:[pn]}], captures:[{name,img}]`),
  `inserts` (`pn, thread, description`), `screws` (`pn, head, thread, description`), `editLock`, `updatedAt`.
- **Persistência:** edições vão para `localStorage` como `{base, data}`; `base` é o `updatedAt` do arquivo em que
  foram feitas. Arquivo mais novo que as edições → as edições viram *backup* recuperável (não se perdem).
  "Salvar como HTML" regrava o `seed-data` num novo arquivo.
- **Rotas** por hash: `#/` início, `#/conjunto/<id>`, `#/peca/<pn>`, `#/inserto/<pn>`, `#/parafuso/<pn>`.
  (O id de rota continua `conjunto`; na tela o termo é **commodity**.)
- **Ações:** todo botão usa `data-act="..."`, tratado no objeto `ACT` por um único listener de clique.
- **Formulários:** `openForm({title, fields, values, onInput, onSubmit})` num `<dialog>`; `onSubmit` devolve
  string para mostrar erro. Tipos de campo: texto, `select`, `textarea`, `checkbox`, `password`, `image`, `info`.
- **Modo edição:** classe `editing` no `<body>`; `.edit-only` / `.view-only` no CSS; ações que mudam dados
  passam por `requireUnlock()`.
- **Árvore (organograma):** `asmTree`, `partLi`, `insLi` geram `<ul>/<li>` com conectores em CSS (`.tree`).
- **Viewer 3D:** `load3dxml` (lê o ZIP com `DecompressionStream`, estrutura do produto, matrizes, faces em
  `triangles/strips/fans`, cores, polilinhas) e `createViewer` (WebGL 1 escrito à mão, projeção ortográfica).
  Controles iguais aos do CATIA: meio = mover, meio + esquerdo/direito = girar, meio + clique = zoom.

## Base na pasta

- `<script src="base/dados.js">` (antes do `seed-data`) define `window.BIBLIOTECA_DADOS`; se existir, substitui os
  dados embutidos (`FROM_FOLDER`, `SEED`). Modelos: `base/modelos/<PN>.js` chama `BIBLIOTECA_MODELO(pn, dados)` e é
  carregado sob demanda por `<script>` dinâmico (`loadStoredModel`). `p.model = {file, name, at}` marca a peça.
- Gravação: File System Access API. `connectBase()` pede a pasta do HTML, `saveBase()` grava `dados.js` após cada
  `commit()` (com checagem de conflito pelo `updatedAt`), `saveModelFile()` grava o modelo compactado
  (`encodeModel`: posições em uint16 relativas à caixa, normais int8, base64). O handle da pasta fica no IndexedDB.
- Teste: sirva o HTML por `python3 -m http.server` e troque `showDirectoryPicker` por `navigator.storage.getDirectory()`.

## Design (manter exatamente este padrão)

- **Tokens de cor em `:root`**, redefinidos para o tema escuro em `@media (prefers-color-scheme: dark)` com
  `:root:not([data-theme="light"])` e em `:root[data-theme="dark"]`. **Nunca** usar cor literal em componente.
- **Cor por tipo:** peça = azul (`--part`), inserto = laranja (`--insert`), parafuso = roxo (`--screw`).
  Estado: `--ok`, `--warn`, `--danger`. PNs sempre em fonte monoespaçada (`--mono`).
- **Componentes:** cartões com borda fina, raio 12–16 px, sombra leve; chips arredondados; ícones SVG de traço
  (1.8) em `currentColor`; fundo pontilhado nas áreas de desenho.
- **Ilustrações das commodities** (`ART`): SVG `viewBox="0 0 240 140"`, **vista frontal, plana e alinhada**
  (o usuário rejeitou perspectiva/isométrico desenhado à mão). Classes: `.fl` (forma com contorno),
  `.ln` (linha forte), `.lt` (linha fina), `.ac` (destaque preenchido), `.as` (destaque em traço).
  Desenhar a partir de foto/print real enviado pelo usuário, nunca de memória.
- **Texto da interface:** direto, em português, verbos de ação nos botões, sem jargão de sistema.
- **Responsivo:** funciona em ~390 px sem rolagem lateral da página; só a árvore e tabelas rolam por dentro.

## Como trabalhar

1. Mudanças pequenas e verificadas. Depois de cada mudança, **testar num navegador de verdade** (Playwright +
   Chromium já instalados; para WebGL use `--use-gl=swiftshader --enable-unsafe-swiftshader`) e **olhar a
   captura de tela** antes de dizer que ficou bom.
2. Mostrar ao usuário a imagem do resultado. Ele acompanha pelo celular e manda fotos da tela do PC.
3. Commit + push a cada entrega. Depois, lembrar o usuário do link do arquivo na branch.
4. Dizer com clareza o que foi testado e o que não foi (por exemplo, "testei só com um 3DXML sintético").
5. Respostas curtas e práticas, em português. O usuário é direto e não quer explicação longa.

## Prévia (Artifact)

O visualizador de artifacts não permite download nem rotas `#/...`. Por isso existe uma versão adaptada:

```
python3 tools/build_artifact.py Biblioteca_PN.html <saida>/Biblioteca_PN.html
```

Publicar sempre no mesmo artifact (mesmo caminho de arquivo na sessão, ou passando a URL existente).
Nunca gravar a saída dentro do repositório.

## Fatos já descobertos (não redescobrir)

- 3DXML só é legível com **Xml Tessellation** (CATIA: Tools › Options › General › Compatibility › 3D XML).
  `format=UVR` e `.cgr` são binários fechados: não dá.
- O CATIA do usuário **não exporta o FT&A (MBD)** no 3DXML tesselado. Por isso as cotas entram como
  **capturas coladas** (galeria "Capturas do MBD").
- `localStorage` guarda ~5 MB: imagens são reduzidas (WebP) antes de salvar.
- Exportar rosca para CSV como `="8-32"`, senão o Excel vira data.

## Pendências combinadas com o usuário

- Lista completa de commodities (o usuário vai enviar) e desenho de cada uma; refazer o desenho do **Lavatory**
  a partir de uma referência real.
- Confirmar no PC do usuário que a política da empresa permite a gravação na pasta (File System Access).
- Tirar as imagens (capturas, fotos de commodity) de dentro do `dados.js` para arquivos em `base/imagens`.
- Link "Abrir no Windchill" por PN (falta o formato do endereço).
- Mapa de insertos: pinos sobre a imagem da peça indicando onde vai cada inserto.
