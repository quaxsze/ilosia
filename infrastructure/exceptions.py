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
