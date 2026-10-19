class GitHubError(Exception):
    """Base class for GitHub-related errors."""


class GitHubResponseError(GitHubError):
    """Raised when GitHub returns an unsuccessful HTTP response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        upstream_status: int | None = None,
    ) -> None:
        self.status_code = status_code
        self.upstream_status = upstream_status
        super().__init__(message)


class GitHubConnectionError(GitHubError):
    """Raised when a connection to GitHub cannot be established."""
