class Error(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ResponseFormatError(Error):
    pass
