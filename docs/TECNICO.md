# Guia técnico

## Componentes e execução

O nome público é **Alô Live**, definido em `marca.py`, com logo em `static/brand/alo-live.png`. A identidade interna `central-de-recados` do endpoint de saúde e as chaves anteriores de preferências/rascunhos foram preservadas para manter compatibilidade com as instalações existentes.

`Teleprompter.py` mantém uma fila `Recados`, os coletores `YouTubeChats` e as confirmações das telas em um processo Flask. Execute uma única instância: o bloqueio da fila é de threads, não uma coordenação entre processos.

`inicializador.py` mantém a interface Qt responsiva durante a abertura do servidor. `sistema.py` verifica versão, instalação e PID antes de reutilizar ou assumir um processo. No Windows, `processos.py` identifica os descendentes do executável de um ambiente virtual: o redirecionador pode ter um PID diferente do interpretador efetivo. O encerramento considera somente processos iniciados por esse gerenciador. Um servidor compatível já existente é reutilizado, sem ser encerrado por ele.

`instancia.py` usa um nome de IPC derivado da pasta para ativar a janela existente. Um pedido de fechamento precisa conter o PID do destinatário. A janela faz consultas pela Qt Network, com um pedido por vez e tempo limite de 2,5 segundos.

## Persistência

O arquivo `mensagens.json` usa schema 2. Registros contêm IDs, texto, versão de edição, origem, identificador de envio e posição racional. A lista antiga de strings é migrada em memória e salva no formato atual na primeira alteração.

- Fila ativa, histórico de até 200 retiradas e última operação de retirada são persistidos juntos.
- A última retirada mantém todos os seus itens, mesmo em uma limpeza com mais de 200 recados.
- Posições racionais permitem restaurar itens na ordem correta sem depender da sequência de cliques.
- A escrita usa arquivo temporário na mesma pasta, `fsync` e substituição atômica. A memória só recebe a nova versão depois do arquivo principal.
- Após cada alteração, são mantidas 20 cópias em `backups/`. Uma falha somente no backup gera aviso, sem reverter a gravação principal.
- Ao iniciar com arquivo ausente ou inválido, é procurado o backup válido mais recente. Um original inválido é preservado. Sem cópia válida, o erro não é convertido silenciosamente em uma fila vazia.

## Repetição de envio

O navegador conserva um `request_id` no rascunho. O identificador muda ao preparar outro envio ou alterar o texto. Tanto o envio manual quanto o YouTube gravam esse identificador no registro.

No envio do YouTube, consulta de tentativa anterior e envio ficam sob o mesmo bloqueio do coletor. A repetição com o mesmo identificador, texto e origem retorna o ID original, inclusive após reiniciar ou retirar o recado. Ela não restaura itens lidos. Um identificador reutilizado com outro texto ou origem é rejeitado.

A recuperação depende de o registro ainda estar na fila, no histórico ou no desfazer. Não há retenção ilimitada de identificadores de envios antigos. Um envio novo do mesmo comentário continua sendo rejeitado enquanto sua origem estiver retida; para um novo recado, use o modo manual.

## Confirmação de entrega e rolagem

`GET /mensagens` fornece os textos, uma revisão e um token HMAC dessa revisão. Depois de aplicar o conteúdo, a tela envia a confirmação para `POST /apresentador/confirmar`.

O recibo contém tipo de tela, estado ativo, revisão e `overflow: {above, below}`. Na janela, os valores vêm da barra de rolagem; no navegador, dos limites do contêiner em relação ao viewport. Clientes anteriores que não enviem esse campo continuam sendo aceitos, sem inferir que tudo cabe.

O painel só exibe o estado de rolagem quando a confirmação é recente, corresponde à revisão atual e a tela está ativa. Confirmações com mais de 8 segundos deixam de ser consideradas recentes; o servidor remove registros após 30 segundos e mantém no máximo 20 clientes.

O estado informa a necessidade de rolagem, não quais pessoas já foram lidas nem se a janela está encoberta por outro aplicativo. Todos os recados continuam juntos.

## Atualização do painel

Cartões de comentários, fila e histórico são reconciliados por ID. Alterações em um recado não recriam os demais. O foco é recuperado após movimentos e, quando o item focado é removido, passa para um cartão remanescente. Um cartão visível funciona como referência de posição durante a atualização da fila.

Rascunhos são guardados em `localStorage` com uma chave por aba; `sessionStorage` e BroadcastChannel ajudam a distinguir abas duplicadas. O armazenamento é opcional e pode falhar. O modo manual recolhe as áreas do YouTube; ele não interrompe coletores já conectados.

## Coleta do YouTube

Cada transmissão possui thread, estado, chave e cursor próprios. Reconectar o mesmo vídeo preserva seu cursor; trocar o vídeo limpa somente o buffer daquele canal. Há até 1.000 comentários em memória e 10.000 IDs de deduplicação. A chave é enviada no cabeçalho da consulta e não aparece nas respostas do painel.

A implementação usa `liveChatMessages.list`, com padrão de 30 segundos e respeito ao `pollingIntervalMillis`. Cada consulta custa 5 unidades conforme a [documentação do Google](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/list). Duas transmissões a cada 30 segundos representam aproximadamente 1.200 unidades por hora, além de descoberta e reconexões. Verifique a cota do projeto.

O Google também oferece `streamList`; essa modalidade não está implementada. O teste com transmissões reais ainda depende da chave e dos chats ativos do operador.

## Configuração

| Variável | Finalidade |
| :--- | :--- |
| `YOUTUBE_API_KEY` | Chave opcional, alternativa ao preenchimento no painel. |
| `TELEPROMPTER_PORT` | Porta do servidor; padrão 5000. |
| `TELEPROMPTER_SERVER_URL` | Endpoint usado pela janela aberta pelo inicializador. |
| `TELEPROMPTER_DATA_DIR` | Pasta de dados; usada nos testes para isolar os arquivos. Deve existir. |
| `TELEPROMPTER_LOG_DIR` | Destino dos logs; criado quando necessário. |

O projeto não carrega arquivos `.env` automaticamente. O inicializador usa sua porta configurada internamente e transmite porta e URL aos filhos. Os comandos usuais utilizam 5000.

Os logs dos componentes possuem rotação de 1 MB com três arquivos anteriores. `processos.log`, que recebe stdout/stderr dos filhos, ainda não possui rotação. O formatador dos componentes oculta padrões de chaves; não trate logs como material público.

## Manutenção

Ao alterar dependências, atualize `requirements.txt` e `requirements-lock.txt`, instale em ambiente limpo, rode testes, `pip check` e `pip_audit`. O lock atual representa Windows x64 e Python 3.13. A auditoria verifica avisos conhecidos de pacotes Python; não é uma garantia de ausência de falhas, nem uma auditoria completa do runtime Qt.

O workflow em `.github/workflows/ci.yml` utiliza ações fixadas por commit, permissão de leitura e nenhuma credencial do YouTube. A configuração deve ser conferida na primeira execução remota após publicar o repositório.
