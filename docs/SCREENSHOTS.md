# Capturas da documentação

As imagens são produzidas a partir das interfaces reais. Os dados de comentários, canais e recados são fictícios. Nenhuma chave, arquivo de mensagens do operador ou sessão habitual do navegador é usada.

Após instalar `requirements-dev.txt`, execute na raiz, no Windows com Chrome ou Edge:

```powershell
.\.venv\Scripts\python.exe -B tests/browser_smoke.py --readme
.\.venv\Scripts\python.exe -B scripts/capture_presenter.py
```

| Arquivo | Conteúdo |
| :--- | :--- |
| `screenshots/01-painel-desktop.png` | Painel em 1440 px, com duas conexões simuladas, três comentários e dois recados. |
| `screenshots/02-modo-manual.png` | Mesmo painel no modo manual, preservando o texto preparado. |
| `screenshots/03-janela-apresentador.png` | Janela PyQt5 em 900 × 420, com preferências temporárias e dois recados. |

O primeiro comando inicia um servidor e um navegador headless com perfil temporário. O segundo renderiza a janela nativa sem mostrá-la na área de trabalho, sem polling e sem mudar as preferências reais. O fundo translúcido pode aparecer preto na captura isolada.

O modo `--readme` gera documentação; os outros modos de `browser_smoke.py` executam os cenários de regressão. Refaça e confira as imagens ao mudar a interface.
