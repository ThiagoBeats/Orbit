class OrbitError(Exception):
    """Erro cuja mensagem (em portugues) pode ser mostrada ao usuario."""


class OrbitDataError(OrbitError):
    """Dados (JSON) corrompidos ou ausentes."""


class ArquivoEmUso(OrbitError):
    """Arquivo aberto em outro programa; a operacao foi desfeita."""


class LockHeld(OrbitError):
    """Outra pessoa/computador esta fazendo upload no mesmo lugar."""
