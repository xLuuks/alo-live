"""Cria um ZIP do código e documentação, preservando os dados locais."""

from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    ".editorconfig", ".gitattributes", ".gitignore", "README.md", "LICENSE", "NOTICE", "SECURITY.md",
    "requirements.txt", "requirements-lock.txt", "requirements-dev.txt", "Iniciar.pyw",
    "inicializador.py", "instancia.py", "janela.py", "marca.py", "processos.py", "recados.py", "registros.py",
    "sistema.py", "Teleprompter.py", "youtube_chat.py",
)
DIRECTORIES = (".github", "docs", "scripts", "static", "templates", "tests")
SUFFIXES = {".py", ".pyw", ".js", ".css", ".html", ".md", ".png", ".svg", ".yml", ".yaml", ".txt"}
SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"(?:gh[pousr]_[0-9A-Za-z]{20,}|github_pat_[0-9A-Za-z_]{30,})"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)


def project_files(root=ROOT):
    root = Path(root).resolve()
    files = [root / name for name in ROOT_FILES]
    for directory in DIRECTORIES:
        files.extend(path for path in (root / directory).rglob("*")
                     if path.is_file() and path.suffix.lower() in SUFFIXES
                     and "__pycache__" not in path.parts)
    for path in files:
        if not path.is_file():
            raise ValueError(f"Arquivo obrigatório ausente: {path.name}")
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f"Arquivo fora da árvore do projeto: {path.name}")
    return sorted(set(files), key=lambda path: path.relative_to(root).as_posix())


def checked_contents(files):
    # Confira todos antes de escrever, evitando produzir um novo pacote parcial.
    contents = []
    for path in files:
        data = path.read_bytes()
        if path.suffix.lower() not in {".png"}:
            text = data.decode("utf-8")
            if any(pattern.search(text) for pattern in SECRET_PATTERNS):
                raise ValueError(f"Possível credencial em {path.name}; revise o arquivo. Valor omitido.")
        contents.append((path, data))
    return contents


def main():
    contents = checked_contents(project_files())
    output = ROOT / "artifacts"
    output.mkdir(exist_ok=True)
    target = output / "alo-live-github.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, data in contents:
            archive.writestr(path.relative_to(ROOT).as_posix(), data)
    (output / "github-files.txt").write_text(
        "\n".join(path.relative_to(ROOT).as_posix() for path, _ in contents) + "\n", encoding="utf-8")
    print(f"Pacote preparado: artifacts/{target.name} ({len(contents)} arquivos).")
    print("Dados de operação, backups, logs e ambiente virtual não foram incluídos.")


if __name__ == "__main__":
    main()
