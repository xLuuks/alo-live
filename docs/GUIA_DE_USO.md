# Guia de uso — Alô Live

Painel local para acompanhar até duas transmissões do YouTube e escolher os recados que aparecem para o apresentador. A entrada manual e a janela transparente em PyQt5 continuam disponíveis.

## Iniciar no Windows

Na primeira instalação, execute na pasta do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
```

Depois, abra **Iniciar.pyw** com dois cliques. O inicializador abre o servidor, o painel no navegador e a janela do apresentador. Mantenha o inicializador aberto durante a transmissão; seus botões permitem reabrir o painel e a janela. Abrir o inicializador ou a janela novamente ativa a instância existente.

Use **Encerrar sistema** ou feche o inicializador para fechar a janela e o servidor que ele iniciou. Se encontrar um servidor compatível já aberto, o inicializador o reutiliza e avisa que ele continuará em execução ao fechar; nesse caso, encerre o servidor pelo terminal original. Um servidor de versão anterior deve ser fechado antes de usar o novo inicializador.

Também é possível iniciar separadamente, como antes: execute `.\.venv\Scripts\python.exe Teleprompter.py` e mantenha esse terminal aberto; execute `.\.venv\Scripts\python.exe janela.py` em outro terminal ou abra o arquivo com dois cliques. Abra **http://127.0.0.1:5000/editor** para o painel ou **http://127.0.0.1:5000/teleprompter** para a tela do apresentador no navegador.

## Janela do apresentador

A janela transparente fica sempre por cima das outras e exibe todos os recados enviados juntos. Arraste pelo texto ou pelo fundo para movê-la. Use a alça no canto inferior direito para redimensionar; se os recados ultrapassarem a altura, use a rolagem. Posição, tamanho, fonte, cor, opacidade e modo de leitura são lembrados ao abrir novamente. Se um monitor for desconectado, a janela é reposicionada em uma tela disponível ao iniciar.

Clique com o **botão direito** sobre o texto ou o fundo para abrir Configurações, mostrar os controles, ajustar a fonte, minimizar ou fechar. Isso também funciona no modo de leitura, sem precisar lembrar do F2. Um aviso indica quando há recados acima ou abaixo da área visível.

Recados novos ou com texto alterado destacam a borda por três segundos. Apenas reordenar ou retirar recados não cria um novo destaque. O modo de leitura esconde os botões e a alça; o aviso de desconexão continua visível. A janela consulta o painel sem bloquear sua interface e mantém o último texto recebido quando houver falha, indicando que ele pode estar desatualizado.

Com a janela em foco:

| Atalho | Ação |
|---|---|
| **F2** | Mostrar ou esconder os controles (modo de leitura) |
| **Ctrl +** ou **Ctrl =** | Aumentar a fonte |
| **Ctrl −** | Diminuir a fonte |
| **Ctrl 0** | Voltar à fonte de 32 px |
| **Esc** | Sair do modo de leitura; fora dele, fechar a janela |
| **Ctrl Q** | Fechar a janela |

Para redimensionar no modo de leitura, pressione F2, ajuste a alça e pressione F2 novamente. O botão **Configurações** permite ajustar fonte de 12 a 72 px, cor e opacidade de 30% a 100%. Esses ajustes se aplicam à janela de `janela.py`; a opção de exibição no navegador continua com seu próprio visual.

## Conectar o YouTube

1. Crie ou selecione um projeto no [Google Cloud Console](https://console.cloud.google.com/).
2. Ative a **YouTube Data API v3** em APIs e serviços → Biblioteca.
3. Em APIs e serviços → Credenciais, crie uma **chave de API**. Restrinja a chave à YouTube Data API v3. Como as consultas são feitas pelo Python, uma restrição por referenciador HTTP de navegador não se aplica; configure as restrições adequadas ao ambiente do servidor.
4. No painel, cole a chave no campo indicado e os links dos **vídeos ao vivo** dos dois canais. É possível conectar somente uma transmissão. São aceitos links `watch?v=`, `youtu.be/`, `/live/` e IDs de vídeo.
5. Clique em **Conectar transmissões** e confira o estado de cada transmissão.

Use uma transmissão acessível à chave, com chat ativo. Lives privadas ou que exijam autorização adicional não são atendidas por esta versão. Uma live agendada sem chat ativo deve ser conectada novamente após começar.

A chave não é gravada em arquivo nem devolvida pela API do painel. O campo de senha a mantém na página enquanto ela estiver aberta; ao recarregar, informe novamente. Opcionalmente, configure a variável de ambiente antes de iniciar:

```powershell
$env:YOUTUBE_API_KEY = 'SUA_CHAVE'
.\.venv\Scripts\python.exe Teleprompter.py
```

Não coloque a chave em arquivos versionados ou envie a chave pelo chat. O navegador guarda apenas os links e o intervalo de consulta. Se não permitir armazenamento local, as conexões continuam funcionando.

## Durante a transmissão

- O painel é organizado em três áreas: comentários, preparação e recados enviados. Em telas menores, as áreas se reorganizam. Cada canal tem uma cor e seu nome; após conectar, a área de configurações é recolhida para liberar espaço.
- Os comentários dos dois chats são reunidos, com autor, canal, transmissão e horário. É possível buscar, filtrar e pausar a atualização da lista sem interromper a coleta. As novidades aguardam no botão **Atualizar lista**: novos comentários não deslocam os cartões enquanto você lê ou clica neles.
- Clique em **Preparar recado**, ajuste o texto e depois em **Enviar ao apresentador**. Nada é enviado automaticamente.
- Cada aba mantém seu próprio rascunho no armazenamento local do navegador, incluindo a associação ao comentário selecionado. Recarregar a aba recupera o texto; enviar ou limpar em uma aba não apaga o rascunho de outra. Abas duplicadas são separadas automaticamente nos navegadores com BroadcastChannel. Em **Recuperar outro rascunho salvo**, é possível copiar um rascunho de outra aba ou de uma sessão anterior sem apagar o original. O salvamento depende da permissão de armazenamento do navegador.
- Se o comentário de origem não estiver mais disponível no servidor, use **Usar este texto como manual** para preservar o texto e enviá-lo como um recado manual.
- Um comentário já enviado fica identificado. Reconectar o mesmo vídeo preserva a marcação; a fila e os últimos 200 recados do histórico também preservam a identificação dos comentários enviados após reiniciar o servidor. Para um novo recado sobre ele, use a entrada manual.
- Os cartões da fila são atualizados por ID, preservando foco e posição de leitura durante alterações. Os recados selecionados aparecem juntos na tela existente. Use **Lido**, **Editar**, **↑**, **↓** ou **Retirar todos da tela** para organizar a apresentação. A edição acontece dentro do painel; alterações simultâneas em outra aba são detectadas antes de sobrescrever o texto.
- **Lido** e **Retirar todos da tela** movem os recados para o **Histórico de recados**. Abra o histórico e use **Restaurar na tela** para desfazer uma retirada. Os últimos 200 recados retirados ficam salvos, inclusive após reiniciar.
- **Desfazer última retirada** recupera a última remoção ou limpeza inteira, preservando a ordem. Esse desfazer fica salvo após reiniciar e funciona mesmo se a limpeza tiver mais de 200 recados. A restauração individual também preserva a ordem entre os recados restaurados; movimentos feitos na fila são respeitados.
- Cada canal possui seus próprios botões **Reconectar** e **Desconectar**, sem interromper o outro. Reconectar a mesma live mantém os comentários, marcações e o cursor da coleta. Trocar o vídeo substitui apenas os comentários daquele canal. As configurações gerais também permitem conectar os links preenchidos e desconectar todas as transmissões.

## Modo manual

O botão **Só recados manuais** recolhe as configurações, as conexões e a lista do YouTube, deixando a preparação e os recados enviados em destaque. O texto em preparação é preservado e passa a ser tratado como manual. **YouTube + manual** volta à organização completa. A escolha é lembrada neste navegador.

O modo manual muda a organização da tela. Chats que já estavam conectados continuam sendo coletados; volte ao modo YouTube e desconecte-os se quiser interromper as consultas à API.

## Cópias de segurança e registro de falhas

A cada alteração salva, o sistema grava uma cópia completa da fila, do histórico e do desfazer em **backups/**, mantendo as 20 cópias mais recentes. Se `mensagens.json` estiver ausente ou inválido ao iniciar, o sistema procura a cópia válida mais recente e recupera os dados automaticamente. Um arquivo inválido é preservado como `mensagens.corrompido-...json`; o painel informa a recuperação para você conferir os recados. Sem cópia válida, um arquivo danificado é preservado e a inicialização informa o erro.

Se somente o backup falhar, a alteração principal permanece salva e o painel apresenta um aviso. A cópia é local, na mesma pasta do projeto: não protege contra a perda de toda essa pasta ou do disco.

Falhas e eventos de conexão são registrados em **logs/servidor.log**, **logs/janela.log** e **logs/inicializador.log**, com rotação dos arquivos. A saída dos processos abertos pelo inicializador fica em **logs/processos.log**. As chaves da API são ocultadas pelo formatador dos registros; os textos dos recados não são registrados pelos fluxos normais de envio.

## Confirmação de entrega ao apresentador

A coluna de recados informa se a janela ou a página do apresentador confirmou o recebimento da versão mais recente dos textos. Uma janela minimizada ou uma aba em segundo plano é identificada separadamente. A confirmação indica recebimento pelo aplicativo, não leitura pela pessoa. O painel também informa se há recados acima ou abaixo da área visível, ou se todos cabem. Esse estado depende de uma confirmação recente, da versão atual e da tela ativa.

A ausência de confirmação recente aparece após até 8 segundos. O servidor precisa estar atualizado junto com `janela.py`; reinicie os dois programas após atualizar o projeto. O painel também sinaliza quando perde a própria conexão com o servidor e quando ela é restabelecida. As consultas do navegador possuem tempo limite. Envios manuais ou do YouTube repetidos com o mesmo identificador, texto e origem não criam cópias do recado. Se a resposta de um envio do YouTube se perder, repetir sem alterar o texto reconhece o registro salvo e libera o editor. A identificação dura enquanto o registro permanecer na fila, no histórico ou no desfazer; não é um arquivo permanente de todos os envios.

## Intervalo, cota e limites

Esta versão usa `liveChatMessages.list` e respeita o `pollingIntervalMillis` retornado pelo YouTube. O padrão é consultar cada chat a cada **30 segundos**; o painel local se atualiza a cada 2 segundos. Reduzir o intervalo no painel aumenta o consumo de cota.

Segundo a [documentação oficial](https://developers.google.com/youtube/data/live/reference/rest/v3/liveChatMessages/list), cada consulta ao chat custa 5 unidades. Para duas transmissões, a estimativa é de 1.200 unidades por hora a cada 30 segundos, 2.400 a cada 15 segundos e 7.200 a cada 5 segundos, além da descoberta dos vídeos e das reconexões. O intervalo mínimo informado pela API pode aumentar esses tempos. Confira a cota disponível no seu projeto; em caso de esgotamento, a coleta para com um aviso. Uma evolução para [`streamList`](https://developers.google.com/youtube/data/live/streaming-live-chat) pode reduzir consultas recorrentes.

A primeira consulta recupera somente o histórico recente disponibilizado pelo YouTube. Não é uma importação completa de comentários antigos. A lista recebida mantém até 1.000 comentários em memória e desaparece ao reiniciar o servidor. Um cartão que ultrapassou esse limite pode continuar visível no navegador até você atualizar a lista, mas o envio dele exigirá a entrada manual se já saiu da memória do servidor.

A fila e o histórico são salvos juntos em `mensagens.json`, com gravação atômica; falhas de gravação não confirmam o envio nem retiram o recado da fila. O arquivo antigo (lista de textos) é lido automaticamente e passa ao formato com IDs, versões e histórico na primeira alteração salva. Não é necessário converter o arquivo manualmente. As operações usam IDs fixos: mudanças na ordem da fila não fazem a ação atingir outro recado.

O servidor escuta apenas em `127.0.0.1`, com o modo de depuração desligado. Execute uma única instância/processo do servidor: os coletores e a fila são coordenados em memória. A implementação não inclui Facebook nem publica respostas no YouTube.

## Verificar

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Os testes usam respostas simuladas da API e arquivos temporários. A validação com comentários reais exige sua chave e uma transmissão ativa.

Para testar também o fluxo no navegador, com Chrome ou Edge instalado e Python 3.13:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -B tests/browser_smoke.py
.\.venv\Scripts\python.exe -B tests/browser_smoke.py --manual-only
.\.venv\Scripts\python.exe -B tests/browser_smoke.py --refinements
.\.venv\Scripts\python.exe -B tests/browser_smoke.py --delivery-refinements
```

Esse teste abre um navegador temporário em modo headless, usa duas lives simuladas e verifica a estabilidade da lista, novidades, recuperação de rascunho, edição no painel, envio, histórico, restauração, reconexão por canal, confirmação de entrega e largura móvel. Ele não acessa sua sessão habitual do navegador nem faz consultas ao YouTube.

O modo `--refinements` verifica também abas duplicadas, isolamento de rascunhos, recuperação de outro rascunho, modo manual e desfazer da limpeza. Os testes do inicializador abrem um servidor de teste em uma porta temporária, com dados separados dos recados reais.
