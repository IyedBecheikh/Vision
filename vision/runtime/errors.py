class WorkflowError(RuntimeError):
    """A safe, user-actionable workflow failure."""


class ValidationError(WorkflowError):
    """Input or installed state violates the workflow contract."""


class TransactionError(WorkflowError):
    """A filesystem transaction failed and required rollback."""
