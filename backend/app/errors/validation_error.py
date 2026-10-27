class ValidationError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        self.status = status
        self.message = message
        super().__init__(message)