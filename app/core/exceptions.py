class AuthenticationError(Exception):
    pass


class AuthorizationError(Exception):
    pass


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


class DatabaseOperationError(Exception):
    pass


class WorkflowError(Exception):
    pass