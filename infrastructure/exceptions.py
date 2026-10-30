class HelmInstallError(RuntimeError):
    pass


class HelmUninstallError(RuntimeError):
    pass


class ClusterUnavailableError(RuntimeError):
    pass


class StorageError(RuntimeError):
    pass


class ServiceQuotaExceeded(RuntimeError):
    pass


class WarpgateError(RuntimeError):
    def __init__(self, message, *, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class WarpgateIdentityCollision(WarpgateError):
    pass
