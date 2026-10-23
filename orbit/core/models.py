from dataclasses import dataclass, field

VERSAO_FORMATO = 1

TIPOS_EVENTO = (
    "revisao_enviada", "status_alterado", "importacao", "email_preparado",
    "nao_se_aplica_alterado", "dados_alterados", "arquivo_registrado",
)


@dataclass
class Contato:
    nome: str
    email: str

    def to_dict(self) -> dict:
        return {"nome": self.nome, "email": self.email}

    @classmethod
    def from_dict(cls, d: dict) -> "Contato":
        return cls(d["nome"], d.get("email", ""))


@dataclass
class Arquivo:
    nome: str
    papel: str  # "principal" ou "editavel"

    def to_dict(self) -> dict:
        return {"nome": self.nome, "papel": self.papel}

    @classmethod
    def from_dict(cls, d: dict) -> "Arquivo":
        return cls(d["nome"], d["papel"])


@dataclass
class Revisao:
    numero: int
    data: str
    status: str
    motivo: str
    usuario: str
    computador: str
    arquivos: list[Arquivo] = field(default_factory=list)
    arquivada: bool = False

    @property
    def principal(self) -> Arquivo:
        for a in self.arquivos:
            if a.papel == "principal":
                return a
        raise ValueError(f"Revisão {self.numero} sem arquivo principal")

    def to_dict(self) -> dict:
        return {
            "numero": self.numero, "data": self.data, "status": self.status,
            "motivo": self.motivo, "usuario": self.usuario,
            "computador": self.computador,
            "arquivos": [a.to_dict() for a in self.arquivos],
            "arquivada": self.arquivada,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Revisao":
        return cls(
            d["numero"], d["data"], d["status"], d.get("motivo", ""),
            d.get("usuario", ""), d.get("computador", ""),
            [Arquivo.from_dict(a) for a in d.get("arquivos", [])],
            d.get("arquivada", False),
        )


@dataclass
class Documento:
    tipo_id: str
    pasta: str
    nao_se_aplica: bool = False
    revisoes: list[Revisao] = field(default_factory=list)

    @property
    def atual(self) -> Revisao | None:
        ativas = [r for r in self.revisoes if not r.arquivada]
        return max(ativas, key=lambda r: r.numero) if ativas else None

    def to_dict(self) -> dict:
        return {
            "tipo_id": self.tipo_id, "pasta": self.pasta,
            "nao_se_aplica": self.nao_se_aplica,
            "revisoes": [r.to_dict() for r in self.revisoes],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Documento":
        return cls(
            d["tipo_id"], d["pasta"], d.get("nao_se_aplica", False),
            [Revisao.from_dict(r) for r in d.get("revisoes", [])],
        )


@dataclass
class Evento:
    tipo: str
    data_hora: str
    usuario: str
    computador: str
    dados: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "tipo": self.tipo, "data_hora": self.data_hora,
            "usuario": self.usuario, "computador": self.computador,
            "dados": dict(self.dados),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Evento":
        return cls(d["tipo"], d["data_hora"], d.get("usuario", ""),
                   d.get("computador", ""), dict(d.get("dados", {})))


@dataclass
class Cliente:
    id: str
    nome: str
    pasta: str
    cnpj: str = ""
    contatos: list[Contato] = field(default_factory=list)
    versao_formato: int = VERSAO_FORMATO

    def to_dict(self) -> dict:
        return {
            "versao_formato": self.versao_formato, "id": self.id,
            "nome": self.nome, "pasta": self.pasta, "cnpj": self.cnpj,
            "contatos": [c.to_dict() for c in self.contatos],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Cliente":
        return cls(
            d["id"], d["nome"], d["pasta"], d.get("cnpj", ""),
            [Contato.from_dict(c) for c in d.get("contatos", [])],
            d.get("versao_formato", VERSAO_FORMATO),
        )


@dataclass
class Container:
    id: str
    tipo: str  # "projeto" ou "maquina"
    codigo: str
    nome: str
    pasta: str
    cliente_id: str | None = None
    pedido: str = ""
    responsavel: str = ""
    descricao: str = ""
    situacao: str = "ativo"  # "ativo" ou "concluido"
    contatos: list[Contato] = field(default_factory=list)
    documentos: dict[str, Documento] = field(default_factory=dict)
    historico: list[Evento] = field(default_factory=list)
    versao_formato: int = VERSAO_FORMATO

    def to_dict(self) -> dict:
        return {
            "versao_formato": self.versao_formato, "id": self.id,
            "tipo": self.tipo, "codigo": self.codigo, "nome": self.nome,
            "pasta": self.pasta, "cliente_id": self.cliente_id,
            "pedido": self.pedido, "responsavel": self.responsavel,
            "descricao": self.descricao, "situacao": self.situacao,
            "contatos": [c.to_dict() for c in self.contatos],
            "documentos": {k: v.to_dict() for k, v in self.documentos.items()},
            "historico": [e.to_dict() for e in self.historico],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Container":
        return cls(
            d["id"], d["tipo"], d.get("codigo", ""), d["nome"], d["pasta"],
            d.get("cliente_id"), d.get("pedido", ""), d.get("responsavel", ""),
            d.get("descricao", ""), d.get("situacao", "ativo"),
            [Contato.from_dict(c) for c in d.get("contatos", [])],
            {k: Documento.from_dict(v) for k, v in d.get("documentos", {}).items()},
            [Evento.from_dict(e) for e in d.get("historico", [])],
            d.get("versao_formato", VERSAO_FORMATO),
        )
