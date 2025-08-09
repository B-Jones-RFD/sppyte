class Error(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class AuthenticationError(Error):
    def __init__(message: str):
        super(message)


class ConnectionError(Error):
    def __init__(message: str):
        super(message)
