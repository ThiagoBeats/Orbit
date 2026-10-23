import getpass
import socket
from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    usuario: str
    computador: str


def current_identity() -> Identity:
    return Identity(getpass.getuser(), socket.gethostname())
