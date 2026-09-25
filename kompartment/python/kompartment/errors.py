"""The errors the API raises."""

from __future__ import annotations

from typing import List, Optional


class KompartmentError(Exception):
    """Base class for everything this package raises about a model."""


class EditError(KompartmentError, ValueError):
    """An edit the model cannot take: a name already used, a block that does
    not exist, a value outside what the setting allows, a delete that would
    leave an equation reading nothing.

    ``detail`` names what was in the way, where that is a list of blocks.
    """

    def __init__(self, message: str, detail: Optional[List[str]] = None) -> None:
        super().__init__(message)
        self.detail = detail


class ValidationError(KompartmentError):
    """What Kompartment's own validator found wrong with a model.

    Raised by :meth:`kompartment.Model.validate`; ``problems`` lists every
    message, ``block`` the block the first one is about, when it is.
    """

    def __init__(self, message: str, problems: Optional[List[str]] = None,
                 block: Optional[str] = None) -> None:
        super().__init__(message)
        self.problems = problems or [message]
        self.block = block
