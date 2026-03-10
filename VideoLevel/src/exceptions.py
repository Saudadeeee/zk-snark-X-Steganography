"""
Custom exceptions for ZK-SNARK Video Steganography.
"""


class ZKStegoError(Exception):
    """Base exception for all ZK-Stego errors"""

    def __init__(self, message: str, **context):
        super().__init__(message)
        self.message = message
        self.context = context

    def __str__(self):
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{self.message} (Context: {context_str})"
        return self.message


class EmbeddingError(ZKStegoError):
    """Error during payload embedding"""
    pass


class SafetyFilterError(ZKStegoError):
    """Error in CAVLC Safety Filter"""
    pass


class InsufficientCapacityError(EmbeddingError):
    """Not enough embedding capacity for payload"""

    def __init__(self, required_bits: int, available_bits: int, **context):
        message = (
            f"Insufficient embedding capacity: need {required_bits} bits "
            f"but only {available_bits} bits available "
            f"({available_bits - required_bits} bits short)"
        )
        super().__init__(message, required_bits=required_bits,
                         available_bits=available_bits, **context)
        self.required_bits = required_bits
        self.available_bits = available_bits
