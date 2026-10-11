class ProviderError(Exception):
    """Only safe codes/messages; never include provider bodies or authorization headers."""

    def __init__(self, code, message, correction_feedback=None, receipt=None):
        self.code = code
        self.correction_feedback = correction_feedback
        self.receipt = receipt
        super().__init__(message)
