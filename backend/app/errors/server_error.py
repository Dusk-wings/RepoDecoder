class ServerError(Exception):
    def __init__(self, message: str, status: int = 500) -> None:
        self.message = message
        self.status = status
        super().__init__(message)
