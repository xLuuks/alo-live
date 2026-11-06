# Segurança

Este aplicativo foi preparado para **uso local no computador do operador**. O servidor escuta em `127.0.0.1`, aceita hosts locais, mantém a depuração desligada e exige um token CSRF para os comandos de alteração. A confirmação do apresentador exige um token assinado da revisão.

Não há autenticação de usuários ou autorização para exposição à rede. Não publique o servidor na internet nem altere o bind para todas as interfaces como forma de hospedar o painel. As proteções locais não substituem autenticação ou controle de acesso de uma aplicação pública.

## Dados e credenciais

- Informe a chave do YouTube no painel ou em variável de ambiente. Ela não é salva pelo aplicativo em arquivo e não é retornada pela API do painel.
- A fila, o histórico e os backups são arquivos locais sem criptografia. Os rascunhos ficam no armazenamento do navegador. Restrinja o acesso ao computador e à pasta conforme a necessidade do uso.
- Não publique `mensagens.json`, `backups/`, `logs/`, arquivos de credenciais, `.env` ou capturas de uma sessão real sem revisão.
- A ocultação de chaves nos logs dos componentes é uma proteção adicional, não uma autorização para publicar registros. A saída bruta em `processos.log` não passa por esse formatador.
- Se uma chave for exposta, revogue-a ou substitua-a no provedor. Retirar o arquivo do último commit não remove cópias do histórico.

## Verificações

Os testes verificam CSRF, host permitido, limite de envio, texto simples, confirmação assinada, persistência e recuperação após falhas. O comando `python -m pip_audit -r requirements-lock.txt` consulta avisos conhecidos de dependências. Ele não certifica a segurança completa da aplicação ou de bibliotecas nativas.

Revise dependências e execute os testes ao aceitar atualizações sugeridas pelo Dependabot. O workflow de CI não utiliza chaves do YouTube nem dados de operação.

## Relato de problemas

Não inclua chaves, tokens, recados pessoais ou dumps completos em uma issue pública. Ao disponibilizar o repositório, habilite o recurso de relato privado de vulnerabilidades do GitHub para receber detalhes sensíveis. Em um relato público, limite-se à descrição geral e a um exemplo fictício que não exponha dados.
