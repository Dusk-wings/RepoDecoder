class NotFoundError(Exception):
    def __init__(self, message: str, status: int = 404) -> None:
        self.message = message
        self.status = status
        super().__init__(message)
