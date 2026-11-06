# Preparar para o GitHub

Repositório: [xLuuks/alo-live](https://github.com/xLuuks/alo-live).

A documentação e os arquivos foram preparados localmente. Gerar o pacote não envia os arquivos ao repositório; a publicação é uma etapa separada.

## Arquivos do projeto

Versione o código Python, `static/`, `templates/`, `tests/`, `scripts/`, `docs/`, `.github/`, os arquivos de requisitos, as configurações de texto e os documentos `README.md`, `LICENSE`, `NOTICE` e `SECURITY.md`.

Mantenha os arquivos de entrada atuais na raiz; testes, assets e documentação já estão em pastas próprias. A aplicação cria `mensagens.json`, backups e logs durante o uso, portanto um clone limpo não precisa de recados de exemplo nesses arquivos.

O `.gitignore` exclui fila, backups, logs, ambientes virtuais, resultados locais de testes, `Links.txt` e formatos comuns de credenciais. Ele não procura segredos dentro de arquivos de código nem remove arquivos já versionados.

## Pacote sem dados de operação

```powershell
.\.venv\Scripts\python.exe scripts/prepare_github.py
```

O comando gera `artifacts/alo-live-github.zip` e uma lista em `artifacts/github-files.txt`. A seleção usa uma lista explícita de arquivos e pastas do projeto, não inclui dados de operação e verifica alguns padrões de credenciais sem mostrar seus valores. O original permanece na pasta de trabalho. Novos tipos de arquivo precisam ser adicionados ao script quando forem necessários.

Confira o conteúdo antes de compartilhar. A verificação por padrões não detecta todo tipo de segredo. Para envio pela interface web do GitHub, extraia o pacote e envie seus arquivos, incluindo os arquivos de configuração que começam com ponto. Enviar o ZIP como um único arquivo não publica o código como uma árvore navegável.

## Usar Git

Se a pasta ainda não tiver um repositório Git, execute na raiz:

```powershell
git init -b main
git add .
git status --short
git diff --cached --stat
```

Revise os arquivos preparados para o commit antes de prosseguir. Fila, backups, logs e `.venv` não devem aparecer. Para o primeiro envio ao repositório vazio já criado:

```powershell
git commit -m "Publica a versão inicial do Alô Live"
git remote add origin https://github.com/xLuuks/alo-live.git
git push -u origin main
```

Esses comandos pressupõem uma pasta recém-inicializada, sem remoto `origin`. Antes de repetir o primeiro envio, confira `git remote -v` e o estado atual do repositório remoto. Não use push forçado para substituir conteúdo existente.

O `.gitignore` é aplicado pelo Git; arrastar a pasta inteira pela interface web não oferece essa proteção. Não envie o diretório de trabalho inteiro com os dados de uma transmissão.

## Após publicar

- Confira o README e as três imagens.
- Confira a primeira execução do workflow em Actions. O arquivo foi preparado e os comandos foram validados localmente; a execução na infraestrutura do GitHub só acontece após o envio.
- Habilite relatos privados de segurança e verifique os alertas de dependências disponíveis no repositório.
- O Dependabot está configurado mensalmente para pacotes Python e ações. Atualize o lock e valide o conjunto antes de aceitar mudanças.
- Uma descrição sugerida é: “Alô Live: painel local em Python para reunir dois chats do YouTube e enviar recados a uma janela transparente do apresentador.”
- Tópicos sugeridos: `python`, `flask`, `pyqt5`, `youtube`, `live-streaming`, `desktop-app`.

O GitHub Pages serve arquivos estáticos; ele não executa o servidor Python ou a janela desktop deste projeto.
